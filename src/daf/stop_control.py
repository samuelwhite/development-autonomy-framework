"""Durable stop/admission ordering, independent of the controller and execution journal.

Only short SQLite transactions hold this gate. Never hold it across external work.
An admission precedes a side effect; it is not proof that the side effect completed.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .contract import canonical, require


class StopControl:
    def __init__(self, directory: Path):
        self.path = directory / "stop-control.sqlite"
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS control(
                  id INTEGER PRIMARY KEY CHECK(id=1), epoch INTEGER NOT NULL,
                  stopped INTEGER NOT NULL, acknowledged INTEGER NOT NULL);
                INSERT OR IGNORE INTO control VALUES(1,0,0,0);
                CREATE TABLE IF NOT EXISTS admissions(
                  id INTEGER PRIMARY KEY, epoch INTEGER NOT NULL,
                  kind TEXT NOT NULL, outcome TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit(
                  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS immutable_stop_update BEFORE UPDATE ON audit
                  BEGIN SELECT RAISE(ABORT, 'immutable_stop_audit'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_stop_delete BEFORE DELETE ON audit
                  BEGIN SELECT RAISE(ABORT, 'immutable_stop_audit'); END;
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, isolation_level=None, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.rollback()
                raise
            else:
                db.commit()

    @staticmethod
    def event(db: sqlite3.Connection, kind: str, body: dict[str, Any]) -> None:
        db.execute("INSERT INTO audit(kind,body) VALUES(?,?)", (kind, canonical(body)))

    def snapshot(self) -> dict[str, Any]:
        with self.connection() as db:
            db.execute("BEGIN")
            value = dict(db.execute("SELECT * FROM control").fetchone())
            value.pop("id")
            value["outstanding"] = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM admissions WHERE outcome IN ('open','unknown') ORDER BY id"
                )
            ]
            value["stopped"] = bool(value["stopped"])
            value["acknowledged"] = bool(
                value["stopped"] and value["acknowledged"] == value["epoch"]
            )
            value["state"] = "stop_requested" if value["stopped"] else "running"
            if value["acknowledged"]:
                row = db.execute(
                    "SELECT body FROM audit WHERE kind='stop_acknowledged' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                value["state"] = json.loads(row[0])["state"]
            return value

    def requested(self) -> bool:
        with self.connection() as db:
            return bool(db.execute("SELECT stopped FROM control").fetchone()[0])

    def request(self) -> int:
        with self.transaction() as db:
            db.execute("UPDATE control SET epoch=epoch+1, stopped=1")
            epoch = int(db.execute("SELECT epoch FROM control").fetchone()[0])
            self.event(db, "stop_requested", {"epoch": epoch})
            return epoch

    @contextmanager
    def fence(self) -> Iterator[sqlite3.Connection]:
        """Linearization fence for local admission commits; no network or callbacks."""
        with self.transaction() as db:
            require(not db.execute("SELECT stopped FROM control").fetchone()[0], "operator_stop")
            yield db

    def check(self) -> None:
        require(not self.requested(), "operator_stop")

    @contextmanager
    def adapter_boundary(self, kind: str) -> Iterator[None]:
        # The execution journal already owns once-only job identity and recovery.
        # A high-level adapter call may reconcile many individual operations; do
        # not mistake its interrupted stack frame for an additional paid request.
        with self.fence() as db:
            self.event(db, "adapter_admitted", {"kind": kind})
        self.check()
        yield

    @contextmanager
    def operation(self, kind: str, *, tracked_outcome: bool = True) -> Iterator[int]:
        with self.fence() as db:
            epoch = db.execute("SELECT epoch FROM control").fetchone()[0]
            cursor = db.execute(
                "INSERT INTO admissions(epoch,kind,outcome) VALUES(?,?,'open')", (epoch, kind)
            )
            identity = int(cursor.lastrowid or 0)
            self.event(db, "admitted", {"id": identity, "epoch": epoch, "kind": kind})
        try:
            # A stop between intent and invocation must not start the invocation.
            self.check()
            yield identity
        except BaseException:
            self.finish(identity, "unknown" if tracked_outcome else "returned")
            raise
        else:
            self.finish(identity, "returned")

    def finish(self, identity: int, outcome: str) -> None:
        require(outcome in {"returned", "unknown"}, "invalid_stop_outcome")
        with self.transaction() as db:
            db.execute("UPDATE admissions SET outcome=? WHERE id=?", (outcome, identity))
            self.event(db, "operation_outcome", {"id": identity, "outcome": outcome})

    def recover(self) -> None:
        """Caller holds controller exclusion. Abandoned intents never imply a safe retry."""
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM admissions WHERE outcome='open'").fetchone():
                db.execute("UPDATE admissions SET outcome='unknown' WHERE outcome='open'")
                db.execute("UPDATE control SET epoch=epoch+1, stopped=1")
                self.event(db, "in_flight_outcome_unknown", {"reason": "controller_interrupted"})

    def acknowledge(self, epoch: int, *, pending: bool) -> dict[str, Any]:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM control").fetchone()
            require(row["stopped"] and row["epoch"] == epoch, "stale_stop_observation")
            db.execute("UPDATE control SET acknowledged=?", (epoch,))
            unresolved = bool(
                db.execute(
                    "SELECT 1 FROM admissions WHERE outcome IN ('open','unknown')"
                ).fetchone()
            )
            state = "in_flight_outcome_unknown" if pending or unresolved else "safely_paused"
            self.event(db, "stop_acknowledged", {"epoch": epoch, "state": state})
            return {"epoch": epoch, "state": state}

    def cancellation(self, identity: int, *, confirmed: bool = False) -> None:
        """Local cancellation evidence only; never confirms provider spending stopped."""
        with self.transaction() as db:
            require(
                db.execute("SELECT id FROM admissions WHERE id=?", (identity,)).fetchone()
                is not None,
                "unknown_stop_admission",
            )
            self.event(
                db,
                "cancellation_confirmed" if confirmed else "cancellation_attempted",
                {"id": identity, "scope": "local_process_only", "provider_outcome": "unknown"},
            )

    @contextmanager
    def resuming(self, epoch: int) -> Iterator[None]:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM control").fetchone()
            require(row["epoch"] == epoch, "stale_stop_observation")
            require(
                not db.execute(
                    "SELECT 1 FROM admissions WHERE outcome IN ('open','unknown')"
                ).fetchone(),
                "in_flight_outcome_unknown",
            )
            yield
            db.execute("UPDATE control SET stopped=0, epoch=epoch+1")
            self.event(db, "operator_resumed", {"previous_epoch": epoch})
