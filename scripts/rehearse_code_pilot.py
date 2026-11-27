"""Rehearse one fixed Python edit using disposable Git and simulated GitHub."""

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from document_pilot import pilot_branch, reconcile, snapshot  # noqa: E402
from github_evidence import check_workflow, complete, obj, run_identity  # noqa: E402
from homeci_candidate import (  # noqa: E402
    check_candidate,
    check_dispatch_identity,
    check_main,
    run_or_resume,
    validator_api,
)
from rehearse_document_pilot import (  # noqa: E402
    DAF,
    FORGE,
    JOB_ID,
    PR,
    REVISION,
    RUN,
    WORKFLOW,
    WORKFLOW_BYTES,
    WORKFLOW_ID,
    RehearsalTransport,
    git,
)

from daf.contract import Refused, canonical, digest, require  # noqa: E402
from daf.receipt_bridge import journal_directory, local_path, read_document  # noqa: E402
from daf.supervised_handoff import prepare_task, validate_bundle  # noqa: E402

CODE = "src/label.py"
TEST = "tests/test_label.py"
BEFORE = b"def normalize_label(value):\n    return value.lower()\n"
AFTER = b"def normalize_label(value):\n    return value.strip().lower()\n"
TEST_BYTES = b"""import sys
import unittest
from pathlib import Path
from runpy import run_path

normalize_label = run_path(str(Path(__file__).resolve().parents[1] / "src/label.py"))[
    "normalize_label"
]
expected = sys.argv.pop()


class LabelTest(unittest.TestCase):
    def test_trim_and_lowercase(self):
        self.assertEqual(normalize_label("  Ready  "), expected)


if __name__ == "__main__":
    unittest.main()
"""
CHECK = "Focused Python test"
SCENARIOS = (
    "success",
    "lost-response",
    "changed-baseline",
    "extra-file",
    "wrong-run",
    "incomplete-metadata",
    "failed",
    "queued",
)
FORGE_ROOT = f"/repos/{FORGE}"
POLICY = {
    "validator_repository": FORGE,
    "workflow_id": WORKFLOW_ID,
    "workflow_revision": REVISION,
    "workflow_path": WORKFLOW,
    "workflow_sha256": hashlib.sha256(WORKFLOW_BYTES).hexdigest(),
    "runner": "demo-runner",
}


def commit(repo, message):
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        message,
    )
    return git(repo, "rev-parse", "HEAD")


def object_diff(repo, base, candidate):
    return git(repo, "diff", "--no-ext-diff", "--no-textconv", base, candidate, raw=True)


def setup(directory, scenario):
    repo, remote, journal = (
        local_path(directory / part) for part in ("source", "remote.git", "journal")
    )
    proposal_path = directory / "proposal.json"
    if proposal_path.exists():
        return (
            repo,
            remote,
            journal,
            read_document(proposal_path),
            read_document(directory / "approval.json"),
        )
    require(not any(directory.iterdir()), "empty_rehearsal_directory_required")
    for path in (repo, remote, journal, repo / "src", repo / "tests"):
        path.mkdir()
    git(repo, "init", "--quiet", "--object-format=sha1", "-b", "main")
    git(remote, "init", "--quiet", "--object-format=sha1", "--bare")
    (repo / CODE).write_bytes(BEFORE)
    (repo / TEST).write_bytes(TEST_BYTES)
    git(repo, "add", "--", CODE, TEST)
    base = commit(repo, "Fixture baseline")
    git(repo, "push", "--quiet", str(remote), f"{base}:refs/heads/main")
    (repo / CODE).write_bytes(AFTER)
    git(repo, "add", "--", CODE)
    if scenario == "extra-file":
        (repo / "extra.txt").write_text("Outside the approved scope.\n", encoding="utf-8")
        git(repo, "add", "--", "extra.txt")
    candidate = commit(repo, "Trim spaces when normalizing a label")
    diff = object_diff(repo, base, candidate)
    plan = {
        "repository": DAF,
        "baseline_sha": base,
        "change": "Trim surrounding spaces before lowercasing a display label.",
        "file": CODE,
        "focused_test": TEST,
        "test_sha256": hashlib.sha256(TEST_BYTES).hexdigest(),
    }
    task = prepare_task(
        {
            "schema_version": 1,
            "plan_sha256": digest(plan),
            "milestone_id": "normalize-label",
            "attempt_id": "normalize-label-1",
            "repository": DAF,
            "baseline_sha": base,
            "instruction": plan["change"],
            "allowed_paths": [CODE],
            "required_checks": [
                {
                    "name": CHECK,
                    "validator_id": FORGE,
                    "source": "github_actions",
                    "workflow_path": WORKFLOW,
                    "workflow_sha256": POLICY["workflow_sha256"],
                    "artifact_name": None,
                }
            ],
        }
    )
    proposal = {
        "task": task,
        "plan": plan,
        "candidate_sha": candidate,
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
    }
    approval = {
        "mode": "simulated",
        "execution_authority": False,
        "task_sha256": task["task_sha256"],
        "baseline_sha": base,
        "candidate_sha": candidate,
        "proposal_sha256": digest(proposal),
        "verification": POLICY,
    }
    proposal_path.write_text(canonical(proposal), encoding="utf-8")
    (directory / "approval.json").write_text(canonical(approval), encoding="utf-8")
    (directory / "candidate.diff").write_bytes(diff)
    if scenario == "changed-baseline":
        git(repo, "push", "--quiet", str(remote), f"{candidate}:refs/heads/main")
    return repo, remote, journal, proposal, approval


def check_scope(repo, directory, base, candidate, proposal):
    require(
        git(repo, "rev-list", "--parents", "-n", "1", candidate) == f"{candidate} {base}",
        "candidate_parent_changed",
    )
    require(
        git(
            repo,
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "--no-renames",
            "-r",
            "-z",
            base,
            candidate,
            raw=True,
        )
        == f"M\0{CODE}\0".encode(),
        "candidate_scope_changed",
    )
    require(
        git(repo, "ls-tree", candidate, "--", CODE).startswith("100644 blob "),
        "candidate_mode_changed",
    )
    require(
        git(repo, "show", f"{base}:{CODE}", raw=True) == BEFORE
        and git(repo, "show", f"{candidate}:{CODE}", raw=True) == AFTER
        and git(repo, "show", f"{candidate}:{TEST}", raw=True) == TEST_BYTES,
        "fixture_bytes_changed",
    )
    diff = object_diff(repo, base, candidate)
    require(
        hashlib.sha256(diff).hexdigest() == proposal["diff_sha256"]
        and local_path(directory / "candidate.diff").read_bytes() == diff,
        "candidate_diff_changed",
    )


class CodeTransport(RehearsalTransport):
    """Retain the simulated writes and run only the two trusted fixture blobs."""

    def __init__(self, repo, remote, directory, scenario, *, loss=None, distinct_ids=False):
        if distinct_ids:
            self.pr, self.run, self.job = PR + 1, RUN + 1, JOB_ID + 1
        if scenario == "lost-response":
            loss = "uncertain-dispatch"
        super().__init__(repo, remote, directory / "simulated-github.json", loss=loss)
        self.directory = directory
        self.scenario = scenario
        self.outcome = "queued" if scenario == "queued" else self.data.get("conclusion", "success")

    def dispatch(self, binding):
        candidate = binding["candidate_sha"]
        with TemporaryDirectory(dir=self.directory) as checkout:
            root = Path(checkout)
            for path, expected in ((CODE, AFTER), (TEST, TEST_BYTES)):
                content = git(self.repo, "show", f"{candidate}:{path}", raw=True)
                require(content == expected, "fixture_bytes_changed")
                output = root / path
                output.parent.mkdir()
                output.write_bytes(content)
            expected = "blocked" if self.scenario == "failed" else "ready"
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(root / TEST), expected],
                cwd=root,
                capture_output=True,
                timeout=10,
                check=False,
            )
            (self.directory / "validation.log").write_bytes(result.stdout + result.stderr)
        conclusion = "success" if result.returncode == 0 else "failure"
        if self.scenario != "queued":
            self.outcome = conclusion
        self.save("dispatch", binding=binding, conclusion=conclusion)
        return {"workflow_run_id": self.run}

    def get(self, path):
        response = super().get(path)
        attempt = f"{FORGE_ROOT}/actions/runs/{self.run}/attempts/1"
        if path == f"/repos/{DAF}/pulls/{self.pr}/files?per_page=100":
            return [{"filename": CODE, "status": "modified"}]
        if path == attempt:
            if self.scenario == "wrong-run":
                return {**response, "id": self.run + 1}
            if self.scenario == "incomplete-metadata":
                return {key: value for key, value in response.items() if key != "display_title"}
        if path == attempt + "/jobs?per_page=100" and response["jobs"]:
            (job,) = response["jobs"]
            return {
                "total_count": 1,
                "jobs": [
                    {
                        **job,
                        "name": CHECK,
                        "steps": [
                            {"name": CHECK, "status": "completed", "conclusion": self.outcome},
                        ],
                    }
                ],
            }
        return response


def observe(binding, read, result, expected_job):
    run_id = result["run_id"]
    choice = {**binding, "run_id": run_id, "attempt": 1}
    attempt = f"/actions/runs/{run_id}/attempts/1"
    run = obj(read(attempt))
    status, conclusion, _ = run_identity(run, FORGE, choice, REVISION, datetime.now(UTC))
    check_dispatch_identity(run, binding, result)
    if status == "queued":
        result.update(state="queued", run_attempt=1)
        return
    jobs = obj(read(attempt + "/jobs?per_page=100"))
    (job,) = complete(jobs.get("jobs"), 1)
    require(
        jobs["total_count"] == 1
        and job.get("id") == expected_job
        and job.get("run_id") == run_id
        and job.get("run_attempt") == 1
        and job.get("head_sha") == REVISION
        and job.get("runner_name") == POLICY["runner"]
        and job.get("name") == CHECK
        and "self-hosted" in job.get("labels", []),
        "wrong_workflow_job",
    )
    require(
        status == job.get("status") == "completed"
        and conclusion == job.get("conclusion")
        and conclusion in ("success", "failure")
        and job.get("steps") == [{"name": CHECK, "status": status, "conclusion": conclusion}],
        "incomplete_fixture_validation",
    )
    result.update(
        run_attempt=1,
        job_id=expected_job,
        runner=POLICY["runner"],
        conclusion=conclusion,
        state="review" if conclusion == "success" else "finished",
    )
    if conclusion == "failure":
        result["reason"] = "focused_test_failed"


def rehearse(directory, scenario="success", *, loss=None, distinct_ids=False, observe_only=False):
    directory = local_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    repo, remote, journal, proposed, approval = setup(directory, scenario)
    task = validate_bundle(proposed["task"])
    request = task["request"]
    base, candidate = request["baseline_sha"], approval["candidate_sha"]
    require(
        approval
        == {
            "mode": "simulated",
            "execution_authority": False,
            "task_sha256": task["task_sha256"],
            "baseline_sha": base,
            "candidate_sha": proposed["candidate_sha"],
            "proposal_sha256": digest(proposed),
            "verification": POLICY,
        }
        and request["repository"] == DAF
        and request["allowed_paths"] == [CODE]
        and request["plan_sha256"] == digest(proposed["plan"]),
        "fixture_approval_changed",
    )
    branch = pilot_branch(DAF, request["attempt_id"])
    journal = journal_directory(
        journal, "code-rehearsal.sqlite", "code-rehearsal-lock.sqlite", "homeci.sqlite"
    )
    initial = {
        "schema_version": 1,
        "kind": "code-rehearsal",
        "repository": DAF,
        "task_sha256": task["task_sha256"],
        "task": request["milestone_id"],
        "attempt": request["attempt_id"],
        "file": CODE,
        "candidate_sha": candidate,
        "branch": branch,
        "state": "publishing",
        "independent_producer_provenance": False,
        "validator_repository": FORGE,
        "workflow_revision": REVISION,
        "workflow_id": POLICY["workflow_id"],
    }
    with closing(sqlite3.connect(journal / "code-rehearsal-lock.sqlite")) as lock:
        lock.execute("BEGIN IMMEDIATE")
        transport = CodeTransport(
            repo, remote, directory, scenario, loss=loss, distinct_ids=distinct_ids
        )
        binding = {
            **POLICY,
            "task_sha256": task["task_sha256"],
            "candidate_sha": candidate,
            "candidate_pr": transport.pr,
        }
        read = validator_api(binding, transport.get)

        def admit():
            check_main(transport.get, f"/repos/{DAF}", base, "candidate_main_revision_changed")
            check_main(read, "", REVISION, "validator_main_revision_changed")
            check_workflow(read, WORKFLOW, REVISION, POLICY["workflow_sha256"])

        def read_branch():
            existing = transport.branch(DAF, branch)
            require(existing in (None, candidate), "candidate_branch_conflict")
            return existing

        def read_draft():
            pulls = transport.pulls(DAF, branch)
            if not pulls:
                return None
            require(pulls == [{"number": transport.pr}], "multiple_candidate_pulls")
            check_candidate(task, binding, transport.get)
            return transport.pr

        def dispatch(approved):
            admit()
            check_scope(repo, directory, base, candidate, proposed)
            require(
                read_branch() == candidate and read_draft() == transport.pr,
                "candidate_changed_before_dispatch",
            )
            return transport.dispatch(approved)

        def write_draft():
            with closing(sqlite3.connect(journal / "code-rehearsal.sqlite")) as db:
                with db:
                    db.execute("CREATE TABLE IF NOT EXISTS intents (action TEXT PRIMARY KEY)")
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS binding (id INTEGER PRIMARY KEY, hash TEXT)"
                    )
                    fingerprint = digest(approval)
                    db.execute("INSERT OR IGNORE INTO binding VALUES (1, ?)", (fingerprint,))
                    require(
                        db.execute("SELECT hash FROM binding WHERE id=1").fetchone()
                        == (fingerprint,),
                        "fixture_approval_changed",
                    )
                reconcile(
                    db,
                    "branch_publish",
                    read_branch,
                    lambda: transport.publish(DAF, branch, candidate),
                    admit,
                )
                return reconcile(
                    db,
                    "draft_create",
                    read_draft,
                    lambda: transport.create_draft(DAF, branch),
                    admit,
                )

        try:
            check_scope(repo, directory, base, candidate, proposed)
            admit()
            if observe_only:
                require(read_branch() == candidate, "branch_publish_outcome_unknown")
                initial["draft_pr"] = read_draft()
                require(initial["draft_pr"] is not None, "draft_create_outcome_unknown")
            else:
                initial["draft_pr"] = write_draft()
            initial["run_id"] = run_or_resume(
                journal / "homeci.sqlite",
                binding,
                read,
                None if observe_only else dispatch,
            )
            observe(binding, read, initial, transport.job)
            check_candidate(task, binding, transport.get)
        except Refused as error:
            initial.update(state="blocked", reason=str(error))
        return {
            "observation": snapshot(journal, initial),
            "external_writes": transport.data["writes"],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", type=Path, help="Empty or previous disposable rehearsal directory"
    )
    parser.add_argument("--scenario", choices=SCENARIOS, default="success")
    args = parser.parse_args()
    try:
        report = rehearse(args.directory, args.scenario)
        print(json.dumps(report))
    except (Refused, OSError, sqlite3.Error, subprocess.TimeoutExpired) as error:
        print(json.dumps({"state": "blocked", "reason": str(error)}))
        return 2
    return 0 if report["observation"]["state"] == "review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
