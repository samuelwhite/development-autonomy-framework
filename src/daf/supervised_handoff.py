"""Pure offline handoffs and claim reconciliation. No execution or identity authority."""

import hashlib
import json
import re
from typing import Any

from .contract import canonical, digest, keys, require, sha
from .external_receipts import receipt_sha256, validate_external_receipt, validate_repository

SUPPLIED = "externally_supplied_unverified"
MAX_BYTES = 2 * 1024 * 1024


def text_field(value: Any, limit: int = 120) -> str:
    require(
        isinstance(value, str)
        and 0 < len(value) <= limit
        and value == value.strip()
        and value.isprintable(),
        "invalid_handoff_text",
    )
    return value


def file_path(value: Any) -> str:
    """Conservative, case-portable exact file names, not glob or directory scopes."""
    text_field(value, 1024)
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    for part in value.split("/"):
        require(
            re.fullmatch(r"[A-Za-z0-9_.-]{1,240}", part) is not None
            and part not in {".", ".."}
            and not part.endswith(".")
            and part.casefold() != ".git"
            and part.split(".")[0].upper() not in reserved,
            "invalid_handoff_path",
        )
    return value


def paths(value: Any, *, empty: bool = False) -> list[str]:
    require(
        isinstance(value, list) and (empty or bool(value)) and len(value) <= 256,
        "invalid_handoff_paths",
    )
    result = [file_path(path) for path in value]
    require(len({path.casefold() for path in result}) == len(result), "duplicate_handoff_path")
    return result


def positive_id(value: Any) -> int:
    require(type(value) is int and 0 < value < 2**63, "invalid_evidence_id")
    return value


def _version(value: Any) -> None:
    require(type(value) is int and value == 1, "invalid_handoff_schema")


def prepare_task(value: Any) -> dict[str, Any]:
    """Fingerprint the complete proposed scope. This records no admission or approval."""
    request = keys(
        value,
        {
            "schema_version",
            "plan_sha256",
            "milestone_id",
            "attempt_id",
            "repository",
            "baseline_sha",
            "instruction",
            "allowed_paths",
            "required_checks",
        },
    )
    _version(request["schema_version"])
    sha(request["plan_sha256"])
    sha(request["baseline_sha"], 40)
    validate_repository(request["repository"])
    for field in ("milestone_id", "attempt_id"):
        require(
            isinstance(request[field], str)
            and re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", request[field]) is not None,
            "invalid_handoff_identity",
        )
    instruction = request["instruction"]
    require(
        isinstance(instruction, str)
        and 0 < len(instruction.strip()) <= 16000
        and len(instruction) <= 16000
        and all(char.isprintable() or char in "\n\r\t" for char in instruction),
        "invalid_handoff_instruction",
    )
    allowed = paths(request["allowed_paths"])
    checks = request["required_checks"]
    require(isinstance(checks, list) and 0 < len(checks) <= 32, "invalid_required_checks")
    names, artifacts = set(), set()
    workflows = {}
    for raw in checks:
        check = keys(
            raw,
            {"name", "validator_id", "source", "workflow_path", "workflow_sha256", "artifact_name"},
        )
        name = text_field(check["name"])
        require(name not in names, "duplicate_required_check")
        names.add(name)
        text_field(check["validator_id"])
        require(
            isinstance(check["source"], str) and check["source"] in {"github_actions", "homeci"},
            "invalid_evidence_source",
        )
        workflow = file_path(check["workflow_path"])
        require(
            workflow.startswith(".github/workflows/") and workflow.endswith((".yml", ".yaml")),
            "invalid_workflow_path",
        )
        sha(check["workflow_sha256"])
        folded = workflow.casefold()
        require(
            folded not in workflows or workflows[folded] == check["workflow_sha256"],
            "conflicting_workflow_digest",
        )
        workflows[folded] = check["workflow_sha256"]
        artifact = check["artifact_name"]
        if artifact is not None:
            text_field(artifact)
            require(artifact not in artifacts, "duplicate_required_artifact")
            artifacts.add(artifact)
        require(check["source"] != "homeci" or artifact is not None, "homeci_artifact_required")
    require(
        not set(workflows).intersection(path.casefold() for path in allowed),
        "required_workflow_in_scope",
    )
    # Deep copy prevents caller mutation after fingerprinting.
    return json.loads(
        canonical(
            {
                "schema_version": 1,
                "status": "proposed_supervised_task",
                "execution": "supervised_codex",
                "execution_authority": False,
                "request": request,
                "task_sha256": digest(request),
            }
        )
    )


def validate_bundle(value: Any) -> dict[str, Any]:
    bundle = keys(
        value,
        {"schema_version", "status", "execution", "execution_authority", "request", "task_sha256"},
    )
    _version(bundle["schema_version"])
    require(bundle["execution_authority"] is False, "handoff_cannot_grant_authority")
    expected = prepare_task(bundle["request"])
    require(bundle == expected, "task_bundle_mismatch")
    return expected


def _claimed_result(status: Any, conclusion: Any) -> str:
    require(
        isinstance(status, str) and status in {"queued", "in_progress", "completed"},
        "invalid_check_status",
    )
    if status != "completed":
        require(conclusion is None, "premature_check_conclusion")
        return "pending"
    require(
        isinstance(conclusion, str)
        and conclusion
        in {
            "success",
            "failure",
            "neutral",
            "cancelled",
            "skipped",
            "timed_out",
            "action_required",
            "stale",
            "startup_failure",
        },
        "invalid_check_conclusion",
    )
    # Skipped, neutral and cancelled checks never satisfy required success.
    return "passed" if conclusion == "success" else "failed"


def reconcile_receipt(
    bundle: Any,
    receipt: Any,
    evidence: Any,
    artifacts: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Compare supplied records and explicitly supplied artifact bytes, never authenticate."""
    task = validate_bundle(bundle)
    claim = validate_external_receipt(receipt)
    request = task["request"]
    for field in ("plan_sha256", "milestone_id", "attempt_id", "repository", "baseline_sha"):
        require(claim[field] == request[field], "receipt_task_binding_mismatch")
    require(claim["task_sha256"] == task["task_sha256"], "receipt_task_binding_mismatch")
    require(claim["execution"] == task["execution"], "receipt_execution_mismatch")
    require(claim["pr_url"] is not None, "receipt_pr_required")
    supplied = keys(
        evidence,
        {
            "schema_version",
            "status",
            "repository",
            "pr_url",
            "baseline_sha",
            "head_sha",
            "changed_paths",
            "checks",
        },
    )
    _version(supplied["schema_version"])
    require(supplied["status"] == SUPPLIED, "external_evidence_cannot_self_verify")
    for field in ("repository", "pr_url", "baseline_sha", "head_sha"):
        require(supplied[field] == claim[field], "evidence_revision_or_pr_mismatch")
    changed = paths(supplied["changed_paths"], empty=True)
    require(set(changed) <= set(request["allowed_paths"]), "changed_path_out_of_scope")
    required = {check["name"]: check for check in request["required_checks"]}
    claims = {check["name"]: check for check in claim["checks"]}
    require(set(claims) == set(required), "receipt_required_checks_mismatch")
    records = supplied["checks"]
    require(
        isinstance(records, list) and len(records) == len(required),
        "evidence_required_checks_mismatch",
    )
    artifacts = {} if artifacts is None else artifacts
    require(isinstance(artifacts, dict), "invalid_artifact_inputs")
    seen, jobs, artifact_ids = set(), set(), set()
    runs = {}
    observations = []
    check_observations = []
    all_passed = True
    for raw in records:
        record = keys(
            raw,
            {
                "name",
                "validator_id",
                "source",
                "head_sha",
                "workflow_path",
                "workflow_sha256",
                "run_id",
                "run_attempt",
                "job_id",
                "status",
                "conclusion",
                "url",
                "artifact",
            },
        )
        name = text_field(record["name"])
        require(name in required and name not in seen, "duplicate_or_unexpected_evidence_check")
        seen.add(name)
        expected = required[name]
        for field in ("validator_id", "source", "workflow_path", "workflow_sha256"):
            require(record[field] == expected[field], "evidence_provenance_mismatch")
        require(record["head_sha"] == claim["head_sha"], "evidence_revision_or_pr_mismatch")
        run_id = positive_id(record["run_id"])
        attempt = positive_id(record["run_attempt"])
        job_id = positive_id(record["job_id"])
        require(job_id not in jobs, "duplicate_evidence_job")
        jobs.add(job_id)
        binding = (attempt, record["workflow_path"], record["workflow_sha256"], record["source"])
        require(run_id not in runs or runs[run_id] == binding, "inconsistent_run_attempt")
        runs[run_id] = binding
        url = f"https://github.com/{claim['repository']}/actions/runs/{run_id}"
        require(record["url"] == url == claims[name]["url"], "evidence_run_link_mismatch")
        result = _claimed_result(record["status"], record["conclusion"])
        require(result == claims[name]["result"], "evidence_result_mismatch")
        all_passed = all_passed and result == "passed"
        check_observations.append(
            {
                "name": name,
                "status": SUPPLIED,
                "claimed_result": result,
                "head_sha": claim["head_sha"],
                "run_id": run_id,
                "run_attempt": attempt,
                "job_id": job_id,
                "attempt_url": f"{url}/attempts/{attempt}",
                "job_url": f"{url}/job/{job_id}",
            }
        )
        artifact_name = expected["artifact_name"]
        if artifact_name is None:
            require(record["artifact"] is None, "unexpected_evidence_artifact")
            continue
        artifact = keys(record["artifact"], {"artifact_id", "name", "sha256"})
        artifact_id = positive_id(artifact["artifact_id"])
        require(artifact_id not in artifact_ids, "duplicate_evidence_artifact")
        artifact_ids.add(artifact_id)
        require(artifact["name"] == artifact_name, "evidence_artifact_name_mismatch")
        sha(artifact["sha256"])
        content = artifacts.get(artifact_name)
        require(
            isinstance(content, bytes) and len(content) <= MAX_BYTES,
            "missing_or_oversized_artifact",
        )
        observed = hashlib.sha256(content).hexdigest()
        require(observed == artifact["sha256"], "artifact_digest_mismatch")
        observations.append(
            {
                "name": artifact_name,
                "sha256": observed,
                "status": "locally_observed",
                "head_sha": claim["head_sha"],
                "run_id": run_id,
                "run_attempt": attempt,
                "job_id": job_id,
                "artifact_id": artifact_id,
            }
        )
    require(set(artifacts) == {item["name"] for item in observations}, "unexpected_artifact_input")
    return {
        "schema_version": 1,
        "status": SUPPLIED,
        "execution_authority": False,
        "task_sha256": task["task_sha256"],
        "receipt_sha256": receipt_sha256(claim),
        "evidence_sha256": digest(supplied),
        "all_required_checks_claimed_passed": all_passed,
        "comparison": {
            "status": "locally_observed",
            "task_binding": "matched",
            "supplied_scope": "matched",
            "supplied_check_provenance": "matched",
            "checks": check_observations,
            "artifacts": observations,
        },
    }
