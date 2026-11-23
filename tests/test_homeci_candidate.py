import base64
import hashlib
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from daf.contract import Refused, digest
from daf.receipt_bridge import append_observation, observation_history, observation_row
from daf.supervised_handoff import interrupted_attempt, prepare_task

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from homeci_candidate import JOB, STEPS, WORKFLOW, WORKFLOW_FILE, title, verify  # noqa: E402

DAF = "example/daf"
FORGE = "example/private-validation"
BASE = "a" * 40
CANDIDATE = "b" * 40
FORGE_SHA = "c" * 40
DOCUMENT = "docs/one.md"
WORKFLOW_BYTES = b"reviewed verifier"
RUN = 100
WORKFLOW_ID = 42
JOB_ID = 200
LISTING = (
    f"/repos/{FORGE}/actions/workflows/{WORKFLOW_ID}/runs?event=workflow_dispatch&per_page=100"
)


@pytest.fixture
def github():
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle = prepare_task(
        {
            "schema_version": 1,
            "plan_sha256": "a" * 64,
            "milestone_id": "m1",
            "attempt_id": "attempt-1",
            "repository": DAF,
            "baseline_sha": BASE,
            "instruction": "Update the operator documentation.",
            "allowed_paths": [DOCUMENT],
            "required_checks": [
                {
                    "name": "offline",
                    "validator_id": "hosted",
                    "source": "github_actions",
                    "workflow_path": ".github/workflows/ci.yml",
                    "workflow_sha256": "c" * 64,
                    "artifact_name": None,
                }
            ],
        }
    )
    approval = {
        "task_sha256": bundle["task_sha256"],
        "candidate_sha": CANDIDATE,
        "candidate_pr": 26,
        "validator_repository": FORGE,
        "workflow_id": WORKFLOW_ID,
        "workflow_revision": FORGE_SHA,
        "workflow_sha256": hashlib.sha256(WORKFLOW_BYTES).hexdigest(),
        "runner": "fixture-runner",
    }
    repo = {"full_name": FORGE, "private": True}
    pr = {
        "number": approval["candidate_pr"],
        "draft": True,
        "state": "open",
        "changed_files": 1,
        "head": {"sha": CANDIDATE, "repo": {"full_name": DAF}},
        "base": {"sha": BASE, "repo": {"full_name": DAF}, "ref": "main"},
        "updated_at": stamp,
    }
    run = {
        "id": RUN,
        "run_attempt": 1,
        "workflow_id": WORKFLOW_ID,
        "head_sha": FORGE_SHA,
        "head_branch": "main",
        "path": WORKFLOW,
        "event": "workflow_dispatch",
        "display_title": title(approval),
        "repository": repo,
        "head_repository": repo,
        "status": "completed",
        "conclusion": "success",
        "updated_at": stamp,
    }
    job = {
        "id": JOB_ID,
        "run_id": RUN,
        "run_attempt": 1,
        "head_sha": FORGE_SHA,
        "name": JOB,
        "runner_name": approval["runner"],
        "labels": ["self-hosted"],
        "status": "completed",
        "conclusion": "success",
        "steps": [
            {"name": name, "status": "completed", "conclusion": "success"} for name, _ in STEPS
        ],
    }
    responses = {
        f"/repos/{DAF}/pulls/26": pr,
        f"/repos/{DAF}/pulls/26/files?per_page=100": [{"filename": DOCUMENT, "status": "modified"}],
        f"/repos/{FORGE}": repo,
        f"/repos/{FORGE}/git/ref/heads/main": {
            "ref": "refs/heads/main",
            "object": {"sha": FORGE_SHA},
        },
        f"/repos/{FORGE}/actions/workflows/{WORKFLOW_FILE}": {
            "id": WORKFLOW_ID,
            "path": WORKFLOW,
            "state": "active",
        },
        f"/repos/{FORGE}/contents/{WORKFLOW}?ref={FORGE_SHA}": {
            "type": "file",
            "path": WORKFLOW,
            "encoding": "base64",
            "content": base64.b64encode(WORKFLOW_BYTES).decode(),
        },
        LISTING: {
            "workflow_runs": [],
            "total_count": 0,
        },
        f"/repos/{FORGE}/actions/runs/{RUN}/attempts/1": run,
        f"/repos/{FORGE}/actions/runs/{RUN}/attempts/1/jobs?per_page=100": {
            "jobs": [job],
            "total_count": 1,
        },
    }
    return bundle, approval, responses, run, job


def test_success_retained_and_restart_never_dispatches_twice(tmp_path, github):
    bundle, approval, responses, _, _ = github
    calls = []

    def post(value):
        calls.append(value)
        return {"workflow_run_id": RUN}

    first = verify(bundle, approval, FORGE, tmp_path, responses.__getitem__, post)
    restarted = verify(bundle, approval, FORGE, tmp_path, responses.__getitem__, post)
    read_only = verify(bundle, approval, FORGE, tmp_path, responses.__getitem__)
    assert first == restarted == read_only
    assert calls == [approval]
    assert first["verification"] == "passed"
    assert first["observed_checkout"] == CANDIDATE
    assert first["job_id"] == JOB_ID and first["attempt"] == 1
    assert first["independent_producer_provenance"] is False
    with observation_history(tmp_path / "journal.sqlite") as db:
        assert observation_row(db, digest(first)) is not None


def test_ambiguous_dispatch_reconciles_without_retry(tmp_path, github):
    bundle, approval, responses, run, _ = github
    calls = []

    def lost_response(_):
        calls.append("post")
        raise Refused("timeout")

    for _ in range(2):
        observation = verify(
            bundle, approval, FORGE, tmp_path, responses.__getitem__, lost_response
        )
        assert observation["reason"] == "dispatch_outcome_unknown"
        assert observation["verification"] == "incomplete"
    assert calls == ["post"]
    responses[LISTING] = {"total_count": 1, "workflow_runs": [run]}
    assert (
        verify(bundle, approval, FORGE, tmp_path, responses.__getitem__, lost_response)[
            "verification"
        ]
        == "passed"
    )
    assert calls == ["post"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("id", RUN + 1, "wrong_run_attempt"),
        ("run_attempt", 2, "wrong_run_attempt"),
        ("workflow_id", WORKFLOW_ID + 1, "wrong_workflow"),
        ("head_sha", "0" * 40, "wrong_run_revision"),
        ("display_title", "DAF docs from a different candidate", "wrong_workflow_dispatch"),
    ],
)
def test_wrong_run_identity_is_incomplete(tmp_path, github, field, value, reason):
    bundle, approval, responses, run, _ = github
    run[field] = value
    result = verify(
        bundle, approval, FORGE, tmp_path, responses.__getitem__, lambda _: {"workflow_run_id": RUN}
    )
    assert result["verification"] == "incomplete"
    assert result["reason"] == reason


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("candidate_sha", "wrong_pr_revision"),
        ("workflow_sha256", "wrong_workflow_digest"),
        ("workflow_id", "wrong_validator_workflow"),
        ("changed_file", "candidate_scope_mismatch"),
    ],
)
def test_invalid_candidate_never_reserves_or_posts(tmp_path, github, target, reason):
    bundle, approval, responses, _, _ = github
    if target == "changed_file":
        responses[f"/repos/{DAF}/pulls/26/files?per_page=100"][0]["filename"] = "docs/other.md"
    elif target == "workflow_id":
        approval[target] += 1
    else:
        approval[target] = "0" * len(approval[target])
    result = verify(
        bundle, approval, FORGE, tmp_path, responses.__getitem__, lambda _: pytest.fail("dispatch")
    )
    assert result["reason"] == reason
    assert not (tmp_path / "homeci.sqlite").exists()


@pytest.mark.parametrize(
    ("conclusion", "reason"),
    [
        ("failure", "portable_contracts_failed"),
        ("cancelled", "workflow_cancelled"),
        ("timed_out", "workflow_timed_out"),
        ("success", "portable_contracts_failed"),
    ],
)
def test_terminal_failure_and_missing_step_are_preserved(tmp_path, github, conclusion, reason):
    bundle, approval, responses, run, job = github
    run["conclusion"] = conclusion
    job["conclusion"] = conclusion
    if conclusion == "success":
        del job["steps"][3]
    else:
        job["steps"][3]["conclusion"] = "failure"
    result = verify(
        bundle, approval, FORGE, tmp_path, responses.__getitem__, lambda _: {"workflow_run_id": RUN}
    )
    assert result["state"] == "terminal" and result["verification"] == "incomplete"
    assert result["reason"] == reason and result["job_id"] == JOB_ID
    assert result["observed_checkout"] == CANDIDATE


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("queued", "queued"),
        ("in_progress", "running"),
        ("waiting", "blocked"),
    ],
)
def test_pending_without_runner_stays_visible(tmp_path, github, status, expected):
    bundle, approval, responses, run, job = github
    run.update(status=status, conclusion=None)
    job.update(status="queued", conclusion=None, runner_name=None, steps=[])
    result = verify(
        bundle, approval, FORGE, tmp_path, responses.__getitem__, lambda _: {"workflow_run_id": RUN}
    )
    assert result["state"] == expected and result["verification"] == "incomplete"
    assert "runner" not in result


def test_interrupted_attempt_stays_incomplete_after_later_observation(tmp_path, github):
    bundle, approval, responses, _, _ = github
    interruption = interrupted_attempt(bundle)
    fingerprint = append_observation(tmp_path, interruption)
    append_observation(
        tmp_path, {"interruption_sha256": fingerprint, "worker_cleanup": "confirmed"}
    )
    result = verify(
        bundle, approval, FORGE, tmp_path, responses.__getitem__, lambda _: pytest.fail("dispatch")
    )
    assert result["reason"] == "attempt_incomplete"
    with observation_history(tmp_path / "journal.sqlite") as db:
        assert observation_row(db, fingerprint) is not None


def test_duplicate_external_runs_block_dispatch(tmp_path, github):
    bundle, approval, responses, run, _ = github
    duplicate = deepcopy(run)
    duplicate["id"] += 1
    responses[LISTING] = {"total_count": 2, "workflow_runs": [run, duplicate]}
    result = verify(
        bundle, approval, FORGE, tmp_path, responses.__getitem__, lambda _: pytest.fail("dispatch")
    )
    assert result["reason"] == "multiple_runs_for_attempt"
