"""Adversarial tests of portable offline handoffs and supplied evidence."""

import hashlib
import json
import socket
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from daf.contract import Refused, canonical
from daf.external_receipts import validate_external_receipt
from daf.receipt_bridge import main, read_document
from daf.supervised_handoff import (
    MAX_BYTES,
    SUPPLIED,
    prepare_task,
    reconcile_receipt,
    validate_bundle,
)


def request_fixture():
    return {
        "schema_version": 1,
        "plan_sha256": "a" * 64,
        "milestone_id": "M1",
        "attempt_id": "attempt-1",
        "repository": "example/product",
        "baseline_sha": "b" * 40,
        "instruction": "Update the synthetic example.\nKeep the change within the named files.",
        "allowed_paths": ["src/example.py", "tests/test_example.py"],
        "required_checks": [
            {
                "name": "offline",
                "validator_id": "reviewer-1",
                "source": "homeci",
                "workflow_path": ".github/workflows/offline.yml",
                "workflow_sha256": "e" * 64,
                "artifact_name": "homeci-result",
            }
        ],
    }


def case():
    bundle = prepare_task(request_fixture())
    receipt = {
        "schema_version": 1,
        "plan_sha256": "a" * 64,
        "milestone_id": "M1",
        "attempt_id": "attempt-1",
        "repository": "example/product",
        "baseline_sha": "b" * 40,
        "head_sha": "c" * 40,
        "task_sha256": bundle["task_sha256"],
        "execution": "supervised_codex",
        "checks": [
            {
                "name": "offline",
                "head_sha": "c" * 40,
                "result": "passed",
                "url": "https://github.com/example/product/actions/runs/12",
            }
        ],
        "pr_url": "https://github.com/example/product/pull/3",
        "status": SUPPLIED,
    }
    content = canonical({"synthetic": True, "message": "example artifact bytes"}).encode()
    evidence = {
        "schema_version": 1,
        "status": SUPPLIED,
        "repository": "example/product",
        "pr_url": receipt["pr_url"],
        "baseline_sha": "b" * 40,
        "head_sha": "c" * 40,
        "changed_paths": ["src/example.py"],
        "checks": [
            {
                "name": "offline",
                "validator_id": "reviewer-1",
                "source": "homeci",
                "head_sha": "c" * 40,
                "workflow_path": ".github/workflows/offline.yml",
                "workflow_sha256": "e" * 64,
                "run_id": 12,
                "run_attempt": 1,
                "job_id": 34,
                "status": "completed",
                "conclusion": "success",
                "url": receipt["checks"][0]["url"],
                "artifact": {
                    "artifact_id": 56,
                    "name": "homeci-result",
                    "sha256": hashlib.sha256(content).hexdigest(),
                },
            }
        ],
    }
    return bundle, receipt, evidence, {"homeci-result": content}


def test_full_reconciliation_remains_unverified_even_with_consistent_fabricated_input():
    bundle, receipt, evidence, artifacts = case()
    before = deepcopy((bundle, receipt, evidence, artifacts))
    result = reconcile_receipt(bundle, receipt, evidence, artifacts)
    assert (bundle, receipt, evidence, artifacts) == before
    assert result["status"] == SUPPLIED
    assert result["execution_authority"] is False
    assert result["all_required_checks_claimed_passed"] is True
    observation = result["comparison"]["artifacts"][0]
    assert observation["status"] == "locally_observed"
    assert (observation["run_id"], observation["run_attempt"], observation["job_id"]) == (12, 1, 34)
    assert result["receipt_sha256"] != result["evidence_sha256"]


def test_bundle_is_deterministic_copied_and_covers_whole_request():
    request = request_fixture()
    bundle = prepare_task(request)
    assert bundle == prepare_task(dict(reversed(list(request.items()))))
    request["allowed_paths"].append("other.py")
    assert bundle["request"]["allowed_paths"] != request["allowed_paths"]
    assert prepare_task(request)["task_sha256"] != bundle["task_sha256"]
    bundle["request"]["instruction"] = "A different task"
    with pytest.raises(Refused, match="task_bundle_mismatch"):
        validate_bundle(bundle)


@pytest.mark.parametrize("value", [True, 0, 1, "false"])
def test_no_bundle_authority(value):
    bundle = case()[0]
    bundle["execution_authority"] = value
    with pytest.raises(Refused, match="handoff_cannot_grant_authority"):
        validate_bundle(bundle)


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/absolute.py",
        "C:/file.py",
        "src\\file.py",
        "src//file.py",
        "src/./file.py",
        "src/../file.py",
        "src/*",
        "src/",
        ".git/config",
        ".GIT/config",
        "src/a:stream",
        "src/%2e%2e/file.py",
        "src/a\n.py",
        "src/a.",
        "NUL.py",
        "aux/file.py",
        "COM1.txt",
        "src/a ",
        "",
        "a" * 241,
    ],
)
def test_nonportable_scope_paths_refused(path):
    request = request_fixture()
    request["allowed_paths"] = [path]
    with pytest.raises(Refused):
        prepare_task(request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("plan_sha256", "wrong"),
        ("baseline_sha", "main"),
        ("milestone_id", []),
        ("attempt_id", ""),
        ("repository", "../outside"),
        ("instruction", ""),
        ("instruction", "\x00"),
        ("instruction", "a" * 16001),
        ("allowed_paths", []),
        ("allowed_paths", ["a.py", "A.py"]),
        ("required_checks", []),
        ("required_checks", {}),
        ("required_checks", [None]),
    ],
)
def test_malformed_task_refused(field, value):
    request = request_fixture()
    request[field] = value
    with pytest.raises(Refused):
        prepare_task(request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", []),
        ("source", "live"),
        ("validator_id", ""),
        ("name", " offline"),
        ("workflow_path", "scripts/ci.py"),
        ("workflow_sha256", "head"),
        ("artifact_name", None),
    ],
)
def test_missing_or_invalid_validator_provenance(field, value):
    request = request_fixture()
    request["required_checks"][0][field] = value
    with pytest.raises(Refused):
        prepare_task(request)


def test_workflow_cannot_be_in_proposed_edit_scope():
    request = request_fixture()
    request["allowed_paths"].append(".GITHUB/workflows/OFFLINE.yml")
    with pytest.raises(Refused, match="required_workflow_in_scope"):
        prepare_task(request)


@pytest.mark.parametrize("variation", ["name", "artifact", "workflow"])
def test_conflicting_required_check_provenance(variation):
    request = request_fixture()
    other = deepcopy(request["required_checks"][0])
    if variation != "name":
        other["name"] = "security"
    if variation == "workflow":
        other["artifact_name"] = "security-result"
        other["workflow_sha256"] = "f" * 64
    request["required_checks"].append(other)
    with pytest.raises(Refused):
        prepare_task(request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_sha256", "f" * 64),
        ("milestone_id", "M2"),
        ("attempt_id", "attempt-2"),
        ("baseline_sha", "d" * 40),
        ("task_sha256", "f" * 64),
        ("execution", "manual"),
        ("pr_url", None),
    ],
)
def test_receipt_bound_to_exact_task(field, value):
    bundle, receipt, evidence, artifacts = case()
    receipt[field] = value
    with pytest.raises(Refused):
        reconcile_receipt(bundle, receipt, evidence, artifacts)


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "other/product"),
        ("pr_url", "https://github.com/example/product/pull/4"),
        ("baseline_sha", "d" * 40),
        ("head_sha", "d" * 40),
        ("status", "verified"),
        ("schema_version", True),
        ("changed_paths", ["src/outsider.py"]),
        ("changed_paths", ["src/../outside.py"]),
        ("changed_paths", ["SRC/example.py"]),
        ("changed_paths", ["src/example.py"] * 2),
        ("checks", []),
    ],
)
def test_pr_scope_and_revision_mismatch(field, value):
    bundle, receipt, evidence, artifacts = case()
    evidence[field] = value
    with pytest.raises(Refused):
        reconcile_receipt(bundle, receipt, evidence, artifacts)


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "unrequired"),
        ("validator_id", "different-reviewer"),
        ("source", "github_actions"),
        ("head_sha", "d" * 40),
        ("workflow_path", ".github/workflows/untrusted.yml"),
        ("workflow_sha256", "f" * 64),
        ("run_id", 13),
        ("run_attempt", True),
        ("job_id", 0),
        ("job_id", "34"),
        ("status", []),
        ("status", "unknown"),
        ("conclusion", []),
        ("conclusion", None),
        ("conclusion", "skipped"),
        ("url", "https://github.com/other/product/actions/runs/12"),
        ("artifact", None),
    ],
)
def test_check_provenance_and_false_success_refused(field, value):
    bundle, receipt, evidence, artifacts = case()
    evidence["checks"][0][field] = value
    with pytest.raises(Refused):
        reconcile_receipt(bundle, receipt, evidence, artifacts)


@pytest.mark.parametrize(
    "status,conclusion,claim",
    [
        ("completed", "failure", "failed"),
        ("completed", "skipped", "failed"),
        ("completed", "cancelled", "failed"),
        ("completed", "neutral", "failed"),
        ("queued", None, "pending"),
        ("in_progress", None, "pending"),
    ],
)
def test_failed_or_pending_claims_never_become_passed(status, conclusion, claim):
    bundle, receipt, evidence, artifacts = case()
    evidence["checks"][0].update(status=status, conclusion=conclusion)
    receipt["checks"][0]["result"] = claim
    result = reconcile_receipt(bundle, receipt, evidence, artifacts)
    assert result["status"] == SUPPLIED
    assert result["all_required_checks_claimed_passed"] is False


def test_premature_conclusion_refused():
    bundle, receipt, evidence, artifacts = case()
    evidence["checks"][0]["status"] = "queued"
    receipt["checks"][0]["result"] = "pending"
    with pytest.raises(Refused, match="premature_check_conclusion"):
        reconcile_receipt(bundle, receipt, evidence, artifacts)


@pytest.mark.parametrize("mutation", ["missing", "tampered", "oversized", "extra"])
def test_local_artifact_bytes_are_required_and_digested(mutation):
    bundle, receipt, evidence, artifacts = case()
    if mutation == "missing":
        artifacts = {}
    elif mutation == "tampered":
        artifacts["homeci-result"] += b"changed"
    elif mutation == "oversized":
        artifacts["homeci-result"] = b"x" * (MAX_BYTES + 1)
    else:
        artifacts["other"] = b"extra"
    with pytest.raises(Refused):
        reconcile_receipt(bundle, receipt, evidence, artifacts)


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_id", True),
        ("name", "other"),
        ("sha256", "invalid"),
        ("sha256", "f" * 64),
    ],
)
def test_artifact_descriptor_refused(field, value):
    bundle, receipt, evidence, artifacts = case()
    evidence["checks"][0]["artifact"][field] = value
    with pytest.raises(Refused):
        reconcile_receipt(bundle, receipt, evidence, artifacts)


def two_checks():
    bundle, receipt, evidence, artifacts = case()
    request = bundle["request"]
    second = deepcopy(request["required_checks"][0])
    second.update(name="security", artifact_name="security-result")
    request["required_checks"].append(second)
    bundle = prepare_task(request)
    receipt["task_sha256"] = bundle["task_sha256"]
    receipt["checks"].append(dict(receipt["checks"][0], name="security"))
    other = deepcopy(evidence["checks"][0])
    other.update(name="security", job_id=35)
    other["artifact"].update(name="security-result", artifact_id=57)
    evidence["checks"].append(other)
    artifacts["security-result"] = artifacts["homeci-result"]
    return bundle, receipt, evidence, artifacts


def test_matrix_jobs_can_share_run_but_have_distinct_jobs_and_artifacts():
    assert reconcile_receipt(*two_checks())["all_required_checks_claimed_passed"]


@pytest.mark.parametrize("field,value", [("run_attempt", 2), ("job_id", 34), ("name", "offline")])
def test_mixed_attempts_duplicate_jobs_or_checks_refused(field, value):
    bundle, receipt, evidence, artifacts = two_checks()
    evidence["checks"][1][field] = value
    with pytest.raises(Refused):
        reconcile_receipt(bundle, receipt, evidence, artifacts)


def test_duplicate_artifact_id_refused():
    bundle, receipt, evidence, artifacts = two_checks()
    evidence["checks"][1]["artifact"]["artifact_id"] = 56
    with pytest.raises(Refused, match="duplicate_evidence_artifact"):
        reconcile_receipt(bundle, receipt, evidence, artifacts)


def test_missing_required_receipt_check_refused():
    bundle, receipt, evidence, artifacts = case()
    receipt["checks"] = []
    with pytest.raises(Refused, match="receipt_required_checks_mismatch"):
        reconcile_receipt(bundle, receipt, evidence, artifacts)


def test_github_check_without_artifact_supported():
    bundle, receipt, evidence, _ = case()
    bundle["request"]["required_checks"][0].update(source="github_actions", artifact_name=None)
    bundle = prepare_task(bundle["request"])
    receipt["task_sha256"] = bundle["task_sha256"]
    evidence["checks"][0].update(source="github_actions", artifact=None)
    assert reconcile_receipt(bundle, receipt, evidence)["comparison"]["artifacts"] == []
    evidence["checks"][0]["artifact"] = {}
    with pytest.raises(Refused, match="unexpected_evidence_artifact"):
        reconcile_receipt(bundle, receipt, evidence)


@pytest.mark.parametrize(
    "record", ["bundle", "request", "receipt", "evidence", "check", "artifact"]
)
def test_unknown_fields_cannot_smuggle_authority(record):
    bundle, receipt, evidence, artifacts = case()
    targets = {
        "bundle": bundle,
        "request": bundle["request"],
        "receipt": receipt,
        "evidence": evidence,
        "check": evidence["checks"][0],
        "artifact": evidence["checks"][0]["artifact"],
    }
    targets[record]["approved"] = True
    with pytest.raises(Refused):
        reconcile_receipt(bundle, receipt, evidence, artifacts)


def test_bridge_has_no_process_network_or_write_side_effects(monkeypatch):
    inputs = case()

    def denied(*args, **kwargs):
        pytest.fail("unexpected capability used")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(Path, "open", denied)
    assert reconcile_receipt(*inputs)["status"] == SUPPLIED
    assert validate_bundle(inputs[0])["execution_authority"] is False


def test_cli_end_to_end(tmp_path, capsys):
    bundle, receipt, evidence, artifacts = case()
    for name, value in (
        ("request", bundle["request"]),
        ("bundle", bundle),
        ("receipt", receipt),
        ("evidence", evidence),
    ):
        (tmp_path / f"{name}.json").write_text(canonical(value), encoding="utf-8")
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(artifacts["homeci-result"])
    assert main(["prepare", str(tmp_path / "request.json")]) == 0
    assert json.loads(capsys.readouterr().out) == bundle
    assert main(["validate", str(tmp_path / "receipt.json")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == SUPPLIED
    args = [
        "reconcile",
        *(str(tmp_path / f"{name}.json") for name in ("bundle", "receipt", "evidence")),
        "--artifact",
        "homeci-result",
        str(artifact),
    ]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == reconcile_receipt(
        bundle, receipt, evidence, artifacts
    )
    assert main(args + ["--artifact", "homeci-result", str(artifact)]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "duplicate_artifact_input"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "artifact.json",
        "bundle.json",
        "evidence.json",
        "receipt.json",
        "request.json",
    ]


@pytest.mark.parametrize(
    "content,reason",
    [
        ('{"schema_version":1,"schema_version":1}', "duplicate_json_key"),
        ('{"x":NaN}', "nonfinite_json_value"),
        ('{"x":Infinity}', "nonfinite_json_value"),
        ('{"private-input":', "invalid_or_unavailable_local_input"),
        ("[" * 2000, "invalid_or_unavailable_local_input"),
    ],
)
def test_cli_malformed_input_is_redacted(tmp_path, capsys, content, reason):
    path = tmp_path / "input.json"
    path.write_text(content, encoding="utf-8")
    assert main(["prepare", str(path)]) == 2
    assert json.loads(capsys.readouterr().out) == {"outcome": "refused", "reason": reason}


def test_cli_missing_file_redacted(tmp_path, capsys):
    assert main(["prepare", str(tmp_path / "private-name")]) == 2
    assert "private-name" not in capsys.readouterr().out


def test_cli_refuses_oversized_file_and_directory(tmp_path):
    path = tmp_path / "input.json"
    path.write_bytes(b" " * (MAX_BYTES + 1))
    with pytest.raises(Refused, match="document_too_large"):
        read_document(path)
    with pytest.raises(Refused, match="regular_input_required"):
        read_document(tmp_path)


def test_cli_refuses_linked_input(tmp_path):
    path = tmp_path / "input.json"
    path.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(Refused, match="linked_input_refused"):
        read_document(link)


@pytest.mark.parametrize(
    "field,value",
    [
        ("execution", []),
        ("execution", {}),
        ("repository", "./repo"),
        ("repository", "../repo"),
        ("repository", "owner/.."),
        ("repository", "owner/."),
    ],
)
def test_original_receipt_malformed_fields_raise_refused(field, value):
    receipt = case()[1]
    receipt[field] = value
    with pytest.raises(Refused):
        validate_external_receipt(receipt)


@pytest.mark.parametrize(
    "field,value",
    [
        ("result", []),
        ("result", {}),
        ("name", "offline\n"),
        ("name", " offline"),
    ],
)
def test_original_check_malformed_fields_raise_refused(field, value):
    receipt = case()[1]
    receipt["checks"][0][field] = value
    with pytest.raises(Refused):
        validate_external_receipt(receipt)


@pytest.mark.parametrize(
    "name",
    [
        "//server/share/input.json",
        r"\\server\share\input.json",
        r"\\.\pipe\input",
        r"\\?\C:\input.json",
    ],
)
def test_cli_refuses_network_and_device_paths_before_filesystem_access(monkeypatch, name):
    def denied(*args, **kwargs):
        pytest.fail("network/device path reached filesystem inspection")

    monkeypatch.setattr(Path, "stat", denied)
    monkeypatch.setattr(Path, "is_symlink", denied)
    with pytest.raises(Refused, match="network_or_device_input_refused"):
        read_document(Path(name))


def test_cli_junction_guard_without_requiring_symlink_privilege(tmp_path, monkeypatch):
    path = tmp_path / "input.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "is_junction", lambda self: self == path)
    with pytest.raises(Refused, match="linked_input_refused"):
        read_document(path)
