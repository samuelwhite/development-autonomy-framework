"""Portable safety and display regressions, using only new synthetic state."""

import json
import socket
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from daf.contract import Plan, Refused, digest, read_json
from daf.engine import Engine
from daf.fixtures import FixtureAdapter
from daf.operations import resume
from daf.preview import RESOURCES, dashboard, demonstrate, example_plan, progress
from daf.stop_control import StopControl
from daf.store import Store


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline runtime attempted external I/O")

    for target, name in (
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
        (socket.socket, "connect"),
        (subprocess, "Popen"),
    ):
        monkeypatch.setattr(target, name, forbidden)


def test_demo_retains_failures_and_exact_usage_across_restart(tmp_path):
    result = demonstrate(tmp_path / "new")
    progression = result["progression"]
    assert progression["run"]["status"] == "completed"
    assert [a["status"] for a in progression["attempts"]] == [
        "completed",
        "failed",
        "completed",
        "completed",
    ]
    assert progression["attempts"][1]["checks"]["tests"] == "failure"
    assert progression["known_actual_tokens"] == 400
    assert progression["provider_jobs"] == 4
    assert progression["reserved_tokens"] == 8000
    assert result["scope_blocker"]["run"]["status"] == "needs_decision"
    assert result["stopped"]["jobs"] == []
    assert result["bounded"]["next_segment"] == "budget_blocked"
    assert result["bounded"]["simulated_sends"] == 2
    assert result["execution_authority"] is False
    assert result["approval_receipts_issued"] == result["provider_requests"] == 0


def test_new_output_only_and_no_modification_on_refusal(tmp_path):
    directory = tmp_path / "existing"
    directory.mkdir()
    evidence = directory / "evidence.txt"
    evidence.write_text("retained")
    with pytest.raises(Refused, match="new_output_directory_required"):
        demonstrate(directory)
    assert list(directory.iterdir()) == [evidence]
    assert evidence.read_text() == "retained"


def test_output_parent_link_refused_without_writing(tmp_path, monkeypatch):
    parent = tmp_path / "linked"
    parent.mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == parent or original(path))
    with pytest.raises(Refused, match="output_link_refused"):
        demonstrate(parent / "new")
    assert not list(parent.iterdir())


@pytest.mark.parametrize("version", [True, 0, 2, 3, 4, 5, 100])
def test_nonfixture_schemas_refused(version):
    data = example_plan().data
    data["schema_version"] = version
    with pytest.raises(Refused, match="unsupported_plan_schema"):
        Plan.validate_data(data)


@pytest.mark.parametrize("field", ["merge", "deploy"])
def test_live_actions_cannot_be_requested(field):
    data = example_plan().data
    data["actions"][field] = True
    with pytest.raises(Refused, match="live_actions_unavailable"):
        Plan.validate_data(data)


def test_recorded_receipt_is_not_accepted():
    plan = example_plan()
    marker = json.loads(plan.approval)
    marker["mode"] = "recorded"
    with pytest.raises(Refused, match="invalid_approval"):
        Plan.load(plan.data, marker)


@pytest.mark.parametrize("change", ["dependency", "criteria", "budget", "path", "unknown"])
def test_plan_boundaries(change):
    data = example_plan().data
    if change == "dependency":
        data["milestones"][0]["depends_on"] = ["F3"]
    elif change == "criteria":
        data["milestones"][0]["acceptance"] = {}
    elif change == "budget":
        data["budgets"]["tokens_per_job"] = data["budgets"]["max_tokens"] + 1
    elif change == "path":
        data["boundaries"]["code_prefixes"] = ["../"]
    else:
        data["unreviewed"] = True
    with pytest.raises(Refused):
        Plan.validate_data(data)


def test_changed_marker_or_constructed_plan_refused(tmp_path):
    plan = example_plan()
    receipt = json.loads(plan.approval)
    receipt["plan_sha256"] = "a" * 64
    with pytest.raises(Refused, match="approval_digest_mismatch"):
        Plan.load(plan.data, receipt)
    with open_store(tmp_path) as store:
        adapter = FixtureAdapter(tmp_path / "fixture.sqlite", {"F1": ["success"]})
        try:
            with pytest.raises(Refused, match="plan_changed"):
                Engine(store, replace(plan, fingerprint="b" * 64), adapter)
        finally:
            adapter.close()


def open_store(path):
    from contextlib import closing

    return closing(Store(path))


def test_adapter_replacement_never_reaches_transport(tmp_path):
    class Untrusted:
        fixture = True
        idempotent = True

        def ensure(self, request):
            pytest.fail("untrusted adapter invoked")

    with open_store(tmp_path) as store:
        with pytest.raises(Refused, match="fixture_adapter_required"):
            Engine(store, example_plan(), Untrusted())
        adapter = FixtureAdapter(tmp_path / "fixture.sqlite", {"F1": ["success"]})
        try:
            engine = Engine(store, example_plan(), adapter)
            engine.adapter = Untrusted()
            with pytest.raises(Refused, match="fixture_adapter_required"):
                engine.advance()
        finally:
            adapter.close()


@pytest.mark.parametrize(
    "outcome",
    [
        "scope_deviation",
        "protected_change",
        "missing_evidence",
        "workflow_change",
        "skipped_check",
        "usage_overrun",
        "acceptance_failure",
    ],
)
def test_bad_evidence_never_accepts_milestone(tmp_path, outcome):
    result = progress(tmp_path, {"F1": [outcome]})
    assert result["run"]["status"] == "needs_decision"
    assert result["milestones"][0]["status"] != "completed"


def test_stop_commits_independently_of_busy_journal_and_refuses_admission(tmp_path):
    with open_store(tmp_path) as store:
        store.initialize(example_plan(), 100)
        store.db.execute("BEGIN IMMEDIATE")
        try:
            with ThreadPoolExecutor() as pool:
                epoch = pool.submit(StopControl(tmp_path).request).result(timeout=5)
            assert epoch > 0
            with pytest.raises(Refused):
                with store.stop.fence():
                    pytest.fail("stop failed to fence admission")
        finally:
            store.db.rollback()


def test_crash_unknown_is_retained_and_blocks_resume(tmp_path):
    class Crash(BaseException):
        pass

    control = StopControl(tmp_path)
    with pytest.raises(Crash), control.operation("fixture"):
        raise Crash()
    reopened = StopControl(tmp_path)
    reopened.recover()
    assert reopened.snapshot()["outstanding"]
    with pytest.raises(Refused):
        with reopened.resuming(reopened.snapshot()["epoch"]):
            pytest.fail("unknown outcome resumed")


def test_stale_stop_epoch_cannot_resume(tmp_path):
    with open_store(tmp_path) as store:
        store.initialize(example_plan(), 100)
        first = store.stop.request()
        store.stop.request()
        with pytest.raises(Refused):
            resume(store, example_plan(), observed_epoch=first)
        assert store.stop.requested()


def test_static_dashboard_escapes_embedded_data_and_has_no_controls(tmp_path):
    result = demonstrate(tmp_path / "new")
    result["planning"] = "</script><img src=x onerror=alert(1)>"
    html = dashboard(result)
    assert "<img src=x" not in html
    assert "\\u003c/script" in html
    assert "default-src 'none'" in html
    assert "sha256-" in html
    assert "<form" not in html and "<button" not in html
    script = (RESOURCES / "assets/app.js").read_text()
    assert "textContent" in script
    for unsafe in ("innerHTML", "fetch(", "XMLHttpRequest", "WebSocket", "eval("):
        assert unsafe not in script


def test_duplicate_json_key_and_missing_receipt_refused(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"scope":1,"scope":2}')
    with pytest.raises(Refused, match="duplicate_json_key"):
        read_json(path)
    with pytest.raises(Refused):
        Plan.load(example_plan().data, {})


def test_fixture_scenario_is_immutable_on_restart(tmp_path):
    adapter = FixtureAdapter(tmp_path / "fixture.sqlite", {"F1": ["success"]})
    adapter.close()
    with pytest.raises(Refused, match="fixture_scenario_changed_on_resume"):
        FixtureAdapter(tmp_path / "fixture.sqlite", {"F1": ["test_failure"]})


def test_stop_audit_cannot_be_rewritten(tmp_path):
    control = StopControl(tmp_path)
    control.request()
    with control.connection() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM audit")


def test_immutable_plan_data():
    plan = example_plan()
    changed = plan.data
    changed["scope"] = ["changed"]
    assert digest(plan.data) == plan.fingerprint
