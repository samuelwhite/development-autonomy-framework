"""Local SQLite execution journal and process exclusion for synthetic development."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .contract import Plan, Refused, canonical, digest, require
from .stop_control import StopControl
from .stop_transport import StoppableTransport

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans(hash TEXT PRIMARY KEY, body TEXT NOT NULL, approval TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run(id INTEGER PRIMARY KEY CHECK(id=1), plan_hash TEXT NOT NULL,
  status TEXT NOT NULL, started REAL NOT NULL, reason TEXT);
CREATE TABLE IF NOT EXISTS milestones(id TEXT PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, milestone TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  status TEXT NOT NULL, request TEXT NOT NULL, result TEXT, polls INTEGER NOT NULL DEFAULT 0,
  UNIQUE(milestone,attempt));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(event_id INTEGER PRIMARY KEY REFERENCES events(id),
  body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations(hash TEXT PRIMARY KEY, body TEXT NOT NULL);
"""


class Store:
    def __init__(self, directory: Path, *, timeout: float = 5):
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.stop = StopControl(directory)
        self._exclusive_depth = 0
        self.db = sqlite3.connect(
            directory / "journal.sqlite", isolation_level=None, timeout=timeout
        )
        try:
            self._initialize()
        except BaseException:
            self.db.close()
            raise

    def _initialize(self) -> None:
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)
        for table in ("plans", "events", "observations"):
            for action in ("UPDATE", "DELETE"):
                self.db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_{action.lower()} "
                    f"BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'immutable_audit_record'); END"
                )

    def close(self) -> None:
        self.db.close()

    def fenced_transport(self, transport: Any) -> Any:
        """Wrap an existing reviewed transport; this does not create a network client."""
        if isinstance(transport, StoppableTransport) and transport.control.path == self.stop.path:
            return transport
        return StoppableTransport(self.stop, transport)

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        # Nested components share this connection/thread; other Store instances still contend.
        if self._exclusive_depth:
            self._exclusive_depth += 1
            try:
                yield
            finally:
                self._exclusive_depth -= 1
            return
        # Separate lock database permits intent commits while holding process-wide exclusion.
        lock = sqlite3.connect(
            self.directory / "controller-lock.sqlite", isolation_level=None, timeout=0
        )
        try:
            try:
                lock.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                raise Refused("controller_busy") from error
            self._exclusive_depth = 1
            yield
        finally:
            self._exclusive_depth = 0
            lock.close()  # OS releases the lock after process death too.

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def event(self, kind: str, payload: dict[str, Any], notify: bool = False) -> None:
        body = canonical(payload)
        cursor = self.db.execute("INSERT INTO events(kind,body) VALUES (?,?)", (kind, body))
        if notify:
            self.db.execute(
                "INSERT INTO notifications VALUES (?,?)",
                (cursor.lastrowid, canonical({"kind": kind, **payload})),
            )

    @contextmanager
    def admission_transaction(self) -> Iterator[None]:
        # Acquire the possibly busy execution journal BEFORE the short stop fence.
        # Commit reservation/dispatch under the fence, so stop and admission have
        # one order even though their durable records live in separate databases.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            with self.stop.fence():
                yield
                self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def record_token_usage(self, request: dict[str, Any], tokens: int) -> None:
        """Check reported gross usage and append at most one warning per job.

        Called after the worker returns and again at independent acceptance.
        This is not a mid-invocation cutoff. Full ceilings are reserved beforehand.
        """
        ceiling = request["limits"]["tokens"]
        normal = request["limits"].get("normal_tokens", ceiling)
        require(type(tokens) is int and 0 <= tokens <= ceiling, "usage_exceeds_reservation")
        if tokens <= normal:
            return
        payload = {
            "job_id": request["job_id"],
            "plan_sha256": request["plan_sha256"],
            "milestone": request["milestone"]["id"],
            "attempt": request["attempt"],
            "normal_tokens": normal,
            "maximum_tokens": ceiling,
            "gross_tokens": tokens,
            "overage_tokens": tokens - normal,
        }
        with self.transaction():
            prior = [
                json.loads(row[0])
                for row in self.db.execute("SELECT body FROM events WHERE kind='budget_warning'")
                if json.loads(row[0])["job_id"] == request["job_id"]
            ]
            if prior:
                require(prior == [payload], "budget_usage_record_conflict")
            else:
                self.event("budget_warning", payload, notify=True)

    def register(self, plan: Plan) -> None:
        existing = self.db.execute(
            "SELECT * FROM plans WHERE hash=?", (plan.fingerprint,)
        ).fetchone()
        if existing:
            require(
                existing["body"] == plan.body and existing["approval"] == plan.approval,
                "approval_record_conflict",
            )
            return
        data = plan.data
        for row in self.db.execute("SELECT body FROM plans"):
            recorded = json.loads(row["body"])
            require(
                (recorded["project"], recorded["plan_id"], recorded["version"])
                != (data["project"], data["plan_id"], data["version"]),
                "conflicting_plan_version",
            )
        previous = data["supersedes"]
        if previous:
            row = self.db.execute("SELECT body FROM plans WHERE hash=?", (previous,)).fetchone()
            require(row is not None, "missing_prior_plan")
            old = json.loads(row["body"])
            require(
                (old["project"], old["plan_id"], old["repository"])
                == (data["project"], data["plan_id"], data["repository"])
                and data["version"] == old["version"] + 1,
                "invalid_amendment",
            )
        else:
            require(data["version"] == 1, "initial_plan_version_required")
        self.db.execute(
            "INSERT INTO plans VALUES (?,?,?)", (plan.fingerprint, plan.body, plan.approval)
        )
        self.event(
            "plan_approved" if previous is None else "amendment_recorded",
            {"plan_sha256": plan.fingerprint, "supersedes": previous, "fixture": plan.fixture},
        )

    def initialize(self, plan: Plan, now: float) -> None:
        with self.transaction():
            self.register(plan)
            row = self.db.execute("SELECT plan_hash FROM run").fetchone()
            if row:
                require(row["plan_hash"] == plan.fingerprint, "active_plan_cannot_be_rewritten")
                return
            self.db.execute(
                "INSERT INTO run VALUES (1,?,'running',?,NULL)", (plan.fingerprint, now)
            )
            self.db.executemany(
                "INSERT INTO milestones VALUES (?,'pending')",
                [(m["id"],) for m in plan.data["milestones"]],
            )

    def record_amendment(self, plan: Plan) -> None:
        # Record only. Existing execution and completion history remain pinned to their plan.
        require(plan.data["supersedes"] is not None, "amendment_requires_parent")
        with self.exclusive(), self.transaction():
            self.register(plan)

    def observe(self, evidence: dict[str, Any]) -> str:
        fingerprint = digest(evidence)
        with self.transaction():
            self.db.execute(
                "INSERT OR IGNORE INTO observations VALUES (?,?)",
                (fingerprint, canonical(evidence)),
            )
        return fingerprint

    def summary(self) -> dict[str, Any]:
        run = self.db.execute("SELECT * FROM run").fetchone()
        summary = {
            "stop_control": self.stop.snapshot(),
            "run": dict(run) if run else None,
            "milestones": [
                dict(r) for r in self.db.execute("SELECT * FROM milestones ORDER BY rowid")
            ],
            "jobs": [
                dict(r)
                for r in self.db.execute(
                    "SELECT id,milestone,attempt,status,polls FROM jobs ORDER BY rowid"
                )
            ],
            "notifications": [
                {"event_id": r["event_id"], **json.loads(r["body"])}
                for r in self.db.execute("SELECT * FROM notifications ORDER BY event_id")
            ],
        }
        if self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='live_jobs'"
        ).fetchone():
            fields = ("id", "phase", "revision", "run_id", "session_id", "tokens")
            summary["executions"] = [
                {field: body[field] for field in fields if field in body}
                for row in self.db.execute("SELECT body FROM live_jobs ORDER BY rowid")
                for body in [json.loads(row[0])]
            ]
        return summary
