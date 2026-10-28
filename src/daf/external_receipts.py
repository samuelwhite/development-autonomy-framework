"""Offline, non-authoritative external execution receipts.

This module deliberately does not invoke Codex, GitHub, CI, or a model. It
validates the *shape* of untrusted, externally supplied evidence, not its
authenticity. The plan fingerprint is supplied by an operator and is never
execution authority. External proofs require a separately reviewed verifier.
"""

import hashlib
import json
import re
from typing import Any

from .contract import canonical, require

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_.-]{1,120}\Z")
_URL = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:pull|actions/runs)/[1-9][0-9]*\Z"
)


def _nonempty(value: Any, limit: int = 500) -> str:
    require(
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and value.isprintable()
        and len(value) <= limit,
        "invalid_receipt_field",
    )
    return value


def validate_repository(value: Any) -> str:
    """Accept a portable GitHub owner/repository identifier, never dot segments."""
    require(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value) is not None
        and value.split("/")[1] not in {".", ".."},
        "invalid_receipt_repository",
    )
    return value


def validate_external_receipt(value: Any) -> dict[str, Any]:
    """Schema-1 unverified receipt, with exact revision/attempt binding.

    Never changes DAF journal state or upgrades evidence to verified status.
    """
    require(
        isinstance(value, dict)
        and set(value)
        == {
            "schema_version",
            "plan_sha256",
            "milestone_id",
            "attempt_id",
            "repository",
            "baseline_sha",
            "head_sha",
            "task_sha256",
            "execution",
            "checks",
            "pr_url",
            "status",
        },
        "invalid_receipt_fields",
    )
    require(
        type(value["schema_version"]) is int and value["schema_version"] == 1,
        "invalid_receipt_schema",
    )
    for key in ("plan_sha256", "task_sha256"):
        require(
            isinstance(value[key], str) and _SHA64.fullmatch(value[key]) is not None,
            "invalid_receipt_digest",
        )
    for key in ("baseline_sha", "head_sha"):
        require(
            isinstance(value[key], str) and _SHA40.fullmatch(value[key]) is not None,
            "invalid_receipt_revision",
        )
    for key in ("milestone_id", "attempt_id"):
        require(
            isinstance(value[key], str) and _ID.fullmatch(value[key]) is not None,
            "invalid_receipt_identity",
        )
    validate_repository(value["repository"])
    require(
        value["status"] == "externally_supplied_unverified", "external_evidence_cannot_self_verify"
    )
    require(
        isinstance(value["execution"], str)
        and value["execution"] in {"supervised_codex", "manual", "ci_only"},
        "unsupported_execution_mode",
    )
    require(
        value["pr_url"] is None
        or (isinstance(value["pr_url"], str) and _URL.fullmatch(value["pr_url"]) is not None),
        "invalid_receipt_link",
    )
    if value["pr_url"] is not None:
        require(
            value["pr_url"].startswith("https://github.com/" + value["repository"] + "/pull/"),
            "receipt_repository_mismatch",
        )
    checks = value["checks"]
    require(isinstance(checks, list) and len(checks) <= 32, "invalid_receipt_checks")
    ids: set[str] = set()
    for check in checks:
        require(
            isinstance(check, dict) and set(check) == {"name", "head_sha", "result", "url"},
            "invalid_receipt_check_fields",
        )
        name = _nonempty(check["name"], 120)
        require(name not in ids, "duplicate_receipt_check")
        ids.add(name)
        require(check["head_sha"] == value["head_sha"], "receipt_revision_mismatch")
        require(
            isinstance(check["result"], str)
            and check["result"] in {"passed", "failed", "pending", "unknown"},
            "invalid_receipt_check_result",
        )
        require(
            isinstance(check["url"], str) and _URL.fullmatch(check["url"]) is not None,
            "invalid_receipt_link",
        )
        expected_prefix = "https://github.com/" + value["repository"] + "/actions/runs/"
        require(check["url"].startswith(expected_prefix), "receipt_repository_mismatch")
    return json.loads(canonical(value))


def receipt_sha256(receipt: dict[str, Any]) -> str:
    """Stable fingerprint of the supplied claim, not proof of its truth."""
    return hashlib.sha256(canonical(validate_external_receipt(receipt)).encode()).hexdigest()
