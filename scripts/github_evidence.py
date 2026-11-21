"""Operator-only GitHub GET adapter for offline supervised task reconciliation."""

import argparse
import base64
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from daf.contract import Refused, keys, require, sha  # noqa: E402
from daf.external_receipts import validate_external_receipt, validate_repository  # noqa: E402
from daf.receipt_bridge import read_bytes, read_document  # noqa: E402
from daf.supervised_handoff import (  # noqa: E402
    SUPPLIED,
    positive_id,
    reconcile_receipt,
    validate_bundle,
)

MAX_RESPONSE = 2 * 1024 * 1024
PAGE = 100
MAX_WORKFLOWS = 24
# Initial PR and files reads plus the final PR read, and four reads per workflow.
MAX_GETS = 3 + 4 * MAX_WORKFLOWS
RUN_PENDING = ("queued", "in_progress", "requested", "waiting", "pending")
CONCLUSIONS = (
    "success",
    "failure",
    "cancelled",
    "neutral",
    "skipped",
    "timed_out",
    "action_required",
    "stale",
    "startup_failure",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_upstream_key")
        result[key] = value
    return result


def _nonfinite(_):
    raise Refused("nonfinite_upstream_value")


def _github_reader(repository, token):
    """Build a fixed-origin, credentialed GET transport with a bounded request window."""
    opener = build_opener(ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + 90
    calls = 0

    def get(path):
        nonlocal calls
        calls += 1
        require(calls <= MAX_GETS and time.monotonic() < deadline, "observation_budget_exhausted")
        request = Request(  # noqa: S310 - fixed HTTPS host and validated repository
            f"https://api.github.com/repos/{repository}{path}",
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Authorization": f"Bearer {token}",
            },
        )
        try:
            with opener.open(request, timeout=8) as response:
                require(response.status == 200, "github_response_status")
                require(
                    response.headers.get_content_type() == "application/json", "github_content_type"
                )
                require('rel="next"' not in response.headers.get("Link", ""), "partial_pagination")
                body = bytearray()
                while block := response.read1(65536):
                    body.extend(block)
                    require(len(body) <= MAX_RESPONSE, "github_response_too_large")
                    require(time.monotonic() < deadline, "observation_budget_exhausted")
                return json.loads(
                    body.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite
                )
        except HTTPError as error:
            with error:
                if error.code == 429 or (
                    error.code == 403
                    and (
                        error.headers.get("X-RateLimit-Remaining") == "0"
                        or error.headers.get("Retry-After")
                    )
                ):
                    raise Refused("github_rate_limited") from None
                if error.code == 401:
                    raise Refused("github_credential_invalid_or_expired") from None
                if error.code in {403, 404}:
                    raise Refused("github_access_denied_or_unavailable") from None
                raise Refused("github_http_refused") from None
        except OSError:
            raise Refused("github_transport_interrupted") from None

    return get


def obj(value):
    require(isinstance(value, dict), "malformed_github_response")
    return value


def complete(items, total):
    require(
        isinstance(items, list)
        and type(total) is int
        and 0 <= total <= PAGE
        and len(items) == total,
        "partial_or_malformed_listing",
    )
    return [obj(item) for item in items]


def matches_repo(value, repository):
    full = obj(value).get("full_name")
    return isinstance(full, str) and full.lower() == repository.lower()


def pr_identity(raw, repository, number, head, baseline):
    pr = obj(raw)
    require(positive_id(pr.get("number")) == number, "wrong_pr")
    for side, commit in (("head", head), ("base", baseline)):
        ref = obj(pr.get(side))
        require(matches_repo(ref.get("repo"), repository), "wrong_github_repository")
        require(ref.get("sha") == commit, "wrong_pr_revision")
    require(pr.get("state") in ("open", "closed"), "malformed_github_response")
    return pr.get("changed_files"), timestamp(pr.get("updated_at")), pr["state"]


def timestamp(value):
    require(isinstance(value, str), "malformed_github_response")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def run_identity(raw, repository, selection, head, now):
    run = obj(raw)
    require(matches_repo(run.get("repository"), repository), "wrong_github_repository")
    require(matches_repo(run.get("head_repository"), repository), "wrong_github_repository")
    require(run.get("head_sha") == head, "wrong_run_revision")
    require(
        positive_id(run.get("id")) == selection["run_id"]
        and positive_id(run.get("run_attempt")) == selection["attempt"],
        "wrong_run_attempt",
    )
    require(
        positive_id(run.get("workflow_id")) == selection["workflow_id"]
        and run.get("path") == selection["workflow_path"],
        "wrong_workflow",
    )
    require(run.get("event") in ["push", "workflow_dispatch"], "unsupported_run_event")
    stamp = timestamp(run.get("updated_at"))
    require(now - timedelta(hours=24) <= stamp <= now + timedelta(minutes=1), "stale_run")
    status, conclusion = run.get("status"), run.get("conclusion")
    require(status == "completed" or status in RUN_PENDING, "unsupported_run_status")
    require(
        "conclusion" in run
        and (conclusion in CONCLUSIONS if status == "completed" else conclusion is None),
        "invalid_run_conclusion",
    )
    return status, conclusion, stamp


def check_workflow(get, path, head, expected):
    response = obj(get(f"/contents/{quote(path, safe='/')}?ref={head}"))
    require(
        response.get("type") == "file"
        and response.get("path") == path
        and response.get("encoding") == "base64",
        "wrong_workflow",
    )
    data = base64.b64decode(response["content"].replace("\n", ""), validate=True)
    require(hashlib.sha256(data).hexdigest() == expected, "wrong_workflow_digest")


def check_artifact(get, run_id, name, head, repository_id):
    response = obj(get(f"/actions/runs/{run_id}/artifacts?per_page={PAGE}"))
    files = complete(response.get("artifacts"), response.get("total_count"))
    matched = [item for item in files if item.get("name") == name]
    require(len(matched) == 1, "artifact_identity_mismatch")
    artifact = matched[0]
    source = obj(artifact.get("workflow_run"))
    require(
        positive_id(source.get("id")) == run_id
        and source.get("head_sha") == head
        and positive_id(source.get("repository_id")) == repository_id
        and positive_id(source.get("head_repository_id")) == repository_id
        and artifact.get("expired") is False,
        "artifact_identity_mismatch",
    )
    return positive_id(artifact.get("id"))


def _observe(bundle, receipt, selection, allowed, get, now, output):
    request = validate_bundle(bundle)["request"]
    claim = validate_external_receipt(receipt)
    choice = keys(selection, {"repository", "head_sha", "pr", "runs"})
    repository = validate_repository(choice["repository"])
    require(
        repository == allowed == request["repository"] == claim["repository"],
        "repository_not_allowlisted",
    )
    head = sha(choice["head_sha"], 40)
    baseline = request["baseline_sha"]
    number = positive_id(choice["pr"])
    link = f"https://github.com/{repository}/pull/{number}"
    require(
        claim["head_sha"] == head and claim["baseline_sha"] == baseline and claim["pr_url"] == link,
        "receipt_selection_mismatch",
    )
    required = {}
    for check in request["required_checks"]:
        required.setdefault(check["workflow_path"], {})[check["name"]] = check
    sources = choice["runs"]
    require(
        isinstance(sources, list) and len(sources) == len(required) <= MAX_WORKFLOWS,
        "invalid_run_selection",
    )
    paths, runs = set(), set()
    for raw in sources:
        pick = keys(raw, {"workflow_path", "workflow_id", "run_id", "attempt"})
        path = pick["workflow_path"]
        require(
            isinstance(path, str) and path in required and path not in paths,
            "invalid_run_selection",
        )
        paths.add(path)
        for field in ("workflow_id", "run_id", "attempt"):
            positive_id(pick[field])
        require(pick["run_id"] not in runs, "invalid_run_selection")
        runs.add(pick["run_id"])

    output.update(repository=repository, head_sha=head, pr=number)
    pr = f"/pulls/{number}"
    before = pr_identity(get(pr), repository, number, head, baseline)
    changed = []
    for file in complete(get(f"{pr}/files?per_page={PAGE}"), before[0]):
        changed.append(file.get("filename"))
        if file.get("status") == "renamed":
            changed.append(file.get("previous_filename"))
    require(
        all(isinstance(name, str) and name in request["allowed_paths"] for name in changed),
        "changed_path_out_of_scope",
    )
    require(len(set(changed)) == len(changed), "duplicate_pr_path")
    records, jobs_seen, final_reads = [], set(), []
    artifacts_required = False
    for pick in sources:
        workflow = pick["workflow_path"]
        checks = required[workflow]
        check_workflow(get, workflow, head, next(iter(checks.values()))["workflow_sha256"])
        run_id, attempt = pick["run_id"], pick["attempt"]
        endpoint = f"/actions/runs/{run_id}"
        raw = obj(get(endpoint))
        observed = run_identity(raw, repository, pick, head, now)
        run_status, run_conclusion, _ = observed
        output["workflow_runs"].append({**pick, "status": run_status, "conclusion": run_conclusion})
        final_reads.append((endpoint, pick, observed))
        response = obj(get(f"{endpoint}/attempts/{attempt}/jobs?per_page={PAGE}"))
        jobs = complete(response.get("jobs"), response.get("total_count"))
        matched = set()
        for job in jobs:
            job_id = positive_id(job.get("id"))
            require(job_id not in jobs_seen, "duplicate_job")
            jobs_seen.add(job_id)
            require(
                positive_id(job.get("run_id")) == run_id
                and positive_id(job.get("run_attempt")) == attempt,
                "wrong_job_attempt",
            )
            require(job.get("head_sha") == head, "wrong_job_revision")
            name = job.get("name")
            require(isinstance(name, str), "malformed_github_response")
            if name not in checks:
                continue
            require(name not in matched, "duplicate_required_job")
            matched.add(name)
            status, conclusion = job.get("status"), job.get("conclusion")
            require(status in ("queued", "in_progress", "completed"), "unsupported_job_status")
            require(
                (status != "completed" and conclusion is None)
                or (status == "completed" and conclusion in CONCLUSIONS),
                "invalid_job_conclusion",
            )
            snapshot = {
                "name": name,
                "run_id": run_id,
                "run_attempt": attempt,
                "job_id": job_id,
                "status": status,
                "conclusion": conclusion,
            }
            output["checks"].append(snapshot)
            require(
                run_status != "completed" or status == "completed",
                "completed_run_has_pending_job",
            )
            check = checks[name]
            if (artifact := check["artifact_name"]) is not None:
                artifacts_required = True
                if status == "completed":
                    repository_id = positive_id(obj(raw["repository"]).get("id"))
                    snapshot["run_artifact_id"] = check_artifact(
                        get, run_id, artifact, head, repository_id
                    )
            records.append(
                {
                    **snapshot,
                    "validator_id": check["validator_id"],
                    "source": check["source"],
                    "head_sha": head,
                    "workflow_path": workflow,
                    "workflow_sha256": check["workflow_sha256"],
                    "url": f"https://github.com/{repository}/actions/runs/{run_id}",
                    "artifact": None,
                }
            )
        require(matched == set(checks), "missing_required_check")

    for endpoint, pick, observed in final_reads:
        require(run_identity(get(endpoint), repository, pick, head, now) == observed, "run_changed")
    require(pr_identity(get(pr), repository, number, head, baseline) == before, "pr_changed")
    require(not artifacts_required, "artifact_job_provenance_unavailable")
    require(
        all(run["conclusion"] == "success" for run in output["workflow_runs"]),
        "workflow_run_not_successful",
    )
    output["comparison"] = reconcile_receipt(
        bundle,
        receipt,
        {
            "schema_version": 1,
            "status": SUPPLIED,
            "repository": repository,
            "pr_url": link,
            "baseline_sha": baseline,
            "head_sha": head,
            "changed_paths": changed,
            "checks": records,
        },
    )


def collect(bundle, receipt, selection, allowed, *, token=None, reader=None, now=None):
    """Keep injected observations explicitly unverified and separate from transport provenance."""
    observed_at = now or datetime.now(UTC)
    result = {
        "status": "refused",
        "execution_authority": False,
        "workflow_runs": [],
        "checks": [],
        "provenance": "supplied_adapter_unverified" if reader is not None else "unobserved",
        "observed_at": observed_at.isoformat(),
    }
    try:
        validate_repository(allowed)
        if reader is None:
            require(
                isinstance(token, str) and re.fullmatch(r"[!-~]{20,512}", token), "token_required"
            )
            wire = _github_reader(allowed, token)

            def reader(path):
                value = wire(path)
                result["provenance"] = "authenticated_github_get"
                return value

        _observe(bundle, receipt, selection, allowed, reader, observed_at, result)
        result["status"] = "compared"
    except Refused as error:
        result["reason"] = str(error)
    except (OSError, KeyboardInterrupt):
        result["reason"] = "observation_interrupted"
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        result["reason"] = "malformed_github_or_local_input"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-repository", required=True)
    parser.add_argument("--token-file", required=True, type=Path)
    for name in ("bundle", "receipt", "selection"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args(argv)
    try:
        documents = [read_document(path) for path in (args.bundle, args.receipt, args.selection)]
        token = read_bytes(args.token_file).decode("ascii").strip()
        result = collect(*documents, args.allow_repository, token=token)
    except (Refused, OSError, ValueError, TypeError, RecursionError, KeyboardInterrupt):
        result = {
            "status": "refused",
            "execution_authority": False,
            "reason": "invalid_or_unavailable_local_input",
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "compared" else 2


if __name__ == "__main__":
    raise SystemExit(main())
