import base64
import hashlib
import os
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from daf.contract import Refused, digest
from daf.receipt_bridge import append_observation, observation_history, observation_row
from daf.supervised_handoff import interrupted_attempt, prepare_task, preview_document_edit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from homeci_candidate import JOB, STEPS, WORKFLOW, WORKFLOW_FILE, title, verify  # noqa: E402
from materialize_document_candidate import materialize_candidate  # noqa: E402

DAF = "example/daf"
FORGE = "example/private-validation"
BASE = "a" * 40
CANDIDATE = "b" * 40
FORGE_SHA = "c" * 40
DOCUMENT = "docs/one.md"
RUN = 100
WORKFLOW_ID = 42
JOB_ID = 200
WORKFLOW_CONTENTS = f"/repos/{FORGE}/contents/{WORKFLOW}?ref={FORGE_SHA}"
DAF_MAIN = f"/repos/{DAF}/git/ref/heads/main"
LISTING = (
    f"/repos/{FORGE}/actions/workflows/{WORKFLOW_ID}/runs?event=workflow_dispatch&per_page=100"
)


@pytest.fixture
def workflow_bytes():
    blob = os.environ.get("DAF_TEST_FORGE_WORKFLOW_BLOB")
    if blob:
        content = Path(blob).read_bytes()
        assert hashlib.sha256(content).hexdigest() == os.environ["DAF_TEST_FORGE_WORKFLOW_SHA256"]
        return content
    # The public suite supplies canonical LF bytes without copying a private workflow.
    return f"name: {JOB}\non: workflow_dispatch\n".encode()


@pytest.fixture
def github(workflow_bytes):
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    workflow_digest = hashlib.sha256(workflow_bytes).hexdigest()
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
                    "name": JOB,
                    "validator_id": FORGE,
                    "source": "github_actions",
                    "workflow_path": WORKFLOW,
                    "workflow_sha256": workflow_digest,
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
        "workflow_path": WORKFLOW,
        "workflow_sha256": workflow_digest,
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
        DAF_MAIN: {"ref": "refs/heads/main", "object": {"sha": BASE}},
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
        WORKFLOW_CONTENTS: {
            "type": "file",
            "path": WORKFLOW,
            "encoding": "base64",
            "content": base64.b64encode(workflow_bytes).decode(),
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


def test_success_retained_and_restart_never_dispatches_twice(tmp_path, github, workflow_bytes):
    bundle, approval, responses, _, _ = github
    check = bundle["request"]["required_checks"][0]
    assert check["workflow_path"] == approval["workflow_path"] == WORKFLOW
    assert check["workflow_sha256"] == approval["workflow_sha256"]
    assert check["workflow_sha256"] == hashlib.sha256(workflow_bytes).hexdigest()
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


def test_real_local_candidate_reuses_one_homeci_dispatch(tmp_path, github):
    bundle, approval, responses, run, _ = github
    repository = tmp_path / "repo"
    repository.mkdir()

    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(repository), *arguments])

    git("init", "--quiet", "-b", "main")
    document = repository / DOCUMENT
    document.parent.mkdir()
    baseline = b"# Guide\n\nOriginal content.\n"
    document.write_bytes(baseline)
    git("add", DOCUMENT)
    git("-c", "user.name=Pilot", "-c", "user.email=pilot@example.org", "commit", "-qm", "Baseline")
    base_sha = git("rev-parse", "HEAD").decode().strip()
    bundle = prepare_task({**bundle["request"], "baseline_sha": base_sha})
    edit = {
        "task_sha256": bundle["task_sha256"],
        "path": DOCUMENT,
        "baseline_file_sha256": hashlib.sha256(baseline).hexdigest(),
        "original": "Original content.",
        "replacement": "Proposed content.",
    }
    preview = preview_document_edit(bundle, edit, baseline)
    record = {
        "preview_sha256": digest(preview),
        "author_name": "Pilot",
        "author_email": "pilot@example.org",
        "created_at": "2026-11-23T13:00:00Z",
    }
    document.write_bytes(b"Unrelated operator working change\n")
    with pytest.raises(Refused, match="^candidate_preview_changed$"):
        materialize_candidate(repository, bundle, edit, {**record, "preview_sha256": "0" * 64})
    before = git("status", "--porcelain=v1")
    result = materialize_candidate(repository, bundle, edit, record)
    assert materialize_candidate(repository, bundle, edit, record) == result
    candidate = result["candidate_sha"]
    assert result["execution_authority"] is False
    assert git("rev-list", "--parents", "-n", "1", candidate).decode().split() == [
        candidate,
        base_sha,
    ]
    assert git(
        "diff-tree", "--no-commit-id", "--name-status", "-r", candidate
    ).decode().splitlines() == [f"M\t{DOCUMENT}"]
    assert git("show", f"{candidate}:{DOCUMENT}") == preview["candidate_text"].encode()
    assert git("rev-parse", "HEAD").decode().strip() == base_sha
    assert git("status", "--porcelain=v1") == before
    assert document.read_bytes() == b"Unrelated operator working change\n"

    approval.update(task_sha256=bundle["task_sha256"], candidate_sha=candidate)
    pr = responses[f"/repos/{DAF}/pulls/26"]
    pr["head"]["sha"] = candidate
    pr["base"]["sha"] = base_sha
    responses[DAF_MAIN]["object"]["sha"] = base_sha
    run["display_title"] = title(approval)
    calls = []

    def post(value):
        calls.append(value)
        duplicate = verify(bundle, approval, FORGE, tmp_path, responses.__getitem__, post)
        assert duplicate["reason"] == "dispatch_outcome_unknown"
        return {"workflow_run_id": RUN}

    first = verify(bundle, approval, FORGE, tmp_path, responses.__getitem__, post)
    restarted = verify(bundle, approval, FORGE, tmp_path, responses.__getitem__, post)
    assert first == restarted
    assert calls == [approval]
    assert first["verification"] == "passed"
    assert first["observed_checkout"] == candidate


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
    "change",
    [
        {"workflow_path": ".github/workflows/ci.yml"},
        {"workflow_sha256": "0" * 64},
        {"validator_id": "example/other-validator"},
        {"name": "A different required job"},
        {"source": "homeci", "artifact_name": "result.zip"},
    ],
)
def test_valid_task_with_different_requirement_refused_before_reservation(tmp_path, github, change):
    bundle, approval, _, _, _ = github
    request = deepcopy(bundle["request"])
    request["required_checks"][0].update(change)
    new_bundle = prepare_task(request)
    # The approval names the new valid task and valid Forge workflow. Only the binding differs.
    approval["task_sha256"] = new_bundle["task_sha256"]
    result = verify(
        new_bundle,
        approval,
        FORGE,
        tmp_path,
        lambda _: pytest.fail("GitHub lookup"),
        lambda _: pytest.fail("dispatch"),
    )
    assert result["reason"] == "task_workflow_requirement_mismatch"
    assert result["verification"] == "incomplete"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("workflow_path", ".github/workflows/other.yml", "wrong_approved_workflow_path"),
        ("workflow_sha256", "0" * 64, "task_workflow_requirement_mismatch"),
    ],
)
def test_valid_approval_with_different_workflow_refused_before_reservation(
    tmp_path,
    github,
    field,
    value,
    reason,
):
    bundle, approval, _, _, _ = github
    approval[field] = value
    result = verify(
        bundle,
        approval,
        FORGE,
        tmp_path,
        lambda _: pytest.fail("GitHub lookup"),
        lambda _: pytest.fail("dispatch"),
    )
    assert result["reason"] == reason
    assert result["verification"] == "incomplete"
    assert not list(tmp_path.iterdir())


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
        ("workflow_bytes", "wrong_workflow_digest"),
        ("workflow_id", "wrong_validator_workflow"),
        ("changed_file", "candidate_scope_mismatch"),
        ("main_advanced", "candidate_main_revision_changed"),
    ],
)
def test_invalid_candidate_never_reserves_or_posts(tmp_path, github, target, reason):
    bundle, approval, responses, _, _ = github
    if target == "changed_file":
        responses[f"/repos/{DAF}/pulls/26/files?per_page=100"][0]["filename"] = "docs/other.md"
    elif target == "main_advanced":
        responses[DAF_MAIN]["object"]["sha"] = "0" * 40
    elif target == "workflow_bytes":
        responses[WORKFLOW_CONTENTS]["content"] = base64.b64encode(
            b"changed workflow bytes"
        ).decode()
    elif target == "workflow_id":
        approval[target] += 1
    else:
        approval[target] = "0" * len(approval[target])
    result = verify(
        bundle, approval, FORGE, tmp_path, responses.__getitem__, lambda _: pytest.fail("dispatch")
    )
    assert result["reason"] == reason
    assert not (tmp_path / "homeci.sqlite").exists()


def test_daf_main_advance_during_verification_refuses_green_job(tmp_path, github):
    bundle, approval, responses, _, _ = github

    def post(_):
        responses[DAF_MAIN]["object"]["sha"] = "0" * 40
        return {"workflow_run_id": RUN}

    result = verify(bundle, approval, FORGE, tmp_path, responses.__getitem__, post)
    assert result["reason"] == "candidate_main_revision_changed"
    assert result["job_id"] == JOB_ID and result["verification"] == "incomplete"


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
