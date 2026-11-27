import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from daf.contract import Refused, canonical
from daf.receipt_bridge import read_document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import rehearse_operator as operator  # noqa: E402

ONCE = {"branch": 1, "draft": 1, "dispatch": 1}


def prepare(workspace, task):
    report = operator.exercise(workspace, task, "preview", None)
    assert report["diff"] and report["state"] == "proposed"
    assert not (workspace / "fixture" / "simulated-github.json").exists()
    return report


def test_two_approvals_and_histories_remain_independent(tmp_path):
    docs, python = tmp_path / "docs", tmp_path / "python"
    a, b = prepare(docs, "docs"), prepare(python, "python")
    for key in ("task_sha256", "candidate_sha", "approval_sha256", "plan_sha256"):
        assert a[key] != b[key]
    for wrong in (None, a["approval_sha256"]):
        with pytest.raises(Refused, match="explicit_fixture_approval_required"):
            operator.exercise(python, "python", "run", wrong)
    assert not (python / "fixture" / "simulated-github.json").exists()
    results = []
    for workspace, proposal in ((docs, a), (python, b)):
        name, approval = proposal["fixture"], proposal["approval_sha256"]
        first = operator.exercise(workspace, name, "run", approval)
        again = operator.exercise(workspace, name, "run", approval)
        assert again == first and first["external_writes"] == ONCE
        event = again["observation"]
        assert event["state"] == "review" and event["candidate_sha"] == proposal["candidate_sha"]
        results.append(event)
        assert event in operator.exercise(workspace, name, "history", None)["observations"]
    for key in ("draft_pr", "run_id", "job_id"):
        assert results[0][key] != results[1][key]


@pytest.mark.parametrize(
    "name,loss", [("docs", "branch"), ("docs", "draft"), ("python", "dispatch")]
)
def test_recovery_with_original_approval_never_replays_reserved_writes(tmp_path, name, loss):
    approval = prepare(tmp_path, name)["approval_sha256"]
    blocked = operator.exercise(tmp_path, name, "run", approval, "uncertain-" + loss)
    assert blocked["observation"]["reason"].endswith("_outcome_unknown")
    assert blocked["external_writes"][loss] == 1
    first = operator.exercise(tmp_path, name, "run", approval)
    assert first["observation"]["state"] == "review" and first["external_writes"] == ONCE
    assert operator.exercise(tmp_path, name, "observe", None) == first
    assert (
        blocked["observation"] in operator.exercise(tmp_path, name, "history", None)["observations"]
    )


@pytest.mark.parametrize(
    "scenario,state,reason",
    [
        ("queued", "queued", None),
        ("incomplete-metadata", "blocked", "wrong_workflow_dispatch"),
        ("wrong-run", "blocked", "wrong_run_attempt"),
        ("failed", "finished", "focused_test_failed"),
    ],
)
def test_read_only_resume_preserves_original_run_and_history(
    tmp_path, monkeypatch, scenario, state, reason
):
    approval = prepare(tmp_path, "python")["approval_sha256"]
    before = operator.exercise(tmp_path, "python", "run", approval, scenario=scenario)[
        "observation"
    ]
    assert before["state"] == state and before.get("reason") == reason
    assert before["run_id"] == 1402
    if scenario == "incomplete-metadata":
        assert before["dispatch_identity_mismatches"] == ["display_title"]

    def no_write(*args, **kwargs):
        pytest.fail("observation was given a write")

    for method in ("publish", "create_draft", "dispatch"):
        monkeypatch.setattr(operator.code.CodeTransport, method, no_write)
    result = operator.exercise(tmp_path, "python", "observe", None)
    after = result["observation"]
    assert after["state"] == ("finished" if scenario == "failed" else "review")
    assert after["run_id"] == before["run_id"] and result["external_writes"] == ONCE
    assert before in operator.exercise(tmp_path, "python", "history", None)["observations"]


def test_simultaneous_operator_yields_to_held_workspace_lock(tmp_path, monkeypatch):
    approved = prepare(tmp_path, "docs")
    entered, release = Event(), Event()
    rehearse = operator.docs.rehearse

    def pause(*args, **kwargs):
        entered.set()
        assert release.wait(30)
        return rehearse(*args, **kwargs)

    monkeypatch.setattr(operator.docs, "rehearse", pause)
    args = (tmp_path, "docs", "run", approved["approval_sha256"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(operator.exercise, *args)
        try:
            assert entered.wait(30)
            result = operator.exercise(*args)
            assert result["reason"] == "invocation_in_progress"
            assert not (tmp_path / "fixture" / "simulated-github.json").exists()
        finally:
            release.set()
        assert active.result(timeout=30)["external_writes"] == ONCE


def test_changed_policy_cannot_use_original_approval(tmp_path):
    approved = prepare(tmp_path, "docs")
    inputs = tmp_path / "fixture" / "request.json"
    request = read_document(inputs)
    request[3]["verification"]["workflow_revision"] = "d" * 40
    inputs.write_text(canonical(request), encoding="utf-8")
    with pytest.raises(Refused, match="explicit_fixture_approval_required"):
        operator.exercise(tmp_path, "docs", "run", approved["approval_sha256"])
    assert not (tmp_path / "fixture" / "simulated-github.json").exists()


def test_historical_success_stays_bound_after_main_advances(tmp_path):
    approval = prepare(tmp_path, "docs")["approval_sha256"]
    first = operator.exercise(tmp_path, "docs", "run", approval)["observation"]
    root = tmp_path / "fixture"
    operator.docs.git(
        root / "source",
        "push",
        str(root / "remote.git"),
        first["candidate_sha"] + ":refs/heads/main",
    )
    history = operator.exercise(tmp_path, "docs", "history", None)["observations"]
    assert history[-1] == first and first["state"] == "review"
    assert operator.exercise(tmp_path, "docs", "observe", None)["observation"] == first
