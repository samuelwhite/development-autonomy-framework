"""Durable fake developer and independent-validator outputs; never calls Codex or GitHub."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from .contract import canonical, digest, require


class FixtureAdapter:
    fixture = True
    idempotent = True

    def __init__(self, database: Path, scenario: dict[str, list[str]]):
        self.scenario = scenario
        self.db = sqlite3.connect(database)
        try:
            self._initialize()
        except BaseException:
            self.db.close()
            raise

    def _initialize(self) -> None:
        self.db.execute("CREATE TABLE IF NOT EXISTS configuration(hash TEXT PRIMARY KEY)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS external_jobs("
            "id TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT NOT NULL)"
        )
        saved = self.db.execute("SELECT hash FROM configuration").fetchone()
        require(
            saved is None or saved[0] == digest(self.scenario), "fixture_scenario_changed_on_resume"
        )
        if saved is None:
            self.db.execute("INSERT INTO configuration VALUES (?)", (digest(self.scenario),))
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def ensure(self, request: dict[str, Any]) -> None:
        existing = self.db.execute(
            "SELECT request FROM external_jobs WHERE id=?", (request["job_id"],)
        ).fetchone()
        if existing:
            require(existing[0] == canonical(request), "external_job_identity_conflict")
            return
        options = self.scenario.get(request["milestone"]["id"], [])
        require(bool(options), "fixture_milestone_missing")
        outcome = options[min(request["attempt"] - 1, len(options) - 1)]
        require(
            outcome
            in {
                "success",
                "test_failure",
                "scope_deviation",
                "protected_change",
                "missing_evidence",
                "workflow_change",
                "skipped_check",
                "usage_overrun",
                "acceptance_failure",
            },
            "unknown_fixture_outcome",
        )
        revision = digest([request["job_id"], "fixture-revision"])[:40]
        # The fake developer always claims success; only the separate validation receipt decides.
        development = {
            "revision": revision,
            "claims_success": True,
            "scope_change": "requires new operating permission"
            if outcome == "scope_deviation"
            else None,
        }
        checks = {check: "success" for check in request["validation"]["required_checks"]}
        acceptance = {name: True for name in request["milestone"]["acceptance"]}
        review = {
            "source": "fixture",
            "validator": request["validation"]["validator"],
            "job_id": request["job_id"],
            "request_sha256": digest(request),
            "plan_sha256": request["plan_sha256"],
            "revision": revision,
            "changed_files": ["src/fixture.py"],
            "workflow_sha256": request["validation"]["workflow_sha256"],
            "protected_files": request["validation"]["protected_files"],
            "checks": checks,
            "failure_details": {},
            "acceptance": acceptance,
            "usage": {"cost_units": 1, "tokens": 100},
        }
        if outcome == "test_failure":
            checks["tests"] = "failure"
            review["failure_details"] = {
                "tests": "test_fixture_transform_preserves_count: expected 3 records; observed 2"
            }
        elif outcome == "protected_change":
            review["changed_files"] = ["tests/acceptance.py"]
        elif outcome == "workflow_change":
            review["workflow_sha256"] = "0" * 64
        elif outcome == "missing_evidence":
            del checks["security"]
        elif outcome == "skipped_check":
            checks["tests"] = "skipped"
        elif outcome == "usage_overrun":
            review["usage"] = {"cost_units": request["limits"]["cost_units"] + 1, "tokens": 100}
        elif outcome == "acceptance_failure":
            acceptance[next(iter(acceptance))] = False
        with self.db:
            self.db.execute(
                "INSERT INTO external_jobs VALUES (?,?,?)",
                (
                    request["job_id"],
                    canonical(request),
                    canonical({"development": development, "validation": review}),
                ),
            )

    def lookup(self, job_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT result FROM external_jobs WHERE id=?", (job_id,)).fetchone()
        return {"state": "ready", "result": json.loads(row[0])} if row else {"state": "absent"}
