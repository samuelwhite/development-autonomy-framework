"""Operator controls persist independently of controller ticks and never reset budgets."""

import sqlite3
from pathlib import Path
from typing import Any

from .contract import Plan, require
from .stop_control import StopControl
from .store import Store


def initialize(store: Store) -> None:
    store.db.execute(
        "CREATE TABLE IF NOT EXISTS operator_control "
        "(id INTEGER PRIMARY KEY CHECK(id=1), stopped INTEGER NOT NULL)"
    )
    store.db.execute("INSERT OR IGNORE INTO operator_control VALUES (1,0)")


def stop_requested(store: Store) -> bool:
    initialize(store)
    legacy = bool(store.db.execute("SELECT stopped FROM operator_control").fetchone()[0])
    if legacy and not store.stop.requested():
        store.stop.request()
    return store.stop.requested()


def request_stop(store: Store) -> None:
    require(store.db.execute("SELECT id FROM run").fetchone() is not None, "run_not_initialized")
    store.stop.request()  # Authoritative commit does not wait for the main journal.
    sync_stop(store)


def request_stop_path(directory: Path) -> dict[str, Any]:
    require((directory / "journal.sqlite").is_file(), "run_not_initialized")
    db = sqlite3.connect((directory / "journal.sqlite").as_uri() + "?mode=ro", uri=True)
    try:
        require(db.execute("SELECT id FROM run").fetchone() is not None, "run_not_initialized")
    finally:
        db.close()
    control = StopControl(directory)
    control.request()
    return control.snapshot()


def sync_stop(store: Store) -> None:
    """Best-effort outbox projection. Failure cannot undo the authoritative stop."""
    if not store.stop.requested():
        return
    timeout = store.db.execute("PRAGMA busy_timeout").fetchone()[0]
    store.db.execute("PRAGMA busy_timeout=0")
    try:
        _sync_stop(store)
    except sqlite3.OperationalError:
        pass  # A later status/controller observation projects this durable request.
    finally:
        store.db.execute(f"PRAGMA busy_timeout={int(timeout)}")


def _sync_stop(store: Store) -> None:
    initialize(store)
    with store.transaction():
        if not store.db.execute("SELECT stopped FROM operator_control").fetchone()[0]:
            store.db.execute("UPDATE operator_control SET stopped=1")
            store.event("operator_stop_requested", {}, notify=True)


def resume(store: Store, plan: Plan, *, observed_epoch: int | None = None) -> None:
    epoch = store.stop.snapshot()["epoch"] if observed_epoch is None else observed_epoch
    initialize(store)
    with store.exclusive(), store.transaction():
        run = store.db.execute("SELECT * FROM run").fetchone()
        require(run is not None and run["plan_hash"] == plan.fingerprint, "resume_plan_mismatch")
        require(run["status"] in {"running", "paused"}, "terminal_run_cannot_resume")
        record = store.db.execute(
            "SELECT body,approval FROM plans WHERE hash=?", (plan.fingerprint,)
        ).fetchone()
        require(
            record["body"] == plan.body and record["approval"] == plan.approval,
            "resume_approval_mismatch",
        )
        with store.stop.resuming(epoch):
            was_stopped = bool(
                store.db.execute("SELECT stopped FROM operator_control").fetchone()[0]
            )
            store.db.execute("UPDATE operator_control SET stopped=0")
            store.db.execute("UPDATE run SET status='running',reason=NULL")
            if was_stopped or run["status"] == "paused":
                store.event("operator_resumed", {"plan_sha256": plan.fingerprint}, notify=True)
