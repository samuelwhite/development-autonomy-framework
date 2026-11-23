"""Run or observe one explicitly approved documentation candidate on a private validator."""

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_evidence import (  # noqa: E402
    check_workflow,
    complete,
    obj,
    pr_identity,
    run_identity,
)

from daf.contract import Refused, canonical, digest, keys, require, sha  # noqa: E402
from daf.external_receipts import validate_repository  # noqa: E402
from daf.receipt_bridge import (  # noqa: E402
    append_observation,
    check_interruption,
    journal_directory,
    read_document,
)
from daf.supervised_handoff import (  # noqa: E402
    file_path,
    interrupted_attempt,
    positive_id,
    text_field,
    validate_bundle,
)

WORKFLOW = ".github/workflows/daf-documentation-candidate.yml"
WORKFLOW_FILE = WORKFLOW.rsplit("/", 1)[1]
JOB = "DAF documentation candidate on HomeCI"
STEPS = (
    ("Check dispatch inputs and runner identity", "runner_identity_check_failed"),
    ("Check out the reviewed DAF baseline", "baseline_checkout_failed"),
    ("Verify one documentation change and exact checkout", "candidate_scope_or_checkout_failed"),
    ("Run portable contracts on the candidate", "portable_contracts_failed"),
    ("Run supervised handoff and receipt regressions", "supervised_receipts_failed"),
    ("Record candidate verification outcome", "verification_summary_missing"),
)


def validate_approval(bundle, value, allowed_validator):
    task = validate_bundle(bundle)
    approval = keys(
        value,
        {
            "task_sha256",
            "candidate_sha",
            "candidate_pr",
            "validator_repository",
            "workflow_id",
            "workflow_revision",
            "workflow_path",
            "workflow_sha256",
            "runner",
        },
    )
    require(sha(approval["task_sha256"]) == task["task_sha256"], "wrong_approved_task")
    require(len(task["request"]["allowed_paths"]) == 1, "one_document_required")
    path = file_path(task["request"]["allowed_paths"][0])
    require(path.startswith("docs/") and path.endswith(".md"), "one_document_required")
    repository = validate_repository(approval["validator_repository"]).lower()
    require(
        repository == validate_repository(allowed_validator).lower()
        and repository != task["request"]["repository"].lower(),
        "validator_repository_not_allowed",
    )
    sha(approval["candidate_sha"], 40)
    sha(approval["workflow_revision"], 40)
    require(approval["workflow_path"] == WORKFLOW, "wrong_approved_workflow_path")
    required_check = {
        "name": JOB,
        "validator_id": repository,
        "source": "github_actions",
        "workflow_path": approval["workflow_path"],
        "workflow_sha256": sha(approval["workflow_sha256"]),
        "artifact_name": None,
    }
    require(
        task["request"]["required_checks"] == [required_check],
        "task_workflow_requirement_mismatch",
    )
    positive_id(approval["candidate_pr"])
    positive_id(approval["workflow_id"])
    text_field(approval["runner"])
    return task, approval


def check_main(get, root, revision, reason):
    main = obj(get(root + "/git/ref/heads/main"))
    require(
        main.get("ref") == "refs/heads/main" and obj(main.get("object")).get("sha") == revision,
        reason,
    )


def check_candidate(task, approval, get):
    request = task["request"]
    repository = request["repository"]
    number = approval["candidate_pr"]
    head = approval["candidate_sha"]
    base = request["baseline_sha"]
    root = f"/repos/{repository}"
    path = f"{root}/pulls/{number}"

    def identity(pr):
        count, _, state = pr_identity(pr, repository, number, head, base)
        require(state == "open" and pr.get("draft") is True, "candidate_draft_required")
        require(type(count) is int and count == 1, "candidate_scope_mismatch")
        require(obj(pr.get("base")).get("ref") == "main", "wrong_candidate_base_branch")
        return pr["updated_at"]

    stamp = identity(get(path))
    files = complete(get(path + "/files?per_page=100"), 1)
    require(
        files[0].get("filename") == request["allowed_paths"][0]
        and files[0].get("status") == "modified"
        and "previous_filename" not in files[0],
        "candidate_scope_mismatch",
    )
    require(stamp == identity(get(path)), "candidate_changed_during_observation")
    check_main(get, root, base, "candidate_main_revision_changed")


def title(approval):
    return (
        f"DAF docs {approval['task_sha256']} PR {approval['candidate_pr']}"
        f" at {approval['candidate_sha']}"
    )


def validator_api(approval, get):
    root = f"/repos/{approval['validator_repository']}"
    repo = obj(get(root))
    require(
        repo.get("private") is True
        and str(repo.get("full_name", "")).lower() == approval["validator_repository"].lower(),
        "private_validator_required",
    )

    def read(path):
        return get(root + path)

    workflow = obj(read(f"/actions/workflows/{WORKFLOW_FILE}"))
    require(
        workflow.get("id") == approval["workflow_id"]
        and workflow.get("path") == WORKFLOW
        and workflow.get("state") == "active",
        "wrong_validator_workflow",
    )
    return read


def reservation(database, approval, *, create=False):
    """Commit intent before POST. An existing reservation can only be observed."""
    if not create and not database.exists():
        return False, None
    connection = str(database) if create else database.as_uri() + "?mode=ro"
    with closing(sqlite3.connect(connection, uri=not create)) as db, db:
        if create:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS attempts "
                "(task TEXT PRIMARY KEY, approval TEXT NOT NULL, run INTEGER)"
            )
        task = approval["task_sha256"]
        fingerprint = digest(approval)
        row = db.execute("SELECT approval, run FROM attempts WHERE task=?", (task,)).fetchone()
        if row is not None:
            require(row[0] == fingerprint, "attempt_approval_changed")
            return False, row[1]
        if create:
            db.execute("INSERT INTO attempts VALUES (?, ?, NULL)", (task, fingerprint))
        return create, None


def find_run(approval, get):
    workflow = approval["workflow_id"]
    listing = obj(get(f"/actions/workflows/{workflow}/runs?event=workflow_dispatch&per_page=100"))
    runs = complete(listing.get("workflow_runs"), listing.get("total_count"))
    prefix = f"DAF docs {approval['task_sha256']} "
    related = [
        run
        for run in runs
        if isinstance(run.get("display_title"), str) and run["display_title"].startswith(prefix)
    ]
    require(len(related) <= 1, "multiple_runs_for_attempt")
    if not related:
        return None
    require(related[0]["display_title"] == title(approval), "candidate_conflicts_with_existing_run")
    require(related[0].get("run_attempt") == 1, "unexpected_additional_run_attempt")
    return positive_id(related[0].get("id"))


def run_or_resume(database, approval, get, post):
    run_id = find_run(approval, get)
    # Read-only observation and same-task retries don't create an attempt.
    new, recorded_run = reservation(database, approval, create=post is not None)
    if recorded_run is not None:
        require(run_id in (None, recorded_run), "wrong_run_attempt")
        return recorded_run
    if post is None:
        require(run_id is not None, "run_not_observed")
        return run_id
    if run_id is None and new:
        check_main(get, "", approval["workflow_revision"], "validator_main_revision_changed")
        try:
            run_id = positive_id(obj(post(approval)).get("workflow_run_id"))
        except Refused:
            raise Refused("dispatch_outcome_unknown") from None
    require(run_id is not None, "dispatch_outcome_unknown")
    with closing(sqlite3.connect(database)) as db, db:
        changed = db.execute(
            "UPDATE attempts SET run=? WHERE task=? AND (run IS NULL OR run=?)",
            (run_id, approval["task_sha256"], run_id),
        ).rowcount
        require(changed == 1, "wrong_run_attempt")
    return run_id


def observe_run(approval, run_id, get, result):
    selection = {
        "workflow_path": approval["workflow_path"],
        "workflow_id": approval["workflow_id"],
        "run_id": run_id,
        "attempt": 1,
    }
    path = f"/actions/runs/{run_id}/attempts/1"

    def identity(run):
        status = run_identity(
            run,
            approval["validator_repository"],
            selection,
            approval["workflow_revision"],
            datetime.now(UTC),
        )
        require(
            run.get("head_branch") == "main"
            and run.get("event") == "workflow_dispatch"
            and run.get("display_title") == title(approval),
            "wrong_workflow_dispatch",
        )
        return status

    run = obj(get(path))
    status, conclusion, stamp = identity(run)
    state = {"completed": "terminal", "in_progress": "running", "waiting": "blocked"}
    result.update(
        run_id=run_id,
        attempt=1,
        run_status=status,
        run_conclusion=conclusion,
        state=state.get(status, "queued"),
    )
    response = obj(get(path + "/jobs?per_page=100"))
    jobs = complete(response.get("jobs"), response.get("total_count"))
    require(len(jobs) <= 1, "unexpected_workflow_jobs")
    if jobs:
        job = jobs[0]
        job_id = positive_id(job.get("id"))
        result.update(
            job_id=job_id, job_status=job.get("status"), job_conclusion=job.get("conclusion")
        )
        require(
            job.get("run_id") == run_id
            and job.get("run_attempt") == 1
            and job.get("head_sha") == approval["workflow_revision"]
            and job.get("name") == JOB,
            "wrong_workflow_job",
        )
        runner = job.get("runner_name")
        if runner:
            require(
                runner == approval["runner"]
                and isinstance(job.get("labels"), list)
                and "self-hosted" in job["labels"],
                "wrong_runner",
            )
            result["runner"] = runner
        steps = (
            complete(job.get("steps"), len(job["steps"]))
            if isinstance(job.get("steps"), list)
            else []
        )
        for step, reason in STEPS:
            found = [item for item in steps if item.get("name") == step]
            require(len(found) <= 1, "duplicate_verification_step")
            if found and found[0].get("status") == "completed":
                if found[0].get("conclusion") == "success" and step == STEPS[2][0]:
                    result["observed_checkout"] = approval["candidate_sha"]
                if found[0].get("conclusion") == "failure":
                    result["step_failure"] = reason
                    break
    require(
        identity(obj(get(path))) == (status, conclusion, stamp), "run_changed_during_observation"
    )
    if status != "completed":
        return
    failure = result.get("step_failure", "workflow_failure") if conclusion == "failure" else None
    require(conclusion == "success", failure or f"workflow_{conclusion}")
    require(
        jobs
        and result.get("runner")
        and result.get("job_status") == "completed"
        and result.get("job_conclusion") == "success",
        "successful_job_missing",
    )
    for step, reason in STEPS:
        require(
            any(
                item.get("name") == step
                and item.get("status") == "completed"
                and item.get("conclusion") == "success"
                for item in steps
            ),
            reason,
        )
    result["verification"] = "passed"


def verify(bundle, value, allowed_validator, journal, get, post=None):
    result = {
        "status": "github_api_observation",
        "execution_authority": False,
        "independent_producer_provenance": False,
        "verification": "incomplete",
        "state": "blocked",
    }
    try:
        task, approval = validate_approval(bundle, value, allowed_validator)
        result.update(approval)
        result.pop("runner")
        result.update(
            repository=task["request"]["repository"], baseline_sha=task["request"]["baseline_sha"]
        )
        database = journal_directory(journal, "homeci.sqlite") / "homeci.sqlite"
        if (journal / "journal.sqlite").exists():
            check_interruption(journal, digest(interrupted_attempt(task)))
        read = validator_api(approval, get)
        check_workflow(
            read,
            approval["workflow_path"],
            approval["workflow_revision"],
            approval["workflow_sha256"],
        )
        check_candidate(task, approval, get)
        run_id = run_or_resume(database, approval, read, post)
        result["run_id"] = run_id
        result["evidence_url"] = (
            f"https://github.com/{approval['validator_repository']}/actions/runs/{run_id}/attempts/1"
        )
        observe_run(approval, run_id, read, result)
        try:
            check_candidate(task, approval, get)
            if (journal / "journal.sqlite").exists():
                check_interruption(journal, digest(interrupted_attempt(task)))
        except Refused:
            result["verification"] = "incomplete"
            raise
    except Refused as error:
        result["reason"] = str(error)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        result["reason"] = "verification_input_or_journal_unavailable"
    if post is not None and "task_sha256" in result:
        try:
            append_observation(journal, result)
        except (Refused, OSError, sqlite3.Error):
            result.update(verification="incomplete", journal_reason="observation_not_retained")
    return result


def gh_api(path, payload=None):
    command = [
        "gh",
        "api",
        "--hostname",
        "github.com",
        "--method",
        "GET" if payload is None else "POST",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        path,
    ]
    if payload is not None:
        command += ["--input", "-"]
    try:
        process = subprocess.run(
            command,
            input=None if payload is None else canonical(payload).encode(),
            capture_output=True,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Refused("github_request_unavailable") from None
    require(process.returncode == 0, "github_request_failed")
    require(len(process.stdout) <= 2 * 1024 * 1024, "github_response_too_large")
    try:
        return json.loads(process.stdout)
    except ValueError:
        raise Refused("malformed_github_response") from None


def dispatch(approval):
    return gh_api(
        f"/repos/{approval['validator_repository']}/actions/workflows/{WORKFLOW_FILE}/dispatches",
        {
            "ref": "main",
            "inputs": {
                "task_sha256": approval["task_sha256"],
                "candidate_pr": str(approval["candidate_pr"]),
                "candidate_sha": approval["candidate_sha"],
                "expected_forge_sha": approval["workflow_revision"],
            },
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "approval", type=Path, help="Private, separately reviewed candidate binding"
    )
    parser.add_argument(
        "--journal", type=Path, required=True, help="Existing private journal directory"
    )
    parser.add_argument(
        "--allow-validator", required=True, help="Exact authorised private repository"
    )
    parser.add_argument(
        "--dispatch",
        action="store_true",
        help="Request one run with the operator's GitHub CLI session",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=0,
        help="Observe nonterminal runs for up to 1200 seconds",
    )
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 1200:
        parser.error("wait seconds must be between 0 and 1200")
    try:
        bundle, approval = read_document(args.bundle), read_document(args.approval)
        deadline = time.monotonic() + args.wait_seconds
        while True:
            result = verify(
                bundle,
                approval,
                args.allow_validator,
                args.journal,
                gh_api,
                dispatch if args.dispatch else None,
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0 or "reason" in result or "journal_reason" in result:
                break
            if result["state"] not in {"queued", "running", "blocked"}:
                break
            time.sleep(min(remaining, 15))
    except (Refused, OSError, ValueError):
        result = {"verification": "incomplete", "reason": "invalid_verification_input"}
    print(json.dumps(result))
    if result["verification"] == "passed":
        return 0
    return 2 if "reason" in result or "journal_reason" in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
