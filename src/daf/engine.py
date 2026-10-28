"""Synthetic progression only; no worker or production adapter is distributed."""

import json
import time
from collections.abc import Callable
from typing import Any, Protocol

from .contract import (
    Plan,
    Refused,
    canonical,
    digest,
    keys,
    relative_path,
    require,
    sha,
    token_reservation,
)
from .fixtures import FixtureAdapter
from .operations import stop_requested, sync_stop
from .store import Store


class Adapter(Protocol):
    fixture: bool
    idempotent: bool

    def ensure(self, request: dict[str, Any]) -> None: ...

    def lookup(self, job_id: str) -> dict[str, Any]: ...


class Engine:
    def __init__(
        self, store: Store, plan: Plan, adapter: Adapter, clock: Callable[[], float] = time.time
    ):
        require(type(adapter) is FixtureAdapter and plan.fixture, "fixture_adapter_required")
        require(Plan.load(plan.data, json.loads(plan.approval)) == plan, "plan_changed")
        self.store, self.plan, self.adapter, self.clock = store, plan, adapter, clock
        self.policy = plan.data

    def exception(self, reason: str, job_id: str | None = None) -> None:
        with self.store.transaction():
            self.store.db.execute("UPDATE run SET status='needs_decision',reason=?", (reason,))
            self.store.event("exception", {"reason": reason, "job_id": job_id}, notify=True)
            self.final_notification(reason)

    def final_notification(self, reason: str) -> None:
        if self.policy["schema_version"] == 5:
            completed = self.store.db.execute(
                "SELECT COUNT(*) FROM milestones WHERE status='completed'"
            ).fetchone()[0]
            jobs = self.store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            self.store.event(
                "run_summary",
                {
                    "plan_sha256": self.plan.fingerprint,
                    "completed": completed,
                    "jobs": jobs,
                    "reason": reason,
                    "fixture": self.plan.fixture,
                },
                notify=True,
            )

    def advance(self, max_steps: int = 100) -> dict[str, Any]:
        require(
            type(self.adapter) is FixtureAdapter and self.plan.fixture, "fixture_adapter_required"
        )
        require(
            Plan.load(self.plan.data, json.loads(self.plan.approval)) == self.plan, "plan_changed"
        )
        require(self.policy == self.plan.data, "plan_changed")
        require(type(max_steps) is int and 0 < max_steps <= 1000, "invalid_step_limit")
        with self.store.exclusive():
            self.store.stop.recover()
            self.store.initialize(self.plan, self.clock())
            for _ in range(max_steps):
                run = self.store.db.execute("SELECT * FROM run").fetchone()
                if run["status"] != "running":
                    break
                if stop_requested(self.store):
                    self.pause()
                    break
                elapsed = self.clock() - run["started"]
                if not 0 <= elapsed < self.policy["budgets"]["max_elapsed_seconds"]:
                    self.exception("elapsed_budget_or_clock")
                    cancel = getattr(self.adapter, "cancel", None)
                    if cancel:
                        try:
                            cancel()
                        except (Refused, OSError, ValueError):
                            with self.store.transaction():
                                self.store.event("cancellation_unconfirmed", {}, notify=True)
                    break
                try:
                    progressed = self.tick()
                    if self.store.stop.requested():
                        self.pause()
                        break
                    if not progressed:
                        break
                except Refused as error:
                    if self.store.stop.requested():
                        self.pause()
                    else:
                        self.exception(str(error))
                    break
                except (KeyError, TypeError, ValueError):
                    self.exception("malformed_adapter_evidence")
                    break
        return self.store.summary()

    def pause(self) -> None:
        sync_stop(self.store)
        # No unbounded cancel callback here. Local supervised commands observe
        # the stop channel directly. Remote work is left for reconciliation.
        pending = bool(
            self.store.db.execute("SELECT 1 FROM jobs WHERE status='dispatching'").fetchone()
        )
        epoch = self.store.stop.snapshot()["epoch"]
        try:
            state = self.store.stop.acknowledge(epoch, pending=pending)
        except Refused:
            return  # A newer stop wins; the next observation acknowledges it.
        with self.store.transaction():
            self.store.db.execute("UPDATE run SET status='paused',reason='operator_stop'")
            self.store.event("controller_paused", state, notify=True)

    def tick(self) -> bool:
        job = self.store.db.execute(
            "SELECT * FROM jobs WHERE status IN ('prepared','dispatching') ORDER BY rowid LIMIT 1"
        ).fetchone()
        if job:
            request = json.loads(job["request"])
            if job["status"] == "prepared":
                with self.store.admission_transaction():
                    self.store.db.execute(
                        "UPDATE jobs SET status='dispatching' WHERE id=?", (job["id"],)
                    )
                    self.store.event(
                        "dispatch_intent",
                        {"job_id": job["id"], "fixture": self.plan.fixture},
                        notify=True,
                    )
                # Intent is durable before the adapter side effect. Never use a fresh ID on retry.
                with self.store.stop.adapter_boundary("adapter_ensure"):
                    self.adapter.ensure(request)
                return True
            with self.store.stop.adapter_boundary("adapter_lookup"):
                observation = self.adapter.lookup(job["id"])
            if observation.get("state") == "pending":
                return False
            if observation.get("state") == "absent" and self.adapter.idempotent:
                with self.store.stop.adapter_boundary("adapter_reconcile"):
                    self.adapter.ensure(request)
                return True
            if observation.get("state") != "ready":
                with self.store.transaction():
                    self.store.db.execute("UPDATE jobs SET polls=polls+1 WHERE id=?", (job["id"],))
                    self.store.event("recovery_wait", {"job_id": job["id"]})
                if job["polls"] + 1 >= self.policy["recovery"]["max_uncertain_polls"]:
                    self.exception("external_job_outcome_unknown", job["id"])
                return False
            self.store.observe(
                {
                    "source": "fixture-validation" if self.plan.fixture else "live-validation",
                    "job_id": job["id"],
                    "receipt_sha256": digest(observation["result"]),
                }
            )
            self.complete_job(dict(job), observation["result"])
            return True
        self.next_job()
        return True

    def next_job(self) -> None:
        states = {
            row["id"]: row["status"] for row in self.store.db.execute("SELECT * FROM milestones")
        }
        if all(state == "completed" for state in states.values()):
            with self.store.admission_transaction():
                self.store.db.execute("UPDATE run SET status='completed'")
                self.store.event(
                    "project_completed",
                    {"plan_sha256": self.plan.fingerprint, "fixture": self.plan.fixture},
                    notify=True,
                )
                self.final_notification("completed")
            return
        milestone = next(
            (
                m
                for m in self.policy["milestones"]
                if states[m["id"]] == "pending"
                and all(states[d] == "completed" for d in m["depends_on"])
            ),
            None,
        )
        if milestone is None:
            raise Refused("no_eligible_milestone")
        prior = self.store.db.execute(
            "SELECT * FROM jobs WHERE milestone=? ORDER BY attempt DESC LIMIT 1", (milestone["id"],)
        ).fetchone()
        attempt = prior["attempt"] + 1 if prior else 1
        require(attempt <= self.policy["recovery"]["max_attempts"], "retry_budget_exhausted")
        count = self.store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] + 1
        budget = self.policy["budgets"]
        require(
            count <= budget["max_jobs"]
            and count * budget["cost_units_per_job"] <= budget["max_cost_units"]
            and count * token_reservation(budget) <= budget["max_tokens"],
            "resource_budget_exhausted",
        )
        previous_success = self.store.db.execute(
            "SELECT result FROM jobs WHERE status='completed' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        base = (
            json.loads(previous_success["result"])["development"]["revision"]
            if previous_success
            else self.policy["baseline_revision"]
        )
        if prior:
            base = json.loads(prior["result"])["development"]["revision"]
        diagnostics = json.loads(prior["result"])["diagnostics"] if prior else []
        request = {
            "job_id": digest([self.plan.fingerprint, milestone["id"], attempt]),
            "plan_sha256": self.plan.fingerprint,
            "repository": self.policy["repository"],
            "milestone": milestone,
            "attempt": attempt,
            "base_revision": base,
            "scope": self.policy["scope"],
            "boundaries": self.policy["boundaries"],
            "validation": self.policy["validation"],
            "diagnostics": diagnostics,
            "limits": {
                "cost_units": budget["cost_units_per_job"],
                "tokens": token_reservation(budget),
                **(
                    {"normal_tokens": budget["tokens_per_job"]}
                    if budget.get("token_grace_percent")
                    else {}
                ),
            },
        }
        if not self.plan.fixture or self.policy["schema_version"] == 5:
            started = self.store.db.execute("SELECT started FROM run").fetchone()[0]
            request["deadline"] = started + budget["max_elapsed_seconds"]
        prepare_worker = getattr(self.adapter, "prepare_worker", None)
        if prepare_worker is not None:
            # Prerequisite admission precedes the durable model-budget reservation.
            with self.store.stop.adapter_boundary("prepare_worker"):
                prepare_worker(request)
        with self.store.admission_transaction():
            self.store.db.execute(
                "INSERT INTO jobs(id,milestone,attempt,status,request) VALUES (?,?,?,'prepared',?)",
                (request["job_id"], milestone["id"], attempt, canonical(request)),
            )
            self.store.event(
                "job_prepared",
                {
                    "job_id": request["job_id"],
                    "milestone": milestone["id"],
                    "attempt": attempt,
                    "reserved": request["limits"],
                },
            )

    def complete_job(self, job: dict[str, Any], raw: Any) -> None:
        result = keys(raw, {"development", "validation"})
        development = keys(result["development"], {"revision", "claims_success", "scope_change"})
        sha(development["revision"], 40)
        require(development["scope_change"] is None, "scope_or_permission_change")
        review = keys(
            result["validation"],
            {
                "source",
                "validator",
                "job_id",
                "request_sha256",
                "plan_sha256",
                "revision",
                "changed_files",
                "workflow_sha256",
                "protected_files",
                "checks",
                "failure_details",
                "acceptance",
                "usage",
            },
        )
        request = json.loads(job["request"])
        require(
            review["source"] == ("fixture" if self.plan.fixture else "github-actions")
            and review["validator"] == self.policy["validation"]["validator"]
            and review["job_id"] == job["id"]
            and review["request_sha256"] == digest(request)
            and review["plan_sha256"] == self.plan.fingerprint
            and review["revision"] == development["revision"],
            "independent_evidence_binding_mismatch",
        )
        require(
            review["workflow_sha256"] == self.policy["validation"]["workflow_sha256"],
            "required_workflow_changed",
        )
        protected = self.policy["validation"]["protected_files"]
        require(review["protected_files"] == protected, "protected_check_or_test_changed")
        require(
            isinstance(review["changed_files"], list) and bool(review["changed_files"]),
            "missing_change_evidence",
        )
        boundaries = self.policy["boundaries"]
        for file in review["changed_files"]:
            path = relative_path(file)
            require(
                path not in protected
                and not any(path.startswith(p) for p in boundaries["protected_prefixes"]),
                "protected_check_or_test_changed",
            )
            require(
                any(path.startswith(p) for p in boundaries["code_prefixes"]),
                "code_boundary_exceeded",
            )
        checks = keys(review["checks"], set(self.policy["validation"]["required_checks"]))
        require(
            all(v in {"success", "failure"} for v in checks.values()), "required_check_not_executed"
        )
        acceptance = keys(review["acceptance"], set(request["milestone"]["acceptance"]))
        require(all(type(v) is bool for v in acceptance.values()), "invalid_acceptance_evidence")
        usage = keys(review["usage"], {"cost_units", "tokens"})
        require(
            all(type(v) is int and 0 <= v <= request["limits"][k] for k, v in usage.items()),
            "usage_exceeds_reservation",
        )
        self.store.record_token_usage(request, usage["tokens"])
        failed_checks = {name for name, value in checks.items() if value != "success"}
        details = keys(review["failure_details"], failed_checks)
        require(
            all(isinstance(v, str) and 0 < len(v) <= 500 for v in details.values()),
            "missing_actionable_failure_details",
        )
        diagnostics = [
            f"Required check failed: {name}: {details[name]}" for name in sorted(failed_checks)
        ]
        diagnostics += [
            f"Acceptance failed: {name}" for name, value in acceptance.items() if not value
        ]
        result["diagnostics"] = diagnostics
        success = not diagnostics
        with self.store.admission_transaction():
            self.store.db.execute(
                "UPDATE jobs SET status=?,result=? WHERE id=?",
                ("completed" if success else "failed", canonical(result), job["id"]),
            )
            self.store.event(
                "validation_passed" if success else "correction_required",
                {
                    "job_id": job["id"],
                    "revision": development["revision"],
                    "diagnostics": diagnostics,
                },
            )
            if success:
                # An authorised action still needs a supported adapter and independent verification.
                if any(self.policy["actions"].values()):
                    self.store.db.execute(
                        "UPDATE run SET status='needs_decision',"
                        "reason='authorized_action_adapter_unavailable'"
                    )
                    self.store.event(
                        "exception",
                        {"reason": "authorized_action_adapter_unavailable", "job_id": job["id"]},
                        notify=True,
                    )
                    return
                self.store.db.execute(
                    "UPDATE milestones SET status='completed' WHERE id=?", (job["milestone"],)
                )
                if job["attempt"] > 1:
                    self.store.event(
                        "automatic_recovery",
                        {"milestone": job["milestone"], "attempts": job["attempt"]},
                        notify=True,
                    )
                self.store.event(
                    "milestone_completed",
                    {
                        "milestone": job["milestone"],
                        "revision": development["revision"],
                        "fixture": self.plan.fixture,
                    },
                    notify=True,
                )
