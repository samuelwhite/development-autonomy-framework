"""Read one public GitHub-pinned DAF plan; propose tasks without execution authority.

This offline validator never discovers credentials, accesses networks, or dispatches
workers. Import identities and receipts are never owner approvals or CI attestations.
"""

import base64
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .contract import Plan, Refused, canonical, digest, keys, require, sha
from .supervised_handoff import paths, prepare_task, validate_bundle, validate_repository

MAX_CONTENT = 64 * 1024
MAX_RESPONSE = 192 * 1024
_MILESTONE = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")


def _document(raw: bytes):
    require(isinstance(raw, bytes) and len(raw) <= MAX_CONTENT, "planning_document_too_large")

    def unique(pairs):
        document = {}
        for name, value in pairs:
            require(name not in document, "duplicate_json_key")
            document[name] = value
        return document

    def nonfinite(_value):
        raise Refused("nonfinite_json_value")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, Refused):
            raise
        raise Refused("invalid_planning_json") from None


def _source_path(value):
    """Exact portable JSON path; no directories, globs or URL fragments."""
    validated = paths([value])[0]
    require(validated.endswith(".json") and len(validated) <= 240, "invalid_source_path")
    return validated


def _document_response(raw):
    def no_duplicates(pairs):
        obj = {}
        for key, val in pairs:
            require(key not in obj, "duplicate_json_key")
            obj[key] = val
        return obj

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, Refused):
            raise
        raise Refused("invalid_github_response") from None


def _github_blob(data, path):
    require(
        isinstance(data, dict)
        and data.get("type") == "file"
        and data.get("path") == path
        and data.get("encoding") == "base64"
        and "target" not in data
        and "submodule_git_url" not in data,
        "invalid_github_file",
    )
    size = data.get("size")
    require(type(size) is int and 0 <= size <= MAX_CONTENT, "invalid_github_file_size")
    blob_sha = sha(data.get("sha"), 40)
    encoded = data.get("content")
    require(isinstance(encoded, str) and len(encoded) <= 4 * MAX_CONTENT, "invalid_github_file")
    try:
        content = base64.b64decode(encoded.replace("\n", ""), validate=True)
    except (ValueError, base64.binascii.Error):
        raise Refused("invalid_github_base64") from None
    require(len(content) == size, "github_file_size_mismatch")
    computed = hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\0" + content, usedforsecurity=False
    ).hexdigest()
    require(computed == blob_sha, "github_blob_mismatch")
    return content, blob_sha


def ingest_public_milestone(repository, commit_sha, source_path, milestone_id, *, get_json):
    """Create a deterministic, non-authoritative proposal from pinned GitHub data.

    Caller supplies an explicit public GitHub reader; this module never opens
    network connections or accepts authority from the source document.
    """
    validate_repository(repository)
    sha(commit_sha, 40)
    source_path = _source_path(source_path)
    require(
        isinstance(milestone_id, str) and _MILESTONE.fullmatch(milestone_id),
        "invalid_milestone_identity",
    )
    require(callable(get_json), "missing_read_only_source")
    prefix = f"/repos/{repository}"
    commit = get_json(f"{prefix}/git/commits/{commit_sha}")
    require(
        isinstance(commit, dict) and commit.get("sha") == commit_sha,
        "github_commit_mismatch",
    )
    response = get_json(f"{prefix}/contents/{source_path}?ref={commit_sha}")
    content, blob_sha = _github_blob(response, source_path)
    document = _document(content)
    spec = keys(document, {"schema_version", "plan", "tasks"})
    require(
        type(spec["schema_version"]) is int and spec["schema_version"] == 1,
        "unsupported_planning_ingest_schema",
    )
    plan = Plan.validate_data(spec["plan"])
    require(plan["repository"] == repository, "planning_repository_mismatch")
    milestone_ids = {x["id"] for x in plan["milestones"]}
    require(milestone_id in milestone_ids, "unknown_planning_milestone")
    tasks = spec["tasks"]
    require(isinstance(tasks, list) and 0 < len(tasks) <= 100, "invalid_planning_tasks")
    registered = {}
    for raw in tasks:
        item = keys(raw, {"milestone_id", "instruction", "allowed_paths", "required_checks"})
        mid = item["milestone_id"]
        require(
            isinstance(mid, str) and mid in milestone_ids and mid not in registered,
            "invalid_or_duplicate_planning_task",
        )
        allowed = paths(item["allowed_paths"])
        for filepath in allowed:
            require(
                any(filepath.startswith(prefix) for prefix in plan["boundaries"]["code_prefixes"])
                and not any(
                    filepath.startswith(prefix)
                    for prefix in plan["boundaries"]["protected_prefixes"]
                )
                and filepath not in plan["validation"]["protected_files"],
                "planning_task_out_of_scope",
            )
        registered[mid] = item
    require(milestone_id in registered, "missing_planning_task")
    task = registered[milestone_id]
    require(
        {c.get("name") for c in task["required_checks"] if isinstance(c, dict)}
        == set(plan["validation"]["required_checks"]),
        "planning_check_mismatch",
    )
    for check in task["required_checks"]:
        require(
            isinstance(check, dict)
            and check.get("workflow_path") == plan["validation"]["workflow_path"]
            and check.get("workflow_sha256") == plan["validation"]["workflow_sha256"],
            "planning_workflow_mismatch",
        )
    bundle = prepare_task(
        {
            "schema_version": 1,
            "plan_sha256": digest(plan),
            "milestone_id": milestone_id,
            "attempt_id": f"proposal-{milestone_id}",
            "repository": repository,
            "baseline_sha": plan["baseline_revision"],
            "instruction": task["instruction"],
            "allowed_paths": task["allowed_paths"],
            "required_checks": task["required_checks"],
        }
    )
    source = {
        "repository": repository,
        "commit_sha": commit_sha,
        "path": source_path,
        "git_blob_sha": blob_sha,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "plan_sha256": digest(plan),
    }
    identity = digest(
        {
            "repository": repository,
            "commit_sha": commit_sha,
            "path": source_path,
            "milestone_id": milestone_id,
        }
    )
    # Source metadata is part of the immutable identity; no wall-clock fields.
    return {
        "schema_version": 1,
        "status": "pinned_plan_proposal",
        "execution_authority": False,
        "approval": None,
        "ingestion_id": identity,
        "source": source,
        "milestone_id": milestone_id,
        "dependencies": next(
            x["depends_on"] for x in plan["milestones"] if x["id"] == milestone_id
        ),
        "acceptance": next(x["acceptance"] for x in plan["milestones"] if x["id"] == milestone_id),
        "bundle": validate_bundle(bundle),
    }


def store_idempotently(record, output_dir: Path):
    """Persist exactly one immutable record per identity, atomically if supported."""
    require(
        record.get("status") == "pinned_plan_proposal"
        and record.get("execution_authority") is False,
        "invalid_ingest_record",
    )
    identity = sha(record.get("ingestion_id"))
    source = record.get("source")
    require(isinstance(source, dict), "invalid_ingest_record")
    require(
        identity
        == digest(
            {
                "repository": source.get("repository"),
                "commit_sha": source.get("commit_sha"),
                "path": source.get("path"),
                "milestone_id": record.get("milestone_id"),
            }
        ),
        "invalid_ingest_identity",
    )
    validate_bundle(record.get("bundle"))
    folder = Path(output_dir).absolute()
    require(not str(folder).replace("\\", "/").startswith("//"), "network_directory_refused")
    require(
        all(not p.is_symlink() and not p.is_junction() for p in (folder, *folder.parents)),
        "linked_storage_directory_refused",
    )
    require(folder.is_dir(), "storage_directory_missing")
    target = folder / f"{identity}.json"
    payload = (canonical(record) + "\n").encode("utf-8")
    require(len(payload) < MAX_RESPONSE, "ingest_record_too_large")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".daf-ingest-", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Hard-link creation fails rather than replacing an existing record;
            # the complete temporary file becomes visible as one immutable file.
            os.link(temp_path, target)
            outcome = "created"
        except FileExistsError:
            outcome = "already_present"
        if outcome == "already_present":
            require(
                target.is_file()
                and not target.is_symlink()
                and target.stat().st_size <= MAX_RESPONSE,
                "ingestion_conflict",
            )
            require(target.read_bytes() == payload, "ingestion_conflict")
        return {"outcome": outcome, "ingestion_id": identity, "record_path": str(target)}
    except (OSError, ValueError) as error:
        if isinstance(error, Refused):
            raise
        raise Refused("storage_write_failed") from None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
