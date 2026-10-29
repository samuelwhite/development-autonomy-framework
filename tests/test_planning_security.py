"""Cross-platform adversarial checks for proposals, never execution authority."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_github_planning import COMMIT, PATH, REPO, fake_source, fixture, imported

from daf.contract import Refused, canonical, digest
from daf.github_planning import (
    MAX_RESPONSE,
    ingest_public_milestone,
    load_ingest_record,
    store_idempotently,
    validate_ingest_record,
    validate_planning_document,
)
from daf.supervised_handoff import prepare_task


@pytest.mark.parametrize("task_index", [0, 1])
@pytest.mark.parametrize("name", ["protected.py", "PROTECTED.PY", "PrOtEcTeD.py"])
def test_windows_protected_file_alias_in_every_task(task_index, name):
    doc = fixture()
    doc["plan"]["validation"]["protected_files"]["src/daf/examples/Protected.py"] = "d" * 64
    doc["tasks"][task_index]["allowed_paths"] = [f"SRC/DAF/EXAMPLES/{name}"]
    with pytest.raises(Refused, match="planning_task_out_of_scope"):
        imported(doc, milestone="F1")


@pytest.mark.parametrize("task_index", [0, 1])
@pytest.mark.parametrize("suffix", ["private/a.py", "PRIVATE/nested/a.py", "PrIvAtE"])
def test_windows_protected_directory_and_entry_alias(task_index, suffix):
    doc = fixture()
    doc["plan"]["boundaries"]["protected_prefixes"].append("src/daf/examples/Private/")
    doc["tasks"][task_index]["allowed_paths"] = [f"src/daf/examples/{suffix}"]
    with pytest.raises(Refused, match="planning_task_out_of_scope"):
        imported(doc)


@pytest.mark.parametrize(
    "filepath",
    [
        "src/daf/examples/private-not/a.py",
        "src/daf/examples/private.py",
        "src/daf/examples/protected.py.bak",
        "SRC/DAF/EXAMPLES/Allowed.py",
    ],
)
def test_legitimate_component_neighbors_and_spelling_preserved(filepath):
    doc = fixture()
    doc["plan"]["boundaries"]["protected_prefixes"] += ["src/daf/examples/private/", ".git/"]
    doc["plan"]["validation"]["protected_files"]["src/daf/examples/PROTECTED.py"] = "d" * 64
    doc["tasks"][0]["allowed_paths"] = [filepath]
    record, _ = imported(doc)
    assert record["bundle"]["request"]["allowed_paths"] == [filepath]
    assert record["source"]["plan_sha256"] == digest(doc["plan"])


@pytest.mark.parametrize("filepath", ["src/daf/examples-extra/a.py", "src/daf/examples"])
def test_code_prefix_requires_a_real_directory_descendant(filepath):
    doc = fixture()
    doc["tasks"][1]["allowed_paths"] = [filepath]
    with pytest.raises(Refused, match="planning_task_out_of_scope"):
        imported(doc)


@pytest.mark.parametrize(
    "filepath",
    [
        "src/daf/examples/../secret.py",
        "src\\daf\\examples\\secret.py",
        "src/daf/examples/a.py:stream",
        "src/daf/examples/a.py.",
        "src/daf/examples/a.py ",
        "src/daf/examples/CON.txt",
        "src/daf/examples/a~1.py",
        "src/daf/examples/%2e%2e/a.py",
        "//server/share/a.py",
        "C:/project/a.py",
        "src/daf/examples/.GiT/config",
        "src/daf/examples//a.py",
    ],
)
def test_unsafe_windows_paths_remain_refused_in_unselected_task(filepath):
    doc = fixture()
    doc["tasks"][1]["allowed_paths"] = [filepath]
    with pytest.raises(Refused):
        imported(doc)


@pytest.mark.parametrize("section", ["files", "code", "protected", "tasks"])
def test_ambiguous_case_aliases_are_refused(section):
    doc = fixture()
    if section == "files":
        doc["plan"]["validation"]["protected_files"]["SRC/DAF/CONTRACT.PY"] = "a" * 64
    elif section == "tasks":
        doc["tasks"][1]["allowed_paths"] = [doc["tasks"][0]["allowed_paths"][0].upper()]
    else:
        key = f"{section}_prefixes"
        doc["plan"]["boundaries"][key].append(doc["plan"]["boundaries"][key][0].upper())
    with pytest.raises(Refused, match="duplicate_scope_path|ambiguous_task_path"):
        imported(doc)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["tasks"][1].update(instruction=""),
        lambda d: d["tasks"][1].update(required_checks=[]),
        lambda d: d["tasks"][1].update(required_checks=None),
        lambda d: d["tasks"][1]["required_checks"][0].update(validator_id=""),
        lambda d: d["tasks"][1]["required_checks"][0].update(workflow_sha256="a" * 64),
        lambda d: d["tasks"][1]["required_checks"][0].update(name=[]),
        lambda d: d["tasks"][1].update(execution_authority=True),
        lambda d: d["tasks"].pop(),
        lambda d: d["plan"]["milestones"][1].update(depends_on=["F2"]),
    ],
)
def test_entire_plan_refuses_invalid_sibling_even_when_importing_f1(mutate):
    doc = fixture()
    mutate(doc)
    with pytest.raises(Refused):
        imported(doc, milestone="F1")


def test_complete_validation_preserves_dependencies_and_repeated_exact_paths():
    doc = fixture()
    doc["tasks"][1]["allowed_paths"] = deepcopy(doc["tasks"][0]["allowed_paths"])
    plan, bundles = validate_planning_document(doc, REPO)
    assert set(bundles) == {"F1", "F2"}
    assert plan["milestones"][1]["depends_on"] == ["F1"]
    assert all(b["execution_authority"] is False for b in bundles.values())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(status="verified"),
        lambda r: r.update(approval={"approved": True}),
        lambda r: r.update(execution_authority=True),
        lambda r: r.update(execution_authority=0),
        lambda r: r.update(schema_version=True),
        lambda r: r.update(spending_authority=True),
        lambda r: r["source"].update(trusted=True),
        lambda r: r["source"].update(plan_sha256="e" * 64),
        lambda r: r["source"].update(commit_sha="main"),
        lambda r: r["source"].update(content_sha256="not-a-hash"),
        lambda r: r.update(dependencies=["F1"]),
        lambda r: r.update(dependencies=["F2", "F2"]),
        lambda r: r.update(acceptance={"tests": {"verified": True}}),
    ],
)
def test_stored_record_cannot_promote_trust_on_write_or_load(tmp_path, mutation):
    record, _ = imported()
    mutation(record)
    with pytest.raises(Refused):
        store_idempotently(record, tmp_path)
    assert list(tmp_path.iterdir()) == []
    file = tmp_path / "supplied.json"
    file.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(Refused):
        load_ingest_record(file)


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "another/repo"),
        ("milestone_id", "F2"),
        ("attempt_id", "admitted-attempt"),
        ("plan_sha256", "e" * 64),
    ],
)
def test_self_consistent_bundle_cannot_change_record_binding(field, value):
    record, _ = imported()
    request = record["bundle"]["request"]
    request[field] = value
    record["bundle"] = prepare_task(request)
    with pytest.raises(Refused, match="ingest_bundle_binding_mismatch"):
        validate_ingest_record(record)


def test_validated_load_is_still_unverified_and_idempotent(tmp_path):
    record, _ = imported(milestone="F2")
    result = store_idempotently(record, tmp_path)
    loaded = load_ingest_record(Path(result["record_path"]))
    assert loaded == record
    assert loaded["approval"] is None and loaded["execution_authority"] is False
    assert store_idempotently(loaded, tmp_path)["outcome"] == "already_present"
    changed = deepcopy(record)
    changed["approval"] = {"trusted": True}
    Path(result["record_path"]).write_text(canonical(changed), encoding="utf-8")
    with pytest.raises(Refused, match="ingest_cannot_grant_authority"):
        store_idempotently(record, tmp_path)
    assert json.loads(Path(result["record_path"]).read_text())["approval"] == {"trusted": True}


@pytest.mark.parametrize(
    "raw",
    [b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b" " * MAX_RESPONSE],
    ids=["duplicate-key", "nonfinite", "bad-utf8", "oversized"],
)
def test_invalid_stored_json_is_refused(tmp_path, raw):
    file = tmp_path / "record.json"
    file.write_bytes(raw)
    with pytest.raises(Refused):
        load_ingest_record(file)


@pytest.mark.parametrize(
    "mode,kind,component",
    [
        ("120000", "blob", 1),
        ("160000", "commit", 1),
        ("120000", "blob", 5),
        ("160000", "commit", 5),
        ("040000", "tree", 5),
    ],
)
def test_source_symlink_submodule_and_directory_are_refused_before_contents(mode, kind, component):
    base, seen = fake_source()

    def read(path):
        result = base(path)
        if path.endswith(f"/git/trees/{component:040x}"):
            result["tree"][0].update(mode=mode, type=kind)
        return result

    with pytest.raises(Refused, match="github_source_not_"):
        ingest_public_milestone(REPO, COMMIT, PATH, "F1", get_json=read)
    assert not any("/contents/" in path for path in seen)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda t: t.update(truncated=True),
        lambda t: t.update(sha="f" * 40),
        lambda t: t["tree"].append(deepcopy(t["tree"][0])),
        lambda t: t["tree"][0].update(path="SRC"),
        lambda t: t["tree"][0].update(sha="main"),
    ],
)
def test_bad_tree_identity_truncation_or_ambiguous_entry_refused(mutation):
    base, _ = fake_source()

    def read(path):
        result = base(path)
        if path.endswith(f"/git/trees/{1:040x}"):
            mutation(result)
        return result

    with pytest.raises(Refused):
        ingest_public_milestone(REPO, COMMIT, PATH, "F1", get_json=read)


def test_tree_blob_must_match_contents_and_no_download_url_is_followed():
    base, seen = fake_source()

    def read(path):
        result = base(path)
        if path.endswith(f"/git/trees/{5:040x}"):
            result["tree"][0]["sha"] = "f" * 40
        if "/contents/" in path:
            result["download_url"] = "https://untrusted.invalid/"
        return result

    with pytest.raises(Refused, match="github_tree_blob_mismatch"):
        ingest_public_milestone(REPO, COMMIT, PATH, "F1", get_json=read)
    assert len(seen) == 7


def test_source_depth_is_refused_before_network():
    def no_network(_):
        raise AssertionError("Invalid source reached transport")

    with pytest.raises(Refused, match="invalid_source_path"):
        ingest_public_milestone(REPO, COMMIT, "a/" * 16 + "plan.json", "F1", get_json=no_network)


def test_storage_unc_and_junction_refused_before_read(tmp_path, monkeypatch):
    def no_stat(_):
        raise AssertionError("Network path was inspected")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", no_stat)
        with pytest.raises(Refused, match="network_directory_refused"):
            load_ingest_record(Path("//server/share/record.json"))
    monkeypatch.setattr(Path, "is_junction", lambda path: path == tmp_path)
    with pytest.raises(Refused, match="linked_storage_directory_refused"):
        load_ingest_record(tmp_path / "record.json")
