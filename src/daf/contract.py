"""Synthetic plan contracts only. Fixture markers are never execution authority."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


class Refused(ValueError):
    """A fixed, safe reason code; never include input documents or credentials."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Refused(reason)


def keys(value: Any, expected: set[str]) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == expected, "invalid_contract_fields")
    return dict(value)


def strings(value: Any) -> list[str]:
    require(
        isinstance(value, list)
        and bool(value)
        and all(isinstance(s, str) and 0 < len(s) <= 1000 for s in value)
        and len(set(value)) == len(value),
        "invalid_string_list",
    )
    return list(value)


def integer(value: Any, minimum: int = 1) -> int:
    require(type(value) is int and minimum <= value <= 10**9, "invalid_budget_or_version")
    return int(value)


def sha(value: Any, length: int = 64) -> str:
    require(
        isinstance(value, str) and re.fullmatch(f"[a-f0-9]{{{length}}}", value) is not None,
        "invalid_digest",
    )
    return str(value)


def token_reservation(budgets: dict[str, Any]) -> int:
    """Inclusive per-job ceiling; absent grace never changes an older plan."""
    normal = int(budgets["tokens_per_job"])
    return normal + normal * int(budgets.get("token_grace_percent", 0)) // 100


def relative_path(value: Any) -> str:
    require(isinstance(value, str) and bool(value), "invalid_path")
    path = PurePosixPath(value)
    require(
        not path.is_absolute()
        and not any(p in {"", ".", ".."} for p in value.rstrip("/").split("/"))
        and "\\" not in value
        and ":" not in value
        and "\x00" not in value,
        "invalid_path",
    )
    return str(value)


def read_json(path: Path) -> Any:
    require(path.stat().st_size <= 2 * 1024 * 1024, "document_too_large")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


@dataclass(frozen=True)
class Plan:
    body: str
    approval: str
    fingerprint: str

    @property
    def data(self) -> dict[str, Any]:
        # Return a new value: adapters cannot mutate the pinned authority in memory.
        return dict(json.loads(self.body))

    @property
    def fixture(self) -> bool:
        return bool(json.loads(self.approval)["mode"] == "fixture")

    @classmethod
    def validate_data(cls, data: Any) -> dict[str, Any]:
        """Validate a candidate without constructing authority or an approval receipt."""
        plan = keys(
            data,
            {
                "schema_version",
                "project",
                "repository",
                "plan_id",
                "version",
                "supersedes",
                "baseline_revision",
                "scope",
                "deliverables",
                "boundaries",
                "validation",
                "budgets",
                "recovery",
                "notifications",
                "actions",
                "milestones",
            },
        )
        require(
            type(plan["schema_version"]) is int and plan["schema_version"] == 1,
            "unsupported_plan_schema",
        )
        for field in ("project", "plan_id"):
            require(
                isinstance(plan[field], str)
                and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", plan[field]) is not None,
                "invalid_identity",
            )
        require(
            isinstance(plan["repository"], str)
            and re.fullmatch(r"[\w.-]+/[\w.-]+", plan["repository"]) is not None,
            "invalid_repository",
        )
        integer(plan["version"])
        sha(plan["baseline_revision"], 40)
        if plan["supersedes"] is not None:
            sha(plan["supersedes"])
        strings(plan["scope"])
        strings(plan["deliverables"])
        boundaries = keys(
            plan["boundaries"],
            {
                "code_prefixes",
                "protected_prefixes",
                "infrastructure",
                "deployment_targets",
                "security_restrictions",
            },
        )
        for field in ("code_prefixes", "protected_prefixes"):
            for path in strings(boundaries[field]):
                relative_path(path)
                require(path.endswith("/"), "prefix_requires_directory")
        strings(boundaries["security_restrictions"])
        for field in ("infrastructure", "deployment_targets"):
            require(
                isinstance(boundaries[field], list)
                and all(isinstance(x, str) for x in boundaries[field]),
                "invalid_boundary",
            )
        validation = keys(
            plan["validation"],
            {
                "validator",
                "required_checks",
                "workflow_path",
                "workflow_sha256",
                "protected_files",
            },
        )
        strings([validation["validator"]])
        require(
            set(strings(validation["required_checks"])) >= {"tests", "security"},
            "missing_required_checks",
        )
        relative_path(validation["workflow_path"])
        sha(validation["workflow_sha256"])
        protected = validation["protected_files"]
        require(
            isinstance(protected, dict) and len(protected) >= 2,
            "missing_acceptance_file_protection",
        )
        for path, fingerprint in protected.items():
            relative_path(path)
            sha(fingerprint)
        require(
            protected.get(validation["workflow_path"]) == validation["workflow_sha256"],
            "required_workflow_not_protected",
        )
        budgets = keys(
            plan["budgets"],
            {
                "max_jobs",
                "max_cost_units",
                "cost_units_per_job",
                "max_tokens",
                "tokens_per_job",
                "max_elapsed_seconds",
            },
        )
        for name, value in budgets.items():
            if name == "token_grace_percent":
                require(type(value) is int and value in {0, 10}, "invalid_token_grace")
            else:
                integer(value)
        require(token_reservation(budgets) <= budgets["max_tokens"], "reservation_exceeds_budget")
        for key in ("cost_units", "tokens"):
            require(
                budgets[f"{key}_per_job"] <= budgets[f"max_{key}"], "reservation_exceeds_budget"
            )
        recovery = keys(plan["recovery"], {"max_attempts", "max_uncertain_polls"})
        for value in recovery.values():
            integer(value)
        require(plan["notifications"] == "durable-outbox", "unsupported_notifications")
        actions = keys(plan["actions"], {"merge", "deploy"})
        require(all(x is False for x in actions.values()), "live_actions_unavailable")
        seen: set[str] = set()
        require(
            isinstance(plan["milestones"], list) and 0 < len(plan["milestones"]) <= 100,
            "invalid_milestones",
        )
        for raw in plan["milestones"]:
            milestone = keys(raw, {"id", "depends_on", "deliverable", "acceptance"})
            identity = milestone["id"]
            require(
                isinstance(identity, str)
                and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", identity) is not None
                and identity not in seen,
                "invalid_milestone_identity",
            )
            dependencies = milestone["depends_on"]
            require(
                isinstance(dependencies, list)
                and all(isinstance(d, str) and d in seen for d in dependencies)
                and len(set(dependencies)) == len(dependencies),
                "dependency_must_precede_milestone",
            )
            strings([milestone["deliverable"]])
            criteria = milestone["acceptance"]
            require(isinstance(criteria, dict) and bool(criteria), "missing_acceptance")
            strings(list(criteria))
            for description in criteria.values():
                strings([description])
            seen.add(identity)
        return plan

    @classmethod
    def load(cls, data: Any, receipt: Any) -> "Plan":
        plan = cls.validate_data(data)
        approval = keys(
            receipt,
            {"schema_version", "plan_sha256", "authority", "record_ref", "approved_at", "mode"},
        )
        require(
            type(approval["schema_version"]) is int
            and approval["schema_version"] == 1
            and approval["mode"] == "fixture",
            "invalid_approval",
        )
        for field in ("authority", "record_ref", "approved_at"):
            strings([approval[field]])
        fingerprint = digest(plan)
        require(sha(approval["plan_sha256"]) == fingerprint, "approval_digest_mismatch")
        return cls(canonical(plan), canonical(approval), fingerprint)
