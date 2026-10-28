"""Synthetic-only walkthrough and immutable, offline Mission Control snapshot."""

import base64
import hashlib
import json
from pathlib import Path

from .bounded_demo import demonstration
from .contract import Plan, read_json, require
from .engine import Engine
from .fixtures import FixtureAdapter
from .operations import request_stop
from .store import Store

RESOURCES = Path(__file__).parent


def example_plan():
    return Plan.load(
        read_json(RESOURCES / "examples/plan.json"),
        read_json(RESOURCES / "examples/approval.json"),
    )


def progress(directory, scenario, steps=100, stopped=False):
    store = Store(directory)
    adapter = FixtureAdapter(directory / "fixture-provider.sqlite", scenario)
    try:
        engine = Engine(store, example_plan(), adapter, clock=lambda: 100.0)
        if stopped:
            store.initialize(example_plan(), 100.0)
            request_stop(store)
        result = engine.advance(steps)
        result["budget"] = example_plan().data["budgets"]
        result["tasks"] = example_plan().data["milestones"]
        result["attempts"] = []
        for row in store.db.execute("SELECT * FROM jobs ORDER BY rowid"):
            request = json.loads(row["request"])
            evidence = json.loads(row["result"]) if row["result"] else {}
            validation = evidence.get("validation", {})
            result["attempts"].append(
                {
                    "milestone": row["milestone"],
                    "attempt": row["attempt"],
                    "status": row["status"],
                    "checks": validation.get("checks", {}),
                    "actual_tokens": validation.get("usage", {}).get("tokens"),
                    "reserved_tokens": request["limits"]["tokens"],
                    "criteria": validation.get("acceptance", {}),
                }
            )
        # A failed attempt stays failed even after a correction succeeds.
        result["known_actual_tokens"] = sum(a["actual_tokens"] or 0 for a in result["attempts"])
        result["actual_complete"] = all(a["actual_tokens"] is not None for a in result["attempts"])
        result["reserved_tokens"] = sum(a["reserved_tokens"] for a in result["attempts"])
        result["provider_jobs"] = adapter.db.execute(
            "SELECT COUNT(*) FROM external_jobs"
        ).fetchone()[0]
        return result
    finally:
        adapter.close()
        store.close()


def dashboard(result):
    template = (RESOURCES / "assets/index.html").read_text(encoding="utf-8")
    script = (RESOURCES / "assets/app.js").read_text(encoding="utf-8")
    style = (RESOURCES / "assets/style.css").read_text(encoding="utf-8")
    # Data is inside a script literal; escape HTML terminators and line separators.
    data = (
        json.dumps(result, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    script = "const snapshot = " + data + ";\n" + script
    script_hash = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    style_hash = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
    return (
        template.replace("SCRIPT_HASH", script_hash)
        .replace("STYLE_HASH", style_hash)
        .replace("/* STYLE */", style)
        .replace("/* SCRIPT */", script)
    )


def demonstrate(directory):
    directory = directory.absolute()
    # Refuse existing evidence, including symlinked/reparse-point parents.
    for path in (directory, *directory.parents):
        require(not path.is_symlink(), "output_link_refused")
        require(not getattr(path, "is_junction", lambda: False)(), "output_link_refused")
    require(not directory.exists(), "new_output_directory_required")
    directory.mkdir(parents=True, exist_ok=False)
    scenario = read_json(RESOURCES / "examples/recovery.json")
    progress(directory / "progression", scenario, steps=2)
    recovered = progress(directory / "progression", scenario)
    # Another reopen must preserve the exact result and number of simulated jobs.
    require(progress(directory / "progression", scenario) == recovered, "recovery_not_idempotent")
    blocked = progress(
        directory / "scope-blocker", read_json(RESOURCES / "examples/scope-exception.json")
    )
    paused = progress(directory / "stopped", scenario, stopped=True)
    bounded = demonstration(directory / "bounded")
    result = {
        "mode": "synthetic-only",
        "version": "0.1.0.dev1",
        "execution_authority": False,
        "provider_requests": 0,
        "approval_receipts_issued": 0,
        "notifications_delivered": 0,
        "progression": recovered,
        "scope_blocker": blocked,
        "stopped": paused,
        "bounded": bounded,
        "planning": "Synthetic configuration; no GitHub planning imported",
        "ci": "Fixture validation only; no external CI evidence",
        "merge": "not performed",
        "deployment": "not performed",
    }
    require(recovered["run"]["status"] == "completed", "demo_progression_failed")
    require(blocked["run"]["reason"] == "scope_or_permission_change", "demo_blocker_failed")
    require(paused["run"]["status"] == "paused" and not paused["jobs"], "demo_stop_failed")
    (directory / "demonstration.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "index.html").write_text(dashboard(result), encoding="utf-8")
    return result
