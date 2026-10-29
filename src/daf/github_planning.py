"""Read one public GitHub-pinned DAF plan; propose tasks without execution authority.

This offline validator never discovers credentials, accesses networks, or dispatches
workers. Import identities and receipts are never owner approvals or CI attestations.
"""

import base64
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from .contract import Plan, Refused, canonical, digest, keys, require, sha, strings
from .supervised_handoff import file_path, paths, prepare_task, validate_bundle, validate_repository

MAX_CONTENT = 64 * 1024
MAX_RESPONSE = 192 * 1024
MAX_SOURCE_PARTS = 16
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
    require(
        validated.endswith(".json")
        and len(validated) <= 240
        and len(validated.split("/")) <= MAX_SOURCE_PARTS,
        "invalid_source_path",
    )
    return validated


def _document_response(raw):
    def no_duplicates(pairs):
        obj = {}
        for key, val in pairs:
            require(key not in obj, "duplicate_json_key")
            obj[key] = val
        return obj

    def nonfinite(_value):
        raise Refused("nonfinite_json_value")

    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=no_duplicates, parse_constant=nonfinite
        )
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


def validate_public_github_path(path):
    """Only the pinned commit/tree/content endpoints used by this reader."""
    require(isinstance(path, str), "invalid_github_path")
    match = re.fullmatch(r"/repos/([^/]+/[^/]+)/(.*)", path)
    require(match is not None, "invalid_github_path")
    validate_repository(match[1])
    endpoint = match[2]
    if re.fullmatch(r"git/(?:commits|trees)/[a-f0-9]{40}", endpoint):
        return path
    contents = re.fullmatch(r"contents/(.+)\?ref=([a-f0-9]{40})", endpoint)
    require(contents is not None, "invalid_github_path")
    _source_path(contents[1])
    return path


def _pinned_regular_blob(prefix, commit, source_path, get_json):
    """Walk exact Git components; Contents alone can dereference symlinks."""
    root = commit.get("tree")
    require(isinstance(root, dict), "invalid_github_tree")
    tree_sha = sha(root.get("sha"), 40)
    parts = source_path.split("/")
    for index, part in enumerate(parts):
        tree = get_json(f"{prefix}/git/trees/{tree_sha}")
        require(
            isinstance(tree, dict)
            and tree.get("sha") == tree_sha
            and tree.get("truncated") is False
            and isinstance(tree.get("tree"), list),
            "invalid_github_tree",
        )
        matches = [
            entry for entry in tree["tree"] if isinstance(entry, dict) and entry.get("path") == part
        ]
        require(len(matches) == 1, "github_source_entry_missing_or_ambiguous")
        entry = matches[0]
        entry_sha = sha(entry.get("sha"), 40)
        if index == len(parts) - 1:
            require(
                entry.get("type") == "blob" and entry.get("mode") in ("100644", "100755"),
                "github_source_not_regular",
            )
            return entry_sha
        require(
            entry.get("type") == "tree" and entry.get("mode") == "040000",
            "github_source_not_directory",
        )
        tree_sha = entry_sha
    raise Refused("invalid_source_path")


def _scope_parts(value, *, directory=False):
    """Portable component identity; retain original spelling in the proposal."""
    require(isinstance(value, str) and 0 < len(value) <= 1024, "invalid_scope_path")
    if directory:
        require(value.endswith("/"), "prefix_requires_directory")
        value = value[:-1]
    parts = value.split("/")
    for part in parts:
        # Protecting .git is legitimate; proposed edits to it remain forbidden.
        if part.casefold() != ".git":
            file_path(part)
    return tuple(part.casefold() for part in parts)


def _scope_prefixes(values):
    result = [_scope_parts(value, directory=True) for value in values]
    require(len(set(result)) == len(result), "duplicate_scope_path")
    return result


def validate_planning_document(document, repository):
    """Validate every proposed task, without constructing approval or execution."""
    validate_repository(repository)
    spec = keys(document, {"schema_version", "plan", "tasks"})
    require(
        type(spec["schema_version"]) is int and spec["schema_version"] == 1,
        "unsupported_planning_ingest_schema",
    )
    plan = Plan.validate_data(spec["plan"])
    require(plan["repository"] == repository, "planning_repository_mismatch")
    code = _scope_prefixes(plan["boundaries"]["code_prefixes"])
    protected = _scope_prefixes(plan["boundaries"]["protected_prefixes"])
    protected_files = [_scope_parts(p) for p in plan["validation"]["protected_files"]]
    require(len(set(protected_files)) == len(protected_files), "duplicate_scope_path")
    milestone_ids = {x["id"] for x in plan["milestones"]}
    tasks = spec["tasks"]
    require(isinstance(tasks, list) and 0 < len(tasks) <= 100, "invalid_planning_tasks")
    bundles, spellings = {}, {}
    plan_hash = digest(plan)
    for raw in tasks:
        item = keys(raw, {"milestone_id", "instruction", "allowed_paths", "required_checks"})
        mid = item["milestone_id"]
        require(
            isinstance(mid, str) and mid in milestone_ids and mid not in bundles,
            "invalid_or_duplicate_planning_task",
        )
        for filepath in paths(item["allowed_paths"]):
            parts = _scope_parts(filepath)
            require(
                any(len(parts) > len(p) and parts[: len(p)] == p for p in code)
                and not any(parts[: len(p)] == p for p in protected)
                and parts not in protected_files,
                "planning_task_out_of_scope",
            )
            require(parts not in spellings or spellings[parts] == filepath, "ambiguous_task_path")
            spellings[parts] = filepath
        checks = item["required_checks"]
        require(isinstance(checks, list), "invalid_required_checks")
        require(
            {
                c.get("name")
                for c in checks
                if isinstance(c, dict) and isinstance(c.get("name"), str)
            }
            == set(plan["validation"]["required_checks"]),
            "planning_check_mismatch",
        )
        for check in checks:
            require(
                isinstance(check, dict)
                and check.get("workflow_path") == plan["validation"]["workflow_path"]
                and check.get("workflow_sha256") == plan["validation"]["workflow_sha256"],
                "planning_workflow_mismatch",
            )
        bundles[mid] = prepare_task(
            {
                "schema_version": 1,
                "plan_sha256": plan_hash,
                "milestone_id": mid,
                "attempt_id": f"proposal-{mid}",
                "repository": repository,
                "baseline_sha": plan["baseline_revision"],
                "instruction": item["instruction"],
                "allowed_paths": item["allowed_paths"],
                "required_checks": checks,
            }
        )
    require(set(bundles) == milestone_ids, "missing_planning_task")
    return plan, bundles


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
    expected_blob = _pinned_regular_blob(prefix, commit, source_path, get_json)
    response = get_json(f"{prefix}/contents/{source_path}?ref={commit_sha}")
    content, blob_sha = _github_blob(response, source_path)
    require(blob_sha == expected_blob, "github_tree_blob_mismatch")
    document = _document(content)
    plan, bundles = validate_planning_document(document, repository)
    require(milestone_id in bundles, "unknown_planning_milestone")
    bundle = bundles[milestone_id]
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


def validate_ingest_record(value):
    """Validate an untrusted persisted projection; never authenticate its claims."""
    record = keys(
        value,
        {
            "schema_version",
            "status",
            "execution_authority",
            "approval",
            "ingestion_id",
            "source",
            "milestone_id",
            "dependencies",
            "acceptance",
            "bundle",
        },
    )
    require(
        type(record["schema_version"]) is int and record["schema_version"] == 1,
        "invalid_ingest_record",
    )
    require(
        record["status"] == "pinned_plan_proposal"
        and record["execution_authority"] is False
        and record["approval"] is None,
        "ingest_cannot_grant_authority",
    )
    source = keys(
        record["source"],
        {"repository", "commit_sha", "path", "git_blob_sha", "content_sha256", "plan_sha256"},
    )
    validate_repository(source["repository"])
    _source_path(source["path"])
    for field in ("commit_sha", "git_blob_sha"):
        sha(source[field], 40)
    for field in ("content_sha256", "plan_sha256"):
        sha(source[field])
    mid = record["milestone_id"]
    require(isinstance(mid, str) and _MILESTONE.fullmatch(mid), "invalid_milestone_identity")
    identity = sha(record["ingestion_id"])
    require(
        identity
        == digest(
            {
                "repository": source["repository"],
                "commit_sha": source["commit_sha"],
                "path": source["path"],
                "milestone_id": mid,
            }
        ),
        "invalid_ingest_identity",
    )
    task = validate_bundle(record["bundle"])["request"]
    require(
        task["repository"] == source["repository"]
        and task["plan_sha256"] == source["plan_sha256"]
        and task["milestone_id"] == mid
        and task["attempt_id"] == f"proposal-{mid}",
        "ingest_bundle_binding_mismatch",
    )
    deps = record["dependencies"]
    require(
        isinstance(deps, list)
        and len(deps) < 100
        and all(isinstance(d, str) and _MILESTONE.fullmatch(d) and d != mid for d in deps)
        and len(set(deps)) == len(deps),
        "invalid_ingest_dependencies",
    )
    criteria = record["acceptance"]
    require(isinstance(criteria, dict) and bool(criteria), "missing_acceptance")
    strings(list(criteria))
    for description in criteria.values():
        strings([description])
    payload = canonical(record)
    require(len(payload.encode("utf-8")) < MAX_RESPONSE, "ingest_record_too_large")
    return json.loads(payload)


def load_ingest_record(path: Path):
    """Read only explicit regular local proposal data, with no trust promotion."""
    require(not str(path).replace("\\", "/").startswith("//"), "network_directory_refused")
    path = Path(path).absolute()
    require(
        all(not p.is_symlink() and not p.is_junction() for p in (path, *path.parents)),
        "linked_storage_directory_refused",
    )
    require(stat.S_ISREG(path.stat().st_mode), "regular_ingest_record_required")
    with path.open("rb") as stream:
        raw = stream.read(MAX_RESPONSE + 1)
    require(len(raw) < MAX_RESPONSE, "ingest_record_too_large")
    return validate_ingest_record(_document_response(raw))


def store_idempotently(record, output_dir: Path):
    """Persist exactly one immutable proposal per identity, atomically if supported."""
    record = validate_ingest_record(record)
    identity = record["ingestion_id"]
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
            require(load_ingest_record(target) == record, "ingestion_conflict")
            require(target.read_bytes() == payload, "ingestion_conflict")
        return {"outcome": outcome, "ingestion_id": identity, "record_path": str(target)}
    except (OSError, ValueError) as error:
        if isinstance(error, Refused):
            raise
        raise Refused("storage_write_failed") from None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
