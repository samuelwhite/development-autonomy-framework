"""Orchestrate one reviewed document candidate through a trusted operator transport."""

import hashlib
import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile

from github_evidence import check_workflow, complete, obj
from homeci_candidate import check_candidate, check_main, validate_policy, validator_api, verify
from materialize_document_candidate import materialize_candidate

from daf.contract import Refused, canonical, digest, keys, require, sha
from daf.external_receipts import validate_repository
from daf.receipt_bridge import (
    append_observation,
    check_interruption,
    journal_directory,
    local_path,
    observation_history,
    observation_row,
    read_document,
)
from daf.supervised_handoff import (
    interrupted_attempt,
    positive_id,
    preview_document_edit,
    validate_bundle,
)

POLICY_FIELDS = {
    "validator_repository",
    "workflow_id",
    "workflow_revision",
    "workflow_path",
    "workflow_sha256",
    "runner",
}


def checked_candidate(repository, task, edit, review, expected):
    repository = local_path(repository)
    candidate = materialize_candidate(repository, task, edit, review)
    head, base, path = candidate["candidate_sha"], candidate["baseline_sha"], candidate["path"]
    require(head == sha(expected, 40), "approved_candidate_changed")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )

    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(repository), "-c", "protocol.allow=never", *args],
            capture_output=True,
            env=env,
            timeout=10,
            check=False,
        )
        require(result.returncode == 0, "candidate_git_check_failed")
        return result.stdout

    require(
        git("rev-list", "--parents", "-n", "1", head).strip() == f"{head} {base}".encode(),
        "candidate_parent_changed",
    )
    require(
        git("diff-tree", "--no-commit-id", "--name-status", "-r", "-z", base, head)
        == f"M\0{path}\0".encode(),
        "candidate_scope_changed",
    )
    require(
        git("ls-tree", "-z", head, "--", path).startswith(b"100644 blob "), "candidate_mode_changed"
    )
    preview = preview_document_edit(task, edit, git("cat-file", "blob", f"{base}:{path}"))
    actual = git("cat-file", "blob", f"{head}:{path}")
    require(
        actual == preview["candidate_text"].encode()
        and hashlib.sha256(actual).hexdigest() == preview["candidate_file_sha256"],
        "candidate_bytes_changed",
    )
    return candidate


def snapshot(journal, value):
    # Retain every distinct observation. The atomic export is only the latest read model.
    append_observation(journal, value)
    target = local_path(journal / "document-pilot.json")
    with NamedTemporaryFile(dir=journal, delete=False) as temporary:
        staged = Path(temporary.name)
        try:
            temporary.write(canonical(value).encode())
            temporary.flush()
            os.fsync(temporary.fileno())
        except BaseException:
            temporary.close()
            staged.unlink(missing_ok=True)
            raise
    try:
        staged.replace(target)
    finally:
        staged.unlink(missing_ok=True)
    return value


def reconcile(db, action, read, write, admit):
    found = read()
    admit()
    with db:
        new = db.execute("INSERT OR IGNORE INTO intents VALUES (?)", (action,)).rowcount
    if found is not None:
        return found
    if new:
        admit()
        try:
            write()
        except (Refused, OSError, TimeoutError):
            pass  # A successful write with a lost response has the same read-back path.
        found = read()
    require(found is not None, f"{action}_outcome_unknown")
    return found


def run_pilot(
    repository,
    bundle,
    edit,
    review,
    approved,
    journal,
    transport,
    *,
    allowed_repository,
    allowed_validator,
):
    """Run one attempt per private journal. Writes require a separately admitted transport."""
    task = validate_bundle(bundle)
    request = task["request"]
    repo = validate_repository(allowed_repository).lower()
    require(request["repository"] == repo, "pilot_repository_not_allowed")
    approval = keys(
        approved,
        {"task_sha256", "preview_sha256", "review_sha256", "candidate_sha", "verification"},
    )
    require(approval["task_sha256"] == task["task_sha256"], "wrong_approved_task")
    require(
        approval["review_sha256"] == digest(review)
        and approval["preview_sha256"] == review["preview_sha256"],
        "approved_review_changed",
    )
    policy = keys(approval["verification"], POLICY_FIELDS)
    validate_policy(task, policy, allowed_validator)
    candidate = checked_candidate(repository, task, edit, review, approval["candidate_sha"])
    head, base, path = candidate["candidate_sha"], candidate["baseline_sha"], candidate["path"]
    branch = "codex/document-pilot/" + digest([repo, request["attempt_id"]])
    journal = journal_directory(journal, "document-pilot-lock.sqlite", "document-pilot.sqlite")
    initial = {
        "schema_version": 1,
        "repository": repo,
        "task_sha256": task["task_sha256"],
        "task": request["milestone_id"],
        "attempt": request["attempt_id"],
        "file": path,
        "candidate_sha": head,
        "branch": branch,
        "state": "publishing",
        "independent_producer_provenance": False,
    }
    root = f"/repos/{repo}"
    get = transport.get

    def admit():
        if (journal / "journal.sqlite").exists():
            check_interruption(journal, digest(interrupted_attempt(task)))
        check_main(get, root, base, "candidate_main_revision_changed")
        validator = validator_api(policy, get)
        check_main(validator, "", policy["workflow_revision"], "validator_main_revision_changed")
        check_workflow(
            validator,
            policy["workflow_path"],
            policy["workflow_revision"],
            policy["workflow_sha256"],
        )

    def read_branch():
        ref = transport.branch(repo, branch)
        if ref is None:
            return None
        require(ref == head, "candidate_branch_conflict")
        return ref

    def read_draft():
        pulls = transport.pulls(repo, branch)
        require(isinstance(pulls, list), "malformed_candidate_pull_list")
        pulls = complete(pulls, len(pulls))
        require(len(pulls) <= 1, "multiple_candidate_pulls")
        if not pulls:
            return None
        pull = pulls[0]
        number = positive_id(pull.get("number"))
        live = obj(get(f"{root}/pulls/{number}"))
        require(obj(live.get("head")).get("ref") == branch, "candidate_branch_conflict")
        check_candidate(task, {**policy, "candidate_pr": number, "candidate_sha": head}, get)
        return number

    def read_verification(current, number, post=None, *, interrupted=False):
        result = verify(
            task,
            {
                **policy,
                "task_sha256": task["task_sha256"],
                "candidate_sha": head,
                "candidate_pr": number,
            },
            allowed_validator,
            journal,
            get,
            post,
            inspect_interrupted=interrupted,
        )
        for source, target in [
            ("run_id", "run_id"),
            ("attempt", "run_attempt"),
            ("job_id", "job_id"),
            ("runner", "runner"),
            ("run_conclusion", "conclusion"),
        ]:
            if result.get(source) is not None:
                current[target] = result[source]
        current["validator_repository"] = policy["validator_repository"]
        return result

    def inspect_interrupted(current):
        # A prior write may have completed before the interruption was recorded.
        # Check its evidence without reserving or issuing another request.
        if read_branch() != head:
            return
        number = read_draft()
        if number is not None:
            current["draft_pr"] = number
            read_verification(current, number, interrupted=True)

    try:
        with closing(sqlite3.connect(journal / "document-pilot-lock.sqlite", timeout=0)) as lock:
            try:
                lock.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                if error.sqlite_errorcode != sqlite3.SQLITE_BUSY:
                    raise
                return {**initial, "state": "running", "reason": "invocation_in_progress"}
            with closing(sqlite3.connect(journal / "document-pilot.sqlite")) as db:
                with db:
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS binding (id INTEGER PRIMARY KEY, hash TEXT)"
                    )
                    db.execute("CREATE TABLE IF NOT EXISTS intents (action TEXT PRIMARY KEY)")
                    fingerprint = digest(approval)
                    db.execute("INSERT OR IGNORE INTO binding VALUES (1, ?)", (fingerprint,))
                    old = db.execute("SELECT hash FROM binding WHERE id=1").fetchone()
                    require(old == (fingerprint,), "pilot_approval_changed")
                current = initial.copy()
                prior_path = journal / "document-pilot.json"
                if prior_path.is_file():
                    # Resume from the last observed identities, including a completed result.
                    prior = read_document(prior_path)
                    require(prior["task_sha256"] == task["task_sha256"], "pilot_approval_changed")
                    with observation_history(journal / "journal.sqlite") as history:
                        require(
                            observation_row(history, digest(prior)) == (canonical(prior),),
                            "pilot_snapshot_not_retained",
                        )
                    if prior["state"] == "review":
                        return prior
                    current.update(
                        {
                            k: prior[k]
                            for k in (
                                "draft_pr",
                                "run_id",
                                "run_attempt",
                                "job_id",
                                "runner",
                                "conclusion",
                            )
                            if k in prior
                        }
                    )
                try:
                    admit()
                    snapshot(journal, current)
                    reconcile(
                        db,
                        "branch_publish",
                        read_branch,
                        lambda: transport.publish(repo, branch, head),
                        admit,
                    )
                    number = reconcile(
                        db,
                        "draft_create",
                        read_draft,
                        lambda: transport.create_draft(repo, branch),
                        admit,
                    )
                    require(read_branch() == head, "candidate_branch_missing")
                    current.update(draft_pr=number, state="verifying")
                    snapshot(journal, current)

                    def dispatch(binding):
                        admit()
                        require(
                            read_branch() == head and read_draft() == number,
                            "candidate_changed_before_dispatch",
                        )
                        return transport.dispatch(binding)

                    result = read_verification(current, number, dispatch)
                    current["state"] = {"terminal": "finished"}.get(
                        result["state"], result["state"]
                    )
                    if result["verification"] == "passed":
                        current["state"] = "review"
                    if reason := result.get("reason") or result.get("journal_reason"):
                        current["reason"] = reason
                    if current.get("reason") == "dispatch_outcome_unknown":
                        try:
                            check_interruption(journal, digest(interrupted_attempt(task)))
                        except Refused as error:
                            current["reason"] = str(error)
                except Refused as error:
                    current.update(state="blocked", reason=str(error))
                if current.get("reason") == "attempt_incomplete":
                    current["state"] = "blocked"
                    try:
                        inspect_interrupted(current)
                    except Refused:
                        pass  # Keep the interruption and previously retained identities.
                return snapshot(journal, current)
    except (sqlite3.Error, OSError, subprocess.TimeoutExpired) as error:
        raise Refused("pilot_storage_or_transport_unavailable") from error
