"""Offline adversarial tests of pinned public GitHub planning and idempotent writes."""

import ast
import base64
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from daf.contract import Refused
from daf.github_planning import ingest_public_milestone, store_idempotently

REPO = "samuelwhite/development-autonomy-framework"
COMMIT = "7b24b7ce84eb7a44d2179adcbd77c17d3bda8b52"
PATH = "src/daf/examples/planning/public-m1.json"
EXAMPLE = Path(__file__).resolve().parents[1] / PATH


def fixture():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def fake_source(doc=None, *, raw=None, metadata=None):
    if doc is None:
        doc = fixture()
    if raw is None:
        raw = json.dumps(doc, sort_keys=True).encode("utf-8")
    git_hash = hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False
    ).hexdigest()
    contents = {
        "type": "file",
        "encoding": "base64",
        "path": PATH,
        "sha": git_hash,
        "size": len(raw),
        "content": base64.b64encode(raw).decode(),
    }
    contents.update(metadata or {})
    seen = []

    def reader(path):
        seen.append(path)
        if "/git/commits/" in path:
            return {"sha": COMMIT}
        return contents

    return reader, seen


def imported(doc=None, milestone="F1", *, raw=None, metadata=None):
    reader, seen = fake_source(doc, raw=raw, metadata=metadata)
    record = ingest_public_milestone(REPO, COMMIT, PATH, milestone, get_json=reader)
    return record, seen


def test_valid_public_example_and_exact_pinned_paths():
    record, seen = imported(milestone="F2")
    assert seen == [
        f"/repos/{REPO}/git/commits/{COMMIT}",
        f"/repos/{REPO}/contents/{PATH}?ref={COMMIT}",
    ]
    assert record["execution_authority"] is False
    assert record["approval"] is None
    assert record["status"] == "pinned_plan_proposal"
    assert record["dependencies"] == ["F1"]
    assert set(record["acceptance"]) == {"tests", "security"}
    assert record["bundle"]["status"] == "proposed_supervised_task"
    assert record["bundle"]["request"]["attempt_id"] == "proposal-F2"
    assert record["source"]["commit_sha"] == COMMIT
    assert record == imported(milestone="F2")[0]


def test_idempotent_record_and_source_conflict(tmp_path):
    first, _ = imported()
    created = store_idempotently(first, tmp_path)
    repeated = store_idempotently(first, tmp_path)
    assert (created["outcome"], repeated["outcome"]) == ("created", "already_present")
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert Path(created["record_path"]).read_text().endswith("\n")
    changed = fixture()
    changed["tasks"][0]["instruction"] = "Changed input at identical pinned address"
    different, _ = imported(changed)
    assert different["ingestion_id"] == first["ingestion_id"]
    with pytest.raises(Refused, match="ingestion_conflict"):
        store_idempotently(different, tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_concurrent_repeated_ingestion_creates_one_record(tmp_path):
    record, _ = imported()
    with ThreadPoolExecutor(max_workers=4) as workers:
        outcomes = list(workers.map(lambda _: store_idempotently(record, tmp_path), range(4)))
    assert sorted(x["outcome"] for x in outcomes) == [
        "already_present",
        "already_present",
        "already_present",
        "created",
    ]
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "../repo"),
        ("milestone", "F3"),
        ("path", "../evil.json"),
        ("path", "src/evil.txt"),
        ("commit", "main"),
        ("commit", "g" * 40),
    ],
)
def test_bad_identity_or_path_refused(field, value):
    options = {
        "repository": REPO,
        "commit_sha": COMMIT,
        "source_path": PATH,
        "milestone_id": "F1",
    }
    mapping = {
        "repository": "repository",
        "milestone": "milestone_id",
        "path": "source_path",
        "commit": "commit_sha",
    }
    options[mapping[field]] = value
    if field == "milestone":
        options["get_json"] = fake_source()[0]
    else:

        def no_network(_path):
            raise AssertionError("Invalid input reached external transport")

        options["get_json"] = no_network
    with pytest.raises(Refused):
        ingest_public_milestone(**options)


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda d: d["plan"].update(repository="other/repo"), "planning_repository_mismatch"),
        (
            lambda d: d["plan"]["milestones"][1].update(depends_on=["missing"]),
            "dependency_must_precede_milestone",
        ),
        (
            lambda d: d["tasks"].append(deepcopy(d["tasks"][0])),
            "invalid_or_duplicate_planning_task",
        ),
        (
            lambda d: d["tasks"][0].update(allowed_paths=["src/daf/engine.py"]),
            "planning_task_out_of_scope",
        ),
        (
            lambda d: d["tasks"][0].update(allowed_paths=[".github/workflows/ci.yml"]),
            "planning_task_out_of_scope",
        ),
        (
            lambda d: d["tasks"][0]["required_checks"][0].update(workflow_sha256="a" * 64),
            "planning_workflow_mismatch",
        ),
        (lambda d: d["tasks"][0].update(required_checks=[]), "planning_check_mismatch"),
        (lambda d: d["tasks"][0].update(execution_authority=True), "invalid_contract_fields"),
        (lambda d: d["plan"]["actions"].update(merge=True), "live_actions_unavailable"),
    ],
)
def test_scope_dependencies_and_authority_refused(mutate, reason):
    doc = fixture()
    mutate(doc)
    with pytest.raises(Refused, match=reason):
        imported(doc)


def test_commit_blob_and_file_metadata_mismatches():
    def wrong_commit(_path):
        return {"sha": "a" * 40}

    with pytest.raises(Refused, match="github_commit_mismatch"):
        ingest_public_milestone(REPO, COMMIT, PATH, "F1", get_json=wrong_commit)
    for metadata, reason in [
        ({"sha": "a" * 40}, "github_blob_mismatch"),
        ({"size": 0}, "github_file_size_mismatch"),
        ({"type": "symlink"}, "invalid_github_file"),
        ({"target": "outside"}, "invalid_github_file"),
        ({"content": "!not-base64!"}, "invalid_github_base64"),
    ]:
        with pytest.raises(Refused, match=reason):
            imported(metadata=metadata)


def test_duplicate_keys_and_nonfinite_values_refused():
    for raw, reason in [
        (b'{"schema_version":1,"schema_version":1}', "duplicate_json_key"),
        (b'{"schema_version":NaN}', "nonfinite_json_value"),
    ]:
        with pytest.raises(Refused, match=reason):
            imported(raw=raw)


def test_symlink_output_and_existing_record_link_refused(tmp_path):
    record, _ = imported()
    folder = tmp_path / "real"
    folder.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(folder, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable")
    with pytest.raises(Refused, match="linked_storage_directory_refused"):
        store_idempotently(record, alias)
    existing = folder / f"{record['ingestion_id']}.json"
    existing.symlink_to(EXAMPLE)
    with pytest.raises(Refused, match="ingestion_conflict"):
        store_idempotently(record, folder)


def test_packaged_module_stays_offline():
    file = Path(__file__).resolve().parents[1] / "src/daf/github_planning.py"
    imports = set()
    for node in ast.walk(ast.parse(file.read_text())):
        if isinstance(node, ast.Import):
            imports.update(item.name.split(".")[0] for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".")[0])
    assert not imports.intersection({"http", "urllib", "socket", "subprocess", "requests"})
