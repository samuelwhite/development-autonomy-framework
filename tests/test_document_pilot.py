import sys
from copy import deepcopy
from pathlib import Path

import pytest

from daf.contract import Refused, digest
from daf.receipt_bridge import append_observation, observation_history, observation_row
from daf.supervised_handoff import interrupted_attempt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from document_pilot import run_pilot  # noqa: E402
from rehearse_document_pilot import DAF, FORGE, RehearsalTransport, rehearse, setup  # noqa: E402

ONCE = {"branch": 1, "draft": 1, "dispatch": 1}


def invoke(repo, inputs, journal, transport):
    return run_pilot(
        repo, *inputs, journal, transport, allowed_repository=DAF, allowed_validator=FORGE
    )


def test_concurrent_call_and_restart_share_one_candidate(tmp_path):
    repo, remote, journal, inputs = setup(tmp_path)
    state = tmp_path / "simulated-github.json"
    transport = RehearsalTransport(repo, remote, state)
    simultaneous = []
    transport.before_write = lambda _: simultaneous.append(
        invoke(
            repo,
            inputs,
            journal,
            RehearsalTransport(repo, remote, state),
        )
    )
    first = invoke(repo, inputs, journal, transport)
    assert len(simultaneous) == 3
    assert all(item["reason"] == "invocation_in_progress" for item in simultaneous)
    assert first["state"] == "review"
    assert first["file"] == "docs/guide.md"
    assert first["candidate_sha"] == inputs[-1]["candidate_sha"]
    assert first["conclusion"] == "success"
    recovered = rehearse(tmp_path)
    assert recovered == {
        "observation": {**first, "kind": "document-rehearsal"},
        "external_writes": ONCE,
    }
    assert rehearse(tmp_path) == recovered
    with observation_history(journal / "journal.sqlite") as history:
        assert observation_row(history, digest(first)) is not None


@pytest.mark.parametrize("phase", ["branch", "draft", "dispatch"])
def test_lost_responses_recover_once(tmp_path, phase):
    result = rehearse(tmp_path, loss=phase)
    if phase == "dispatch":
        assert result["observation"]["reason"] == "dispatch_outcome_unknown"
        result = rehearse(tmp_path)
    assert result["observation"]["state"] == "review"
    assert result["external_writes"] == ONCE


@pytest.mark.parametrize(
    ("phase", "reason"),
    [
        ("branch", "branch_publish_outcome_unknown"),
        ("draft", "draft_create_outcome_unknown"),
        ("dispatch", "dispatch_outcome_unknown"),
    ],
)
def test_unverifiable_response_pauses_and_recovers_after_restart(tmp_path, phase, reason):
    paused = rehearse(tmp_path, loss=f"uncertain-{phase}")
    assert paused["observation"]["reason"] == reason
    assert paused["external_writes"][phase] == 1
    recovered = rehearse(tmp_path)
    assert recovered["observation"]["state"] == "review"
    assert recovered["external_writes"] == ONCE


@pytest.mark.parametrize(
    ("outcome", "state"),
    [
        ("queued", "queued"),
        ("failure", "finished"),
        ("cancelled", "finished"),
    ],
)
def test_runner_outcome_is_retained(tmp_path, outcome, state):
    result = rehearse(tmp_path, outcome=outcome)
    assert result["observation"]["state"] == state
    assert result["observation"]["run_id"] == 1401
    assert result["observation"].get("conclusion") == (None if outcome == "queued" else outcome)
    assert rehearse(tmp_path)["external_writes"] == ONCE


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("edit", "candidate_preview_changed"),
        ("path", "one_document_edit_required"),
        ("candidate", "approved_candidate_changed"),
        ("workflow", "task_workflow_requirement_mismatch"),
    ],
)
def test_changed_input_refused_before_publication(tmp_path, change, reason):
    repo, remote, journal, inputs = setup(tmp_path)
    modified = deepcopy(inputs)
    if change == "edit":
        modified[1]["replacement"] = "Different approved content."
    elif change == "path":
        modified[1]["path"] = "docs/other.md"
    elif change == "candidate":
        modified[3]["candidate_sha"] = "0" * 40
    else:
        modified[3]["verification"]["workflow_sha256"] = "0" * 64
    state = tmp_path / "simulated-github.json"
    transport = RehearsalTransport(repo, remote, state)
    with pytest.raises(Refused, match=reason):
        invoke(repo, modified, journal, transport)
    assert not state.exists()


def test_baseline_drift_and_conflicting_branch_refuse_publication(tmp_path):
    repo, remote, journal, inputs = setup(tmp_path)
    state = tmp_path / "simulated-github.json"
    transport = RehearsalTransport(repo, remote, state)
    get = transport.get
    transport.get = lambda path: (
        {"ref": "refs/heads/main", "object": {"sha": "0" * 40}}
        if path == f"/repos/{DAF}/git/ref/heads/main"
        else get(path)
    )
    assert invoke(repo, inputs, journal, transport)["reason"] == "candidate_main_revision_changed"
    transport.get = get
    branch = transport.branch
    transport.branch = lambda repo, name: branch(repo, name) if name == "main" else "0" * 40
    assert invoke(repo, inputs, journal, transport)["reason"] == "candidate_branch_conflict"
    assert not state.exists()


def test_interruption_between_publication_and_draft_prevents_next_write(tmp_path):
    repo, remote, journal, inputs = setup(tmp_path)
    state = tmp_path / "simulated-github.json"
    transport = RehearsalTransport(repo, remote, state)
    transport.before_write = lambda action: (
        append_observation(journal, interrupted_attempt(inputs[0])) if action == "branch" else None
    )
    result = invoke(repo, inputs, journal, transport)
    assert result["reason"] == "attempt_incomplete"
    assert transport.data["writes"] == {"branch": 1, "draft": 0, "dispatch": 0}


def test_remote_scope_change_stops_before_dispatch(tmp_path):
    repo, remote, journal, inputs = setup(tmp_path)
    transport = RehearsalTransport(repo, remote, tmp_path / "simulated-github.json")
    get = transport.get
    transport.get = lambda path: (
        [{"filename": "docs/other.md", "status": "modified"}]
        if "/pulls/" in path and "/files?" in path
        else get(path)
    )
    assert invoke(repo, inputs, journal, transport)["reason"] == "candidate_scope_mismatch"
    assert transport.data["writes"] == {"branch": 1, "draft": 1, "dispatch": 0}


def test_interrupted_lost_dispatch_is_reconciled_without_acceptance(tmp_path):
    repo, remote, journal, inputs = setup(tmp_path)
    state = tmp_path / "simulated-github.json"
    transport = RehearsalTransport(repo, remote, state, loss="uncertain-dispatch")
    transport.before_write = lambda action: (
        append_observation(journal, interrupted_attempt(inputs[0]))
        if action == "dispatch"
        else None
    )
    first = invoke(repo, inputs, journal, transport)
    assert first["reason"] == "attempt_incomplete" and "run_id" not in first
    resumed = invoke(repo, inputs, journal, RehearsalTransport(repo, remote, state))
    assert resumed["state"] == "blocked" and resumed["reason"] == "attempt_incomplete"
    assert resumed["run_id"] == 1401 and resumed["conclusion"] == "success"
    assert transport.data["writes"] == ONCE
