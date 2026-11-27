"""Operator transport for one separately approved GitHub documentation pilot."""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from document_pilot import PILOT_FIELDS, POLICY_FIELDS, pilot_branch, run_pilot  # noqa: E402
from homeci_candidate import dispatch, gh_api, validate_policy  # noqa: E402

from daf.contract import Refused, digest, keys, require, sha  # noqa: E402
from daf.external_receipts import validate_repository  # noqa: E402
from daf.receipt_bridge import local_path, read_document  # noqa: E402
from daf.supervised_handoff import positive_id, validate_bundle  # noqa: E402

GIT_CONFIG = (
    "protocol.allow=never",
    "protocol.https.allow=always",
    "http.followRedirects=false",
    "credential.helper=",
    "credential.https://github.com.helper=!gh auth git-credential",
    "credential.interactive=never",
)


def github_url(repository):
    return f"https://github.com/{repository}.git"


class GitHubPilotTransport:
    def __init__(self, repository, branch, pilot, git_directory, git_env, *, api=gh_api):
        self.repository = repository
        self.branch_name = branch
        self.candidate = pilot["candidate_sha"]
        self.dispatch_policy = {**pilot["verification"], "task_sha256": pilot["task_sha256"]}
        self.git_directory = git_directory
        self.git_env = git_env
        self.api = api
        self.remote = github_url(repository)

    def git(self, *args):
        try:
            return subprocess.run(
                ["git", "-C", str(self.git_directory), *args],
                env=self.git_env,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise Refused("candidate_git_transport_interrupted") from None

    def remote_git(self, *args):
        options = [arg for setting in GIT_CONFIG for arg in ("-c", setting)]
        return self.git(*options, *args)

    def ref(self, repository, branch):
        require(
            repository == self.repository and branch == self.branch_name,
            "candidate_publication_scope_changed",
        )
        return f"refs/heads/{self.branch_name}"

    def get(self, path):
        roots = (self.repository, self.dispatch_policy["validator_repository"])
        require(
            any(path == f"/repos/{repo}" or path.startswith(f"/repos/{repo}/") for repo in roots),
            "pilot_github_read_scope_changed",
        )
        return self.api(path)

    def branch(self, repository, branch):
        ref = self.ref(repository, branch)
        result = self.remote_git("ls-remote", "--exit-code", "--refs", self.remote, ref)
        if result.returncode == 2 and not result.stdout:
            return None
        require(result.returncode == 0, "candidate_branch_read_unavailable")
        match = re.fullmatch(
            rb"([a-f0-9]{40})\t" + re.escape(ref.encode()) + rb"\r?\n", result.stdout
        )
        require(match is not None, "malformed_candidate_branch")
        return match[1].decode()

    def publish(self, repository, branch, commit):
        ref = self.ref(repository, branch)
        require(commit == self.candidate, "approved_candidate_changed")
        result = self.remote_git(
            "push", "--no-verify", f"--force-with-lease={ref}:", self.remote, f"{commit}:{ref}"
        )
        require(result.returncode == 0, "candidate_branch_publish_unavailable")

    def pulls(self, repository, branch):
        self.ref(repository, branch)
        owner = self.repository.split("/", 1)[0]
        # Two items are enough to detect ambiguity. Include closed PRs so they block recreation.
        query = urlencode({"state": "all", "head": f"{owner}:{self.branch_name}", "per_page": 2})
        return self.get(f"/repos/{self.repository}/pulls?{query}")

    def create_draft(self, repository, branch):
        self.ref(repository, branch)
        return self.api(
            f"/repos/{self.repository}/pulls",
            {
                "title": "Review documentation pilot candidate",
                "body": "One reviewed documentation edit for the HomeCI pilot.",
                "head": self.branch_name,
                "base": "main",
                "draft": True,
                "maintainer_can_modify": False,
            },
        )

    def dispatch(self, binding):
        number = positive_id(binding.get("candidate_pr"))
        require(
            binding
            == {**self.dispatch_policy, "candidate_pr": number, "candidate_sha": self.candidate},
            "pilot_dispatch_binding_changed",
        )
        return dispatch(binding, api=self.api)


def execute(repository, bundle, edit, review, value, approval_sha256, *, api=gh_api):
    require(digest(value) == sha(approval_sha256), "live_approval_digest_changed")
    approval = keys(value, {"schema_version", "repository", "journal", "pilot"})
    require(
        type(approval["schema_version"]) is int and approval["schema_version"] == 1,
        "invalid_live_approval_schema",
    )
    task = validate_bundle(bundle)
    request = task["request"]
    allowed = validate_repository(approval["repository"]).lower()
    require(allowed == request["repository"], "pilot_repository_not_allowed")
    pilot = keys(approval["pilot"], PILOT_FIELDS)
    policy = keys(pilot["verification"], POLICY_FIELDS)
    validator = validate_repository(policy["validator_repository"])
    validate_policy(task, policy, validator)
    require(isinstance(approval["journal"], str), "absolute_pilot_journal_required")
    journal = Path(approval["journal"])
    require(journal.is_absolute(), "absolute_pilot_journal_required")
    repository = local_path(repository)
    git_env = {key: val for key, val in os.environ.items() if not key.startswith("GIT_")}
    git_env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_LAZY_FETCH="1",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_TERMINAL_PROMPT="0",
        GH_PROMPT_DISABLED="1",
    )
    with TemporaryDirectory(prefix="daf-pilot-publish-") as temporary:
        transport = GitHubPilotTransport(
            allowed,
            pilot_branch(allowed, request["attempt_id"]),
            pilot,
            temporary,
            git_env,
            api=api,
        )
        result = transport.git(
            "-C", str(repository), "rev-parse", "--path-format=absolute", "--git-path", "objects"
        )
        require(result.returncode == 0, "pilot_git_objects_unavailable")
        try:
            objects = local_path(Path(result.stdout.decode().rstrip("\r\n")))
        except UnicodeError:
            raise Refused("pilot_git_objects_unavailable") from None
        require(objects.is_absolute() and objects.is_dir(), "pilot_git_objects_unavailable")
        require(
            transport.git("init", "--bare", "--template=").returncode == 0,
            "pilot_git_storage_unavailable",
        )
        # Only the detached publisher uses this object store. Its config and refs are disposable.
        git_env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = json.dumps(
            objects.as_posix(), ensure_ascii=False
        )
        return run_pilot(
            repository,
            task,
            edit,
            review,
            pilot,
            journal,
            transport,
            allowed_repository=allowed,
            allowed_validator=validator,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("repository", "bundle", "edit", "review", "approval"):
        parser.add_argument(field, type=Path)
    parser.add_argument(
        "--approval-sha256", required=True, help="Digest from the separate approval"
    )
    args = parser.parse_args()
    try:
        result = execute(
            args.repository,
            read_document(args.bundle),
            read_document(args.edit),
            read_document(args.review),
            read_document(args.approval),
            args.approval_sha256,
        )
    except Refused as error:
        result = {"state": "blocked", "reason": str(error)}
    except (OSError, ValueError, sqlite3.Error):
        result = {"state": "blocked", "reason": "pilot_approval_or_storage_unavailable"}
    print(json.dumps(result))
    return 0 if result["state"] == "review" else 2 if result.get("reason") else 1


if __name__ == "__main__":
    raise SystemExit(main())
