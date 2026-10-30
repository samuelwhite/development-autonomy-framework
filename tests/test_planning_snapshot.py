"""Complete-source persistence and the desktop protocol, without network requests."""

import base64
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest
from test_github_planning import COMMIT, PATH, REPO, fake_source, fixture

from daf.contract import Refused, canonical
from daf.planning_snapshot import (
    history,
    make_snapshot,
    project_snapshot,
    read_snapshot,
    save_snapshot,
    validate_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "desktop_service", ROOT / "desktop/controller/service.py"
)
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)
SOURCE = {"repository": REPO, "commit_sha": COMMIT, "path": PATH}


def snapshot(document=None):
    return make_snapshot(SOURCE, json.dumps(document or fixture()).encode())


def request(operation="planning.importPublicPlan", **data):
    if operation == "planning.importPublicPlan" and not data:
        data = {"source": SOURCE}
    return {"protocol": 1, "requestId": "a" * 32, "operation": operation, **data}


def test_complete_source_roundtrip_and_idempotency(tmp_path):
    original = snapshot()
    assert save_snapshot(tmp_path, original) == "imported"
    assert save_snapshot(tmp_path, original) == "already_present"
    assert read_snapshot(tmp_path, original["snapshot_id"]) == original
    assert json.loads(base64.b64decode(original["content_base64"])) == fixture()
    view = project_snapshot(original)
    assert view["milestones"][1]["dependencies"] == ["F1"]
    assert view["milestones"][1]["instruction"] == fixture()["tasks"][1]["instruction"]
    assert view["executionAuthority"] is view["spendingAuthority"] is False
    assert view["approval"] is None
    assert history(tmp_path)["imports"][0]["id"] == view["id"]
    service.validate(view, service.SCHEMA["$defs"]["snapshot"])


def test_concurrent_identical_snapshot_is_atomic(tmp_path):
    original = snapshot()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: save_snapshot(tmp_path, original), range(4)))
    assert sorted(results) == ["already_present"] * 3 + ["imported"]
    assert len(list(tmp_path.iterdir())) == 1


def test_conflicting_source_keeps_original(tmp_path):
    original = snapshot()
    save_snapshot(tmp_path, original)
    document = fixture()
    document["tasks"][1]["instruction"] = "Different text at the same pinned address"
    with pytest.raises(Refused, match="snapshot_conflict"):
        save_snapshot(tmp_path, snapshot(document))
    assert read_snapshot(tmp_path, original["snapshot_id"]) == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("approval", {"approved": True}),
        ("execution_authority", True),
        ("spending_authority", True),
        ("execution_authority", 0),
        ("verification", "trusted"),
        ("status", "approved"),
        ("schema_version", True),
        ("trusted", True),
        ("proposals", []),
        ("snapshot_id", "a" * 64),
        ("content_base64", "*"),
    ],
)
def test_stored_trust_and_binding_injections_refuse(field, value):
    record = snapshot()
    record[field] = value
    with pytest.raises((Refused, ValueError)):
        validate_snapshot(record)


@pytest.mark.parametrize(
    "mutation",
    ["missing_task", "protected_sibling", "changed_bytes", "wrong_blob", "changed_bundle"],
)
def test_full_snapshot_revalidated_not_just_selected_projection(mutation):
    record = snapshot()
    document = fixture()
    if mutation == "missing_task":
        document["tasks"].pop()
    elif mutation == "protected_sibling":
        document["tasks"][1]["allowed_paths"] = [".GitHub/workflows/ci.yml"]
    elif mutation == "changed_bytes":
        document["tasks"][1]["instruction"] = "Tampered text"
    elif mutation == "wrong_blob":
        record["source"]["git_blob_sha"] = "d" * 40
    else:
        record["proposals"][1]["bundle"]["execution_authority"] = True
    record["content_base64"] = base64.b64encode(json.dumps(document).encode()).decode()
    with pytest.raises(Refused):
        validate_snapshot(record)


def test_corrupt_history_isolated_and_incomplete_file_never_complete(tmp_path):
    record = snapshot()
    save_snapshot(tmp_path, record)
    (tmp_path / ("c" * 64 + ".json")).write_text('{"approval":true}')
    (tmp_path / ".incomplete-abcd").write_text(canonical(record))
    result = history(tmp_path)
    assert len(result["imports"]) == 1 and result["damaged"] == ["c" * 64]


def test_publish_failure_leaves_no_snapshot(tmp_path, monkeypatch):
    def fail(*_args):
        raise OSError("interrupted")

    monkeypatch.setattr("daf.planning_snapshot.os.link", fail)
    with pytest.raises(OSError):
        save_snapshot(tmp_path, snapshot())
    assert list(tmp_path.iterdir()) == []


def test_links_and_network_storage_refused(tmp_path):
    with pytest.raises(Refused, match="local_storage"):
        history(Path("//server/share/daf"))
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(Refused, match="linked_storage"):
        save_snapshot(link, snapshot())


def test_storage_cap_refuses_without_deleting(tmp_path):
    for i in range(100):
        (tmp_path / f"{i:064x}.json").write_text("corrupted")
    with pytest.raises(Refused, match="storage_limit"):
        save_snapshot(tmp_path, snapshot())
    assert len(list(tmp_path.iterdir())) == 100


def test_sidecar_import_list_get_only_import_calls_reader(tmp_path):
    reader, calls = fake_source()
    result = service.perform(request(), tmp_path, reader=reader)
    assert result["outcome"] == "imported" and len(calls) == 7
    calls.clear()
    listed = service.perform(request("planning.listImports"), tmp_path, reader=reader)
    loaded = service.perform(
        request("planning.getImport", id=listed["imports"][0]["id"]), tmp_path, reader=reader
    )
    assert loaded["snapshot"] == result["snapshot"] and calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        "protocol",
        "operation",
        "command",
        "directory",
        "receipt",
        "source_extra",
        "number_id",
        "missing",
    ],
)
def test_protocol_unknown_authority_or_operations_refused(mutation, tmp_path):
    value = deepcopy(request())
    if mutation == "protocol":
        value["protocol"] = True
    elif mutation == "operation":
        value["operation"] = "execute"
    elif mutation == "source_extra":
        value["source"]["headers"] = {"Authorization": "secret"}
    elif mutation == "number_id":
        value["requestId"] = 1
    elif mutation == "missing":
        del value["source"]
    else:
        value[mutation] = "arbitrary"
    with pytest.raises(Refused):
        service.perform(value, tmp_path, reader=lambda _: pytest.fail("network before validation"))


@pytest.mark.parametrize(
    "status,expected",
    [
        (301, "github_unavailable"),
        (403, "github_rate_limited"),
        (404, "github_not_found"),
        (429, "github_rate_limited"),
        (500, "github_unavailable"),
    ],
)
def test_reader_statuses_do_not_retry_or_follow(monkeypatch, status, expected):
    class Connection:
        def __init__(self, host, timeout, context):
            assert host == "api.github.com" and 0 < timeout <= 8
            assert context.check_hostname and context.verify_mode == service.ssl.CERT_REQUIRED

        def request(self, method, path, headers):
            assert method == "GET" and set(headers) == {
                "Accept",
                "User-Agent",
                "X-GitHub-Api-Version",
            }

        def getresponse(self):
            return type("Response", (), {"status": status})()

        def close(self):
            pass

    monkeypatch.setattr(service.http.client, "HTTPSConnection", Connection)
    reader = service.PublicReader()
    with pytest.raises(Refused, match=expected):
        reader(f"/repos/{REPO}/git/commits/{COMMIT}")
    assert reader.requests == 1


def test_reader_refuses_endpoint_and_deadline_before_connection(monkeypatch):
    monkeypatch.setattr(
        service.http.client, "HTTPSConnection", lambda *_a, **_k: pytest.fail("unexpected network")
    )
    reader = service.PublicReader()
    with pytest.raises(Refused):
        reader("https://evil.invalid/plan.json")
    reader.deadline = 0
    with pytest.raises(Refused, match="github_timeout"):
        reader(f"/repos/{REPO}/git/commits/{COMMIT}")


def test_shared_response_corpus_and_full_source_bindings():
    folder = ROOT / "desktop/tests/fixtures"
    record = json.loads((folder / "untrusted-snapshot.json").read_text(encoding="utf-8"))
    view = json.loads((folder / "untrusted-view.json").read_text(encoding="utf-8"))
    assert project_snapshot(record) == view
    service.validate(view, service.SCHEMA["$defs"]["snapshot"])
    for field in ("executionAuthority", "spendingAuthority", "approval", "verification"):
        altered = deepcopy(view)
        altered[field] = True
        with pytest.raises(Refused):
            service.validate(altered, service.SCHEMA["$defs"]["snapshot"])
