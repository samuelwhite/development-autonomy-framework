"""Create a local Git candidate from one exact documentation preview."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from daf.contract import Refused, digest, keys, require, sha  # noqa: E402
from daf.receipt_bridge import local_path, read_document  # noqa: E402
from daf.supervised_handoff import (  # noqa: E402
    MAX_DOCUMENT_BYTES,
    preview_document_edit,
    text_field,
    validate_bundle,
)


def materialize_candidate(repository, bundle, edit, record):
    task = validate_bundle(bundle)
    edit = keys(edit, {"task_sha256", "path", "baseline_file_sha256", "original", "replacement"})
    binding = keys(record, {"preview_sha256", "author_name", "author_email", "created_at"})
    preview_sha = sha(binding["preview_sha256"])
    name = text_field(binding["author_name"])
    email = text_field(binding["author_email"], 254)
    require(
        "<" not in name and ">" not in name and re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", email),
        "invalid_candidate_author",
    )
    created = datetime.strptime(binding["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    require(
        created.strftime("%Y-%m-%dT%H:%M:%SZ") == binding["created_at"], "invalid_candidate_date"
    )
    repository = local_path(repository)
    require(repository.is_dir(), "local_repository_required")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_LAZY_FETCH="1",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_NAME=name,
        GIT_AUTHOR_EMAIL=email,
        GIT_AUTHOR_DATE=f"@{int(created.timestamp())} +0000",
        GIT_COMMITTER_NAME=name,
        GIT_COMMITTER_EMAIL=email,
        GIT_COMMITTER_DATE=f"@{int(created.timestamp())} +0000",
    )

    def git(*args, content=None):
        result = subprocess.run(
            ["git", "-C", str(repository), "-c", "protocol.allow=never", *args],
            env=env,
            input=content,
            capture_output=True,
            timeout=10,
            check=False,
        )
        require(result.returncode == 0, "local_git_candidate_failed")
        return result.stdout

    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    require(root.resolve() == repository.resolve(), "local_repository_root_required")
    baseline = task["request"]["baseline_sha"]
    path = edit["path"]
    require(task["request"]["allowed_paths"] == [path], "one_document_edit_required")
    require(git("cat-file", "-t", baseline) == b"commit\n", "baseline_commit_required")
    entry = git("ls-tree", "-z", baseline, "--", path)
    require(
        entry.startswith(b"100644 blob ") and entry.count(b"\0") == 1, "regular_markdown_required"
    )
    blob = sha(entry.split(b"\t", 1)[0].rsplit(b" ", 1)[1].decode(), 40)
    require(int(git("cat-file", "-s", blob)) <= MAX_DOCUMENT_BYTES, "baseline_document_too_large")
    preview = preview_document_edit(task, edit, git("cat-file", "blob", blob))
    require(digest(preview) == preview_sha, "candidate_preview_changed")

    # A temporary index acts on the pinned baseline tree, without Git hooks or checkout filters.
    with TemporaryDirectory(prefix="daf-document-candidate-") as temporary:
        env["GIT_INDEX_FILE"] = str(Path(temporary) / "index")
        git("read-tree", baseline)
        candidate_blob = git(
            "hash-object", "-w", "--stdin", content=preview["candidate_text"].encode()
        )
        git("update-index", "--cacheinfo", "100644", candidate_blob.decode().strip(), path)
        tree = git("write-tree").decode().strip()
        candidate = (
            git(
                "-c",
                "commit.gpgsign=false",
                "commit-tree",
                tree,
                "-p",
                baseline,
                "-m",
                "Prepare documentation candidate",
            )
            .decode()
            .strip()
        )
    return {
        "status": "local_documentation_candidate",
        "execution_authority": False,
        "candidate_sha": sha(candidate, 40),
        "baseline_sha": baseline,
        "task_sha256": task["task_sha256"],
        "preview_sha256": preview_sha,
        "path": path,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repository", "bundle", "edit", "record"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args(argv)
    try:
        result = materialize_candidate(
            args.repository,
            read_document(args.bundle),
            read_document(args.edit),
            read_document(args.record),
        )
    except (
        Refused,
        OSError,
        ValueError,
        TypeError,
        RecursionError,
        subprocess.TimeoutExpired,
    ) as error:
        reason = (
            str(error) if isinstance(error, Refused) else "invalid_or_unavailable_candidate_input"
        )
        print(json.dumps({"outcome": "refused", "reason": reason}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
