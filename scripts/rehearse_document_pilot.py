"""Exercise the document pilot with real local Git and simulated GitHub."""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from document_pilot import run_pilot  # noqa: E402
from homeci_candidate import JOB, STEPS, WORKFLOW, WORKFLOW_FILE, title  # noqa: E402
from materialize_document_candidate import materialize_candidate  # noqa: E402

from daf.contract import Refused, canonical, digest  # noqa: E402
from daf.supervised_handoff import prepare_task, preview_document_edit  # noqa: E402

DAF = "example/daf"
FORGE = "example/validator"
REVISION = "c" * 40
DOCUMENT = "docs/guide.md"
WORKFLOW_BYTES = b"name: Offline rehearsal\n"
PR, RUN, JOB_ID, WORKFLOW_ID = 28, 1401, 1601, 42
PILOT_TITLE = "Review the operator guide"
BASELINE_TEXT = b"# Operator guide\n\nCheck the old status.\n"


def git(directory, *args, raw=False):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_AUTHOR_DATE="2026-01-01T00:00:00Z",
        GIT_COMMITTER_DATE="2026-01-01T00:00:00Z",
    )
    result = subprocess.run(
        [
            "git",
            "-C",
            str(directory),
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.hooksPath=" + os.devnull,
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.file.allow=always",
            *args,
        ],
        env=env,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise Refused("rehearsal_git_failed")
    return result.stdout if raw else result.stdout.decode().strip()


def setup(directory):
    repo, remote, journal = (directory / part for part in ("source", "remote.git", "journal"))
    config = directory / "request.json"
    if not config.exists():
        for path in (repo, remote, journal):
            path.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(remote, "init", "-q", "--bare")
        (repo / "docs").mkdir()
        (repo / DOCUMENT).write_bytes(BASELINE_TEXT)
        git(repo, "add", "--", DOCUMENT)
        git(
            repo,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Baseline",
        )
        base = git(repo, "rev-parse", "HEAD")
        git(repo, "push", "--quiet", str(remote), f"{base}:refs/heads/main")
        policy = {
            "validator_repository": FORGE,
            "workflow_id": WORKFLOW_ID,
            "workflow_revision": REVISION,
            "workflow_path": WORKFLOW,
            "workflow_sha256": hashlib.sha256(WORKFLOW_BYTES).hexdigest(),
            "runner": "demo-runner",
        }
        bundle = prepare_task(
            {
                "schema_version": 1,
                "plan_sha256": "a" * 64,
                "milestone_id": "operator-guide",
                "attempt_id": "operator-guide-1",
                "repository": DAF,
                "baseline_sha": base,
                "instruction": PILOT_TITLE,
                "allowed_paths": [DOCUMENT],
                "required_checks": [
                    {
                        "name": JOB,
                        "validator_id": FORGE,
                        "source": "github_actions",
                        "workflow_path": WORKFLOW,
                        "workflow_sha256": policy["workflow_sha256"],
                        "artifact_name": None,
                    }
                ],
            }
        )
        edit = {
            "task_sha256": bundle["task_sha256"],
            "path": DOCUMENT,
            "baseline_file_sha256": hashlib.sha256(BASELINE_TEXT).hexdigest(),
            "original": "Check the old status.",
            "replacement": "Check Mission Control.",
        }
        preview = preview_document_edit(bundle, edit, BASELINE_TEXT)
        review = {
            "preview_sha256": digest(preview),
            "author_name": "Fixture",
            "author_email": "fixture@example.test",
            "created_at": "2026-01-01T00:00:00Z",
        }
        candidate = materialize_candidate(repo, bundle, edit, review)
        approval = {
            "task_sha256": bundle["task_sha256"],
            "preview_sha256": digest(preview),
            "review_sha256": digest(review),
            "candidate_sha": candidate["candidate_sha"],
            "verification": policy,
        }
        config.write_text(canonical([bundle, edit, review, approval]), encoding="utf-8")
    return repo, remote, journal, json.loads(config.read_text(encoding="utf-8"))


class RehearsalTransport:
    """A local-only Git remote and persisted simulated API responses."""

    def __init__(self, repo, remote, state, *, loss=None, outcome="success"):
        self.repo, self.remote, self.state = repo, remote, state
        self.loss, self.outcome = loss, outcome
        self.before_write = lambda action: None
        self.stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.hidden = set()
        self.base = self.branch(DAF, "main")
        self.data = (
            json.loads(state.read_text(encoding="utf-8"))
            if state.exists()
            else {"writes": {"branch": 0, "draft": 0, "dispatch": 0}}
        )

    def save(self, action, **fields):
        self.data["writes"][action] += 1
        self.data.update(fields)
        self.state.write_text(canonical(self.data), encoding="utf-8")
        if self.loss in {action, "uncertain-" + action}:
            if self.loss.startswith("uncertain-"):
                self.hidden.add(action)
            raise Refused("simulated_response_lost")

    def branch(self, repository, branch):
        assert repository == DAF
        if "branch" in self.hidden:
            return None
        ref = git(self.repo, "ls-remote", "--refs", str(self.remote), f"refs/heads/{branch}")
        return ref.split()[0] if ref else None

    def publish(self, repository, branch, head):
        assert repository == DAF and branch.startswith("codex/document-pilot/")
        self.before_write("branch")
        ref = f"refs/heads/{branch}"
        git(
            self.repo,
            "push",
            "--quiet",
            f"--force-with-lease={ref}:",
            str(self.remote),
            f"{head}:{ref}",
        )
        self.save("branch")

    def pulls(self, repository, branch):
        assert repository == DAF
        return (
            [{"number": PR}]
            if self.data.get("branch") == branch and "draft" not in self.hidden
            else []
        )

    def create_draft(self, repository, branch):
        assert repository == DAF
        self.before_write("draft")
        self.save("draft", branch=branch)

    def dispatch(self, binding):
        self.before_write("dispatch")
        self.save("dispatch", binding=binding)
        return {"workflow_run_id": RUN}

    def get(self, path):
        daf, forge = f"/repos/{DAF}", f"/repos/{FORGE}"
        stamp = self.stamp
        base = self.base
        private = {"full_name": FORGE, "private": True}
        binding = self.data.get("binding")
        run_path = f"{forge}/actions/runs/{RUN}/attempts/1"
        status = "queued" if self.outcome == "queued" else "completed"
        conclusion = None if status == "queued" else self.outcome
        run = {
            "id": RUN,
            "run_attempt": 1,
            "workflow_id": WORKFLOW_ID,
            "head_sha": REVISION,
            "head_branch": "main",
            "path": WORKFLOW,
            "event": "workflow_dispatch",
            "display_title": title(binding) if binding else "",
            "repository": private,
            "head_repository": private,
            "status": status,
            "conclusion": conclusion,
            "updated_at": stamp,
        }
        listed = [run] if binding and "dispatch" not in self.hidden else []
        job = {
            "id": JOB_ID,
            "run_id": RUN,
            "run_attempt": 1,
            "head_sha": REVISION,
            "name": JOB,
            "runner_name": "demo-runner",
            "labels": ["self-hosted"],
            "status": status,
            "conclusion": conclusion,
            "steps": [
                {"name": name, "status": "completed", "conclusion": "success"} for name, _ in STEPS
            ],
        }
        responses = {
            f"{daf}/git/ref/heads/main": {"ref": "refs/heads/main", "object": {"sha": base}},
            f"{forge}/git/ref/heads/main": {"ref": "refs/heads/main", "object": {"sha": REVISION}},
            forge: private,
            f"{forge}/actions/workflows/{WORKFLOW_FILE}": {
                "id": WORKFLOW_ID,
                "path": WORKFLOW,
                "state": "active",
            },
            f"{forge}/contents/{WORKFLOW}?ref={REVISION}": {
                "type": "file",
                "path": WORKFLOW,
                "encoding": "base64",
                "content": base64.b64encode(WORKFLOW_BYTES).decode(),
            },
            f"{forge}/actions/workflows/{WORKFLOW_ID}/runs?event=workflow_dispatch&per_page=100": {
                "workflow_runs": listed,
                "total_count": len(listed),
            },
            run_path: run,
            f"{run_path}/jobs?per_page=100": {
                "jobs": [job] if status == "completed" else [],
                "total_count": int(status == "completed"),
            },
        }
        if "branch" in self.data:
            branch = self.data["branch"]
            responses[f"{daf}/pulls/{PR}"] = {
                "number": PR,
                "draft": True,
                "state": "open",
                "changed_files": 1,
                "head": {
                    "sha": self.branch(DAF, branch),
                    "ref": branch,
                    "repo": {"full_name": DAF},
                },
                "base": {"sha": base, "repo": {"full_name": DAF}, "ref": "main"},
                "updated_at": stamp,
            }
            responses[f"{daf}/pulls/{PR}/files?per_page=100"] = [
                {"filename": DOCUMENT, "status": "modified"},
            ]
        return responses[path]


def rehearse(directory, *, loss=None, outcome="success"):
    repo, remote, journal, inputs = setup(directory)
    transport = RehearsalTransport(
        repo, remote, directory / "simulated-github.json", loss=loss, outcome=outcome
    )
    result = run_pilot(
        repo, *inputs, journal, transport, allowed_repository=DAF, allowed_validator=FORGE
    )
    return {"observation": result, "external_writes": transport.data["writes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Dedicated directory for the local rehearsal")
    parser.add_argument(
        "--lose",
        choices=[
            "branch",
            "draft",
            "dispatch",
            "uncertain-branch",
            "uncertain-draft",
            "uncertain-dispatch",
        ],
    )
    parser.add_argument(
        "--outcome", choices=["success", "queued", "failure", "cancelled"], default="success"
    )
    args = parser.parse_args()
    directory = args.directory.absolute()
    directory.mkdir(exist_ok=True)
    if any(directory.iterdir()) and not (directory / "request.json").is_file():
        parser.error("Choose an empty directory or an existing rehearsal")
    print(json.dumps(rehearse(directory, loss=args.lose, outcome=args.outcome), indent=2))


if __name__ == "__main__":
    main()
