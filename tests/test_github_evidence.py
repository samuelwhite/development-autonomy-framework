import base64
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest

from daf.contract import Refused
from daf.supervised_handoff import SUPPLIED, prepare_task
from scripts import github_evidence as adapter

ROOT = Path(__file__).resolve().parents[1] / "src/daf/examples/receipts"
NOW = datetime(2026, 11, 21, 8, tzinfo=UTC)
STAMP = "2026-11-21T07:00:00Z"
REPO = "example/product"
HEAD = "c" * 40
BASE = "b" * 40
WORKFLOW = ".github/workflows/offline.yml"
WORKFLOW_BYTES = b"name: deterministic receipt fixture"
PR = "/pulls/3"
RUN = "/actions/runs/12"
JOBS = f"{RUN}/attempts/1/jobs?per_page=100"
FILES = f"{PR}/files?per_page=100"
ARTIFACTS = f"{RUN}/artifacts?per_page=100"


def fixture(artifact=False):
    request = json.loads((ROOT / "request.json").read_text())
    check = request["required_checks"][0]
    check["workflow_sha256"] = hashlib.sha256(WORKFLOW_BYTES).hexdigest()
    if not artifact:
        check.update(source="github_actions", artifact_name=None)
    bundle = prepare_task(request)
    receipt = json.loads((ROOT / "receipt.json").read_text())
    receipt["task_sha256"] = bundle["task_sha256"]
    selection = {
        "repository": REPO,
        "head_sha": HEAD,
        "pr": 3,
        "runs": [{"workflow_path": WORKFLOW, "workflow_id": 81, "run_id": 12, "attempt": 1}],
    }
    repository = {"full_name": REPO, "id": 87}
    answers = {
        PR: {
            "number": 3,
            "changed_files": 1,
            "updated_at": STAMP,
            "state": "open",
            "head": {"sha": HEAD, "repo": repository},
            "base": {"sha": BASE, "repo": repository},
        },
        FILES: [{"filename": "src/example.py", "status": "modified"}],
        f"/contents/{WORKFLOW}?ref={HEAD}": {
            "type": "file",
            "path": WORKFLOW,
            "encoding": "base64",
            "content": base64.b64encode(WORKFLOW_BYTES).decode(),
        },
        RUN: {
            "id": 12,
            "run_attempt": 1,
            "workflow_id": 81,
            "path": WORKFLOW,
            "head_sha": HEAD,
            "repository": repository,
            "head_repository": repository,
            "updated_at": STAMP,
            "status": "completed",
            "conclusion": "success",
            "event": "push",
        },
        JOBS: {
            "total_count": 1,
            "jobs": [
                {
                    "id": 34,
                    "run_id": 12,
                    "run_attempt": 1,
                    "head_sha": HEAD,
                    "name": "offline",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        },
        ARTIFACTS: {
            "total_count": 1,
            "artifacts": [
                {
                    "id": 56,
                    "name": "homeci-result",
                    "expired": False,
                    "workflow_run": {
                        "id": 12,
                        "head_sha": HEAD,
                        "repository_id": 87,
                        "head_repository_id": 87,
                    },
                }
            ],
        },
    }
    return (bundle, receipt, selection), answers


def observe(inputs, responses, *, allowed=REPO, reader=None):
    return adapter.collect(*inputs, allowed, reader=reader or responses.__getitem__, now=NOW)


def assert_refusal(result, reason):
    assert result["status"] == "refused"
    assert result["reason"] == reason
    assert result["execution_authority"] is False
    assert "comparison" not in result


def test_exact_head_comparison_cannot_upgrade_claims():
    inputs, responses = fixture()
    result = observe(inputs, responses)
    assert result["status"] == "compared"
    assert result["provenance"] == "supplied_adapter_unverified"
    assert result["execution_authority"] is False
    assert result["checks"][0]["job_id"] == 34
    assert result["workflow_runs"] == [
        {**inputs[2]["runs"][0], "status": "completed", "conclusion": "success"}
    ]
    assert result["comparison"]["status"] == SUPPLIED
    assert result["comparison"]["all_required_checks_claimed_passed"] is True


@pytest.mark.parametrize(
    ("path", "change", "reason"),
    [
        (PR, lambda row: row["head"].update(sha="d" * 40), "wrong_pr_revision"),
        (PR, lambda row: row["base"].update(sha="d" * 40), "wrong_pr_revision"),
        (PR, lambda row: row.update(changed_files=2), "partial_or_malformed_listing"),
        (
            PR,
            lambda row: row["head"]["repo"].update(full_name="different/project"),
            "wrong_github_repository",
        ),
        (RUN, lambda row: row.update(head_sha="d" * 40), "wrong_run_revision"),
        (RUN, lambda row: row.update(workflow_id=82), "wrong_workflow"),
        (RUN, lambda row: row.update(path=".github/workflows/other.yml"), "wrong_workflow"),
        (RUN, lambda row: row.update(event="pull_request"), "unsupported_run_event"),
        (RUN, lambda row: row.update(run_attempt=2), "wrong_run_attempt"),
        (RUN, lambda row: row.update(updated_at="2026-11-19T00:00:00Z"), "stale_run"),
        (RUN, lambda row: row.update(updated_at=[]), "malformed_github_response"),
        (JOBS, lambda row: row.update(total_count=101), "partial_or_malformed_listing"),
        (JOBS, lambda row: row.update(total_count=0, jobs=[]), "missing_required_check"),
        (JOBS, lambda row: row["jobs"][0].update(run_attempt=2), "wrong_job_attempt"),
        (JOBS, lambda row: row["jobs"][0].update(head_sha="d" * 40), "wrong_job_revision"),
        (JOBS, lambda row: row.update(total_count=2, jobs=row["jobs"] * 2), "duplicate_job"),
        (
            JOBS,
            lambda row: row.update(
                total_count=2, jobs=[*row["jobs"], {**row["jobs"][0], "id": 35}]
            ),
            "duplicate_required_job",
        ),
        (
            FILES,
            lambda rows: rows[0].update(status="renamed", previous_filename="out-of-scope"),
            "changed_path_out_of_scope",
        ),
    ],
)
def test_wrong_binding_is_refused(path, change, reason):
    inputs, responses = fixture()
    change(responses[path])
    assert_refusal(observe(inputs, responses), reason)


@pytest.mark.parametrize(
    ("status", "conclusion", "claim"),
    [
        ("queued", None, "pending"),
        ("in_progress", None, "pending"),
        ("completed", "cancelled", "failed"),
        ("completed", "failure", "failed"),
    ],
)
def test_preserves_pending_cancelled_and_failed_jobs(status, conclusion, claim):
    inputs, responses = fixture()
    inputs[1]["checks"][0]["result"] = claim
    responses[JOBS]["jobs"][0].update(status=status, conclusion=conclusion)
    if claim == "pending":
        responses[RUN].update(status=status, conclusion=None)
    result = observe(inputs, responses)
    assert result["checks"][0]["status"] == status
    assert result["checks"][0]["conclusion"] == conclusion
    if claim == "pending":
        assert_refusal(result, "workflow_run_not_successful")
    else:
        assert result["status"] == "compared"
        assert result["comparison"]["all_required_checks_claimed_passed"] is False


@pytest.mark.parametrize(
    ("status", "conclusion", "reason"),
    [
        (None, None, "unsupported_run_status"),
        (["completed"], "success", "unsupported_run_status"),
        ("unknown", None, "unsupported_run_status"),
        ("completed", None, "invalid_run_conclusion"),
        ("completed", ["success"], "invalid_run_conclusion"),
        ("completed", "unknown", "invalid_run_conclusion"),
        ("in_progress", "success", "invalid_run_conclusion"),
        ("pending", "failure", "invalid_run_conclusion"),
    ],
)
def test_malformed_workflow_outcomes_are_refused(status, conclusion, reason):
    inputs, responses = fixture()
    responses[RUN].update(status=status, conclusion=conclusion)
    result = observe(inputs, responses)
    assert_refusal(result, reason)
    assert result["workflow_runs"] == []


def test_absent_pending_conclusion_is_refused():
    inputs, responses = fixture()
    responses[RUN]["status"] = "waiting"
    del responses[RUN]["conclusion"]
    assert_refusal(observe(inputs, responses), "invalid_run_conclusion")


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [
        ("queued", None),
        ("in_progress", None),
        ("requested", None),
        ("waiting", None),
        ("pending", None),
        ("completed", "failure"),
        ("completed", "cancelled"),
        ("completed", "timed_out"),
        ("completed", "skipped"),
    ],
)
def test_successful_job_cannot_mask_workflow_outcome(status, conclusion):
    inputs, responses = fixture()
    responses[RUN].update(status=status, conclusion=conclusion)
    result = observe(inputs, responses)
    assert_refusal(result, "workflow_run_not_successful")
    assert result["workflow_runs"][0]["status"] == status
    assert result["workflow_runs"][0]["conclusion"] == conclusion
    assert result["checks"][0]["conclusion"] == "success"


def test_completed_workflow_with_pending_required_job_is_refused():
    inputs, responses = fixture()
    responses[JOBS]["jobs"][0].update(status="in_progress", conclusion=None)
    result = observe(inputs, responses)
    assert_refusal(result, "completed_run_has_pending_job")
    assert result["workflow_runs"][0]["status"] == "completed"
    assert result["checks"][0]["status"] == "in_progress"


def test_changed_workflow_outcome_is_refused_on_reread():
    inputs, responses = fixture()

    def reader(path):
        if path == JOBS:
            responses[RUN]["conclusion"] = "cancelled"
        return responses[path]

    assert_refusal(observe(inputs, responses, reader=reader), "run_changed")


def test_artifact_mismatch_and_missing_attempt_job_attribution_are_refused():
    inputs, responses = fixture(artifact=True)
    result = observe(inputs, responses)
    assert_refusal(result, "artifact_job_provenance_unavailable")
    assert result["checks"][0]["run_artifact_id"] == 56
    responses[ARTIFACTS]["artifacts"][0]["workflow_run"]["head_sha"] = "d" * 40
    assert_refusal(observe(inputs, responses), "artifact_identity_mismatch")


def test_allowlist_and_request_shape_fail_before_network():
    inputs, _ = fixture()
    reader = lambda _: pytest.fail("unexpected GET")  # noqa: E731
    assert_refusal(
        observe(inputs, {}, allowed="other/project", reader=reader), "repository_not_allowlisted"
    )
    inputs[2]["execution_authority"] = True
    assert_refusal(observe(inputs, {}, reader=reader), "invalid_contract_fields")


@pytest.mark.parametrize(
    ("moving", "reason"), [(PR, "wrong_pr_revision"), (RUN, "wrong_run_attempt")]
)
def test_refuses_drift_after_observing_jobs(moving, reason):
    inputs, responses = fixture()
    reads = 0

    def drift(path):
        nonlocal reads
        row = deepcopy(responses[path])
        if path == moving:
            reads += 1
            if reads == 2 and path == PR:
                row["head"]["sha"] = "d" * 40
            elif reads == 2:
                row["run_attempt"] = 2
        return row

    result = observe(inputs, {}, reader=drift)
    assert_refusal(result, reason)
    assert result["checks"][0]["conclusion"] == "success"


def test_interrupted_collection_does_not_report_completion():
    inputs, responses = fixture()

    def interrupted(path):
        if path == JOBS:
            raise KeyboardInterrupt
        return responses[path]

    assert_refusal(observe(inputs, {}, reader=interrupted), "observation_interrupted")


@pytest.mark.parametrize(
    ("code", "header", "reason"),
    [
        (401, {}, "github_credential_invalid_or_expired"),
        (404, {}, "github_access_denied_or_unavailable"),
        (403, {"X-RateLimit-Remaining": "0"}, "github_rate_limited"),
        (429, {}, "github_rate_limited"),
        (302, {}, "github_http_refused"),
    ],
)
def test_http_error_is_sanitised_and_get_is_fixed(monkeypatch, code, header, reason):
    inputs, _ = fixture()

    def open_request(request, *, timeout):
        assert request.full_url == "https://api.github.com/repos/example/product/pulls/3"
        assert request.method == "GET"
        assert request.headers["Authorization"] == f"Bearer {'z' * 32}"
        assert timeout == 8
        headers = Message()
        for name, value in header.items():
            headers[name] = value
        raise HTTPError(request.full_url, code, "never echo upstream error text", headers, None)

    class Opener:
        open = staticmethod(open_request)

    def opener(proxy, redirects):
        assert proxy.proxies == {}
        assert isinstance(redirects, adapter.NoRedirect)
        return Opener()

    monkeypatch.setattr(adapter, "build_opener", opener)
    result = adapter.collect(*inputs, REPO, token="z" * 32, now=NOW)
    assert_refusal(result, reason)
    assert result["provenance"] == "unobserved"
    assert "never echo" not in json.dumps(result)


def test_partial_link_and_json_duplicate_are_refused(monkeypatch):
    class Response:
        status = 200
        headers = Message()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read1(self, _size):
            return next(self.data)

    class Opener:
        open = staticmethod(lambda _request, **_kwargs: response)

    response = Response()
    response.headers["Content-Type"] = "application/json"
    response.headers["Link"] = '<https://api.github.com/page/2>; rel="next"'
    monkeypatch.setattr(adapter, "build_opener", lambda *_args: Opener())
    get = adapter._github_reader(REPO, "z" * 32)
    with pytest.raises(Refused, match="partial_pagination"):
        get(PR)
    del response.headers["Link"]
    response.data = iter([b'{"number":1,"number":2}', b""])
    with pytest.raises(Refused, match="duplicate_upstream_key"):
        get(PR)


def multiple_workflows(count):
    (bundle, receipt, selection), answers = fixture()
    request = bundle["request"]
    check = request["required_checks"][0].copy()
    claim = receipt["checks"][0].copy()
    request["required_checks"].clear()
    receipt["checks"].clear()
    selection["runs"].clear()
    for index in range(count):
        name = f"check-{index}"
        path = f".github/workflows/check-{index}.yml"
        run_id = 100 + index
        run = f"/actions/runs/{run_id}"
        pick = {"workflow_path": path, "run_id": run_id, "workflow_id": 200 + index, "attempt": 1}
        selection["runs"].append(pick)
        request["required_checks"].append({**check, "name": name, "workflow_path": path})
        receipt["checks"].append({**claim, "name": name, "url": f"https://github.com/{REPO}{run}"})
        answers[f"/contents/{path}?ref={HEAD}"] = {
            **answers[f"/contents/{WORKFLOW}?ref={HEAD}"],
            "path": path,
        }
        answers[run] = {
            **answers[RUN],
            "id": run_id,
            "workflow_id": pick["workflow_id"],
            "path": path,
        }
        job = {**answers[JOBS]["jobs"][0], "id": 300 + index, "run_id": run_id, "name": name}
        answers[f"{run}/attempts/1/jobs?per_page=100"] = {"total_count": 1, "jobs": [job]}
    bundle = prepare_task(request)
    receipt["task_sha256"] = bundle["task_sha256"]
    return (bundle, receipt, selection), answers


def test_maximum_workflows_fit_transport_budget(monkeypatch):
    inputs, answers = multiple_workflows(24)
    calls = []

    class Response:
        status = 200
        headers = Message()
        headers["Content-Type"] = "application/json"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read1(self, _size):
            return next(self.blocks)

    class Opener:
        def open(self, request, *, timeout):
            calls.append(request.full_url)
            path = request.full_url.removeprefix(f"https://api.github.com/repos/{REPO}")
            response = Response()
            response.blocks = iter([json.dumps(answers[path]).encode(), b""])
            return response

    monkeypatch.setattr(adapter, "build_opener", lambda *_args: Opener())
    get = adapter._github_reader(REPO, "z" * 32)
    monkeypatch.setattr(adapter, "_github_reader", lambda *_args: get)
    result = adapter.collect(*inputs, REPO, token="z" * 32, now=NOW)
    assert result["status"] == "compared"
    assert result["execution_authority"] is False
    assert result["provenance"] == "authenticated_github_get"
    assert len(result["workflow_runs"]) == len(result["checks"]) == 24
    assert len(calls) == 99
    with pytest.raises(Refused, match="observation_budget_exhausted"):
        get(PR)
    assert len(calls) == 99


def test_over_maximum_workflows_are_refused_before_any_get():
    inputs, _ = multiple_workflows(25)
    reader = lambda _: pytest.fail("unexpected GET")  # noqa: E731
    assert_refusal(observe(inputs, {}, reader=reader), "invalid_run_selection")
