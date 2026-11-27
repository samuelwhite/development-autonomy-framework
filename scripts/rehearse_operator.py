"""Preview, admit and observe two supervised pilots using disposable Git only."""

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import rehearse_code_pilot as code  # noqa: E402
import rehearse_document_pilot as docs  # noqa: E402
from document_pilot import checked_candidate, snapshot  # noqa: E402
from homeci_candidate import verify  # noqa: E402

from daf.contract import Refused, canonical, digest, require  # noqa: E402
from daf.receipt_bridge import (  # noqa: E402
    journal_directory,
    local_path,
    observation_history,
    read_document,
)
from daf.supervised_handoff import validate_bundle  # noqa: E402

TASKS = ("docs", "python")
LOSSES = ("branch", "draft", "dispatch")
NEXT = {
    "review": "Review the exact candidate and retained result.",
    "finished": "Review the failed validation and retain the original run.",
    "queued": "Observe the same journal again.",
    "running": "Observe the same journal again.",
    "blocked": "Inspect the refusal and retained identities.",
}


def preview(directory, name):
    if name == "docs":
        repo, _, _, (task, edit, review, approval) = docs.setup(directory, bind_plan=True)
        task = validate_bundle(task)
        plan = read_document(directory / "plan.json")
        checked_candidate(repo, task, edit, review, approval["candidate_sha"])
    else:
        repo, _, _, proposed, approval = code.setup(directory, "success")
        task = validate_bundle(proposed["task"])
        plan = proposed["plan"]
        require(digest(proposed) == approval["proposal_sha256"], "fixture_approval_changed")
    request = task["request"]
    base, candidate = request["baseline_sha"], approval["candidate_sha"]
    require(
        request["plan_sha256"] == digest(plan)
        and plan["baseline_sha"] == base
        and plan["repository"] == request["repository"]
        and task["task_sha256"] == approval["task_sha256"],
        "fixture_task_binding_changed",
    )
    diff = code.object_diff(repo, base, candidate)
    diff_path = local_path(directory / "candidate.diff")
    if not diff_path.exists():
        diff_path.write_bytes(diff)
    require(diff_path.read_bytes() == diff, "candidate_diff_changed")
    if name == "python":
        code.check_scope(repo, directory, base, candidate, proposed)
    return {
        "mode": "simulated",
        "execution_authority": False,
        "fixture": name,
        "plan_sha256": digest(plan),
        "task_sha256": task["task_sha256"],
        "baseline_sha": base,
        "candidate_sha": candidate,
        "path": request["allowed_paths"][0],
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "pilot_approval_sha256": digest(approval),
        "validator": approval["verification"],
    }


def observe_docs(directory, prior):
    repo, remote, journal, (task, _, _, approval) = docs.setup(directory)
    transport = docs.RehearsalTransport(repo, remote, directory / "simulated-github.json")
    result = prior.copy()
    for field in ("reason", "dispatch_identity_mismatches"):
        result.pop(field, None)
    candidates = transport.pulls(docs.DAF, prior["branch"])
    if not candidates:
        reason = (
            "draft_create_outcome_unknown"
            if transport.branch(docs.DAF, prior["branch"])
            else ("branch_publish_outcome_unknown")
        )
        result.update(state="blocked", reason=reason)
    else:
        require(candidates == [{"number": transport.pr}], "multiple_candidate_pulls")
        result["draft_pr"] = transport.pr
        observation = verify(
            task,
            {
                **approval["verification"],
                "task_sha256": task["task_sha256"],
                "candidate_sha": approval["candidate_sha"],
                "candidate_pr": transport.pr,
            },
            docs.FORGE,
            journal,
            transport.get,
        )
        result["state"] = {"terminal": "finished"}.get(observation["state"], observation["state"])
        if observation["verification"] == "passed":
            result["state"] = "review"
        for key, output in (
            ("run_id", "run_id"),
            ("attempt", "run_attempt"),
            ("job_id", "job_id"),
            ("runner", "runner"),
            ("run_conclusion", "conclusion"),
            ("reason", "reason"),
            ("dispatch_identity_mismatches", "dispatch_identity_mismatches"),
        ):
            if observation.get(key) is not None:
                result[output] = observation[key]
    return {"observation": snapshot(journal, result), "external_writes": transport.data["writes"]}


def history(journal, approval):
    with observation_history(journal / "journal.sqlite") as db:
        rows = db.execute("SELECT hash, body FROM observations ORDER BY rowid").fetchall()
    events = []
    for fingerprint, body in rows:
        event = json.loads(body)
        require(
            digest(event) == fingerprint and event.get("task_sha256") == approval["task_sha256"],
            "history_binding_changed",
        )
        if "candidate_sha" in event:
            require(event["candidate_sha"] == approval["candidate_sha"], "history_binding_changed")
        events.append(event)
    return events


def exercise(directory, name, mode, supplied, loss=None, scenario="success"):
    directory = local_path(directory)
    directory.mkdir(exist_ok=True)
    lock_path = journal_directory(directory, "operator-lock.sqlite") / "operator-lock.sqlite"
    with closing(sqlite3.connect(lock_path, timeout=0)) as lock:
        try:
            lock.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            if error.sqlite_errorcode != sqlite3.SQLITE_BUSY:
                raise
            return {
                "fixture": name,
                "state": "running",
                "reason": "invocation_in_progress",
                "next_action": "Wait for the active operator and reuse this workspace.",
            }
        fixture = local_path(directory / "fixture")
        if mode == "preview":
            fixture.mkdir(exist_ok=True)
        require(fixture.is_dir(), "preview_required")
        admission = local_path(directory / "admission.json")
        journal = fixture / "journal"
        current = journal / "document-pilot.json"
        if mode == "history":
            approved = read_document(admission)
            require(approved["mode"] == "simulated", "simulation_required")
            return {
                "fixture": name,
                "evidence": str(current),
                "approval_sha256": digest(approved),
                "observations": history(journal, approved),
            }
        approved = preview(fixture, name)
        fingerprint = digest(approved)
        if mode == "preview":
            return {
                **approved,
                "approval_sha256": fingerprint,
                "state": "proposed",
                "diff": (fixture / "candidate.diff").read_text(encoding="utf-8"),
                "next_action": f"Review the diff and admit with --approve {name}={fingerprint}.",
            }
        if mode == "run":
            require(supplied == fingerprint, "explicit_fixture_approval_required")
            if not admission.exists():
                with admission.open("x", encoding="utf-8") as record:
                    record.write(canonical(approved))
        require(
            admission.exists() and read_document(admission) == approved, "fixture_admission_changed"
        )
        if mode == "observe":
            prior = read_document(current)
            require(prior in history(journal, approved), "pilot_snapshot_not_retained")
            if prior["state"] in {"review", "finished"}:
                return {
                    "fixture": name,
                    "approval_sha256": fingerprint,
                    "evidence": str(current),
                    "next_action": NEXT[prior["state"]],
                    "observation": prior,
                    "external_writes": read_document(fixture / "simulated-github.json")["writes"],
                }
        if name == "docs":
            report = (
                observe_docs(fixture, prior)
                if mode == "observe"
                else docs.rehearse(fixture, loss=loss)
            )
        else:
            report = code.rehearse(
                fixture, scenario, loss=loss, distinct_ids=True, observe_only=mode == "observe"
            )
        record = report["observation"]
        action = NEXT[record["state"]]
        if record.get("reason", "").endswith("_outcome_unknown") or record.get("reason") in {
            "run_not_observed",
            "wrong_workflow_dispatch",
        }:
            action = "Observe the same journal. Inspect mismatches before accepting evidence."
        return {
            "fixture": name,
            "approval_sha256": fingerprint,
            "evidence": str(current),
            "next_action": action,
            **report,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preview", "run", "observe", "history"))
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--task", choices=TASKS, action="append")
    parser.add_argument("--approve", action="append", default=[], metavar="TASK=SHA256")
    parser.add_argument("--lose", choices=LOSSES, help="Hide one simulated write response")
    parser.add_argument(
        "--scenario",
        choices=("success", "queued", "wrong-run", "incomplete-metadata", "failed"),
        default="success",
        help="Simulate an alternate Python outcome",
    )
    args = parser.parse_args()
    if args.mode != "run" and (args.approve or args.lose):
        parser.error("--approve and --lose require run")
    approvals = {}
    for value in args.approve:
        name, separator, fingerprint = value.partition("=")
        if not separator or name not in TASKS or name in approvals:
            parser.error("Use one --approve TASK=SHA256 per task")
        approvals[name] = fingerprint
    workspace = local_path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    reports = []
    for name in dict.fromkeys(args.task or TASKS):
        try:
            reports.append(
                exercise(
                    workspace / name,
                    name,
                    args.mode,
                    approvals.get(name),
                    "uncertain-" + args.lose if args.lose else None,
                    args.scenario,
                )
            )
        except (Refused, OSError, sqlite3.Error) as error:
            reports.append(
                {
                    "fixture": name,
                    "state": "blocked",
                    "reason": str(error)
                    if isinstance(error, Refused)
                    else "local_evidence_unavailable",
                    "next_action": "Inspect the retained proposal and journal.",
                }
            )
    print(json.dumps({"simulated": True, "tasks": reports}, indent=2))
    return int(
        any(
            item.get("observation", item).get("state") in {"blocked", "finished"}
            for item in reports
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
