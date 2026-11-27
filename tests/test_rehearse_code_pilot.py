import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from daf.contract import digest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/rehearse_code_pilot.py"
ONCE = {"branch": 1, "draft": 1, "dispatch": 1}


def invoke(workspace, scenario=None, *, code=0):
    args = [sys.executable, str(SCRIPT), str(workspace)]
    if scenario is not None:
        args.extend(("--scenario", scenario))
    call = subprocess.run(args, capture_output=True, timeout=60, check=False)
    assert call.returncode == code, (call.stdout, call.stderr)
    return json.loads(call.stdout)


def assert_review(report):
    result = report["observation"]
    assert result["state"] == "review" and result["conclusion"] == "success"
    assert result["file"] == "src/label.py"
    assert (result["draft_pr"], result["run_id"], result["run_attempt"], result["job_id"]) == (
        28,
        1401,
        1,
        1601,
    )
    assert report["external_writes"] == ONCE


def test_code_cli_publishes_exact_approved_diff_and_recovers_duplicate(tmp_path):
    first = invoke(tmp_path)
    assert_review(first)
    assert invoke(tmp_path) == first
    proposal = json.loads((tmp_path / "proposal.json").read_bytes())
    approval = json.loads((tmp_path / "approval.json").read_bytes())
    diff = (tmp_path / "candidate.diff").read_bytes()
    assert approval["mode"] == "simulated" and approval["execution_authority"] is False
    assert approval["baseline_sha"] == proposal["task"]["request"]["baseline_sha"]
    assert approval["candidate_sha"] == first["observation"]["candidate_sha"]
    assert approval["proposal_sha256"] == digest(proposal)
    assert proposal["diff_sha256"] == hashlib.sha256(diff).hexdigest()
    assert b"-    return value.lower()\n+    return value.strip().lower()\n" in diff
    assert b"Ran 1 test" in (tmp_path / "validation.log").read_bytes()


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        ("lost-response", "dispatch_outcome_unknown"),
        ("incomplete-metadata", "wrong_workflow_dispatch"),
    ],
)
def test_code_cli_restart_reads_original_dispatch(tmp_path, scenario, reason):
    initial = invoke(tmp_path, scenario, code=1)
    assert initial["observation"]["state"] == "blocked"
    assert initial["observation"]["reason"] == reason
    assert "job_id" not in initial["observation"]
    assert initial["external_writes"] == ONCE
    if scenario == "incomplete-metadata":
        assert initial["observation"]["run_id"] == 1401
    recovered = invoke(tmp_path)
    assert_review(recovered)
    assert recovered["observation"]["candidate_sha"] == initial["observation"]["candidate_sha"]


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        ("changed-baseline", "candidate_main_revision_changed"),
        ("extra-file", "candidate_scope_changed"),
    ],
)
def test_code_cli_rejects_scope_before_external_writes(tmp_path, scenario, reason):
    report = invoke(tmp_path, scenario, code=1)
    assert report["observation"]["reason"] == reason
    assert not (tmp_path / "validation.log").exists()
    assert report["external_writes"] == dict.fromkeys(ONCE, 0)


def test_code_cli_refuses_incorrect_run_before_accepting_job(tmp_path):
    report = invoke(tmp_path, "wrong-run", code=1)
    assert report["observation"]["reason"] == "wrong_run_attempt"
    assert report["observation"]["run_id"] == 1401
    assert "job_id" not in report["observation"] and "conclusion" not in report["observation"]
    assert report["external_writes"] == ONCE


def test_code_cli_retains_failed_focused_validation(tmp_path):
    result = invoke(tmp_path, "failed", code=1)
    assert result["observation"]["state"] == "finished"
    assert result["observation"]["conclusion"] == "failure"
    assert result["observation"]["reason"] == "focused_test_failed"
    assert b"FAILED (failures=1)" in (tmp_path / "validation.log").read_bytes()
    assert result["external_writes"] == ONCE
    assert invoke(tmp_path, code=1) == result
