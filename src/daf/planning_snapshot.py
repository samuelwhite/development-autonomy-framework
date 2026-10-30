"""Immutable full-source planning snapshots. Consistency is never authentication."""

import base64
import hashlib
import os
import re
import stat
import tempfile
from itertools import islice
from pathlib import Path

from .contract import Refused, canonical, digest, keys, require, sha
from .github_planning import (
    MAX_CONTENT,
    _document,
    _document_response,
    _source_path,
    propose_milestone,
    validate_planning_document,
)
from .supervised_handoff import validate_repository

MAX_SNAPSHOT = 512 * 1024
MAX_HISTORY = 100
MAX_STORAGE = 32 * 1024 * 1024
VERIFICATION = "local_source_observation_requirements_unverified"


def validate_source(value):
    source = keys(value, {"repository", "commit_sha", "path"})
    validate_repository(source["repository"])
    sha(source["commit_sha"], 40)
    _source_path(source["path"])
    return source


def make_snapshot(source, content):
    source = validate_source(source)
    plan, bundles = validate_planning_document(_document(content), source["repository"])
    blob = hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\0" + content, usedforsecurity=False
    ).hexdigest()
    provenance = {
        **source,
        "git_blob_sha": blob,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "plan_sha256": digest(plan),
    }
    snapshot = {
        "schema_version": 1,
        "snapshot_id": digest(source),
        "status": "pinned_plan_proposal",
        "approval": None,
        "execution_authority": False,
        "spending_authority": False,
        "verification": VERIFICATION,
        "source": provenance,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "proposals": [
            propose_milestone(provenance, plan, bundles, m["id"]) for m in plan["milestones"]
        ],
    }
    require(len(canonical(snapshot).encode()) < MAX_SNAPSHOT, "snapshot_too_large")
    return snapshot


def validate_snapshot(value):
    snapshot = keys(
        value,
        {
            "schema_version",
            "snapshot_id",
            "status",
            "approval",
            "execution_authority",
            "spending_authority",
            "verification",
            "source",
            "content_base64",
            "proposals",
        },
    )
    require(type(snapshot["schema_version"]) is int, "invalid_snapshot")
    require(
        snapshot["execution_authority"] is False
        and snapshot["spending_authority"] is False
        and snapshot["approval"] is None,
        "snapshot_cannot_grant_authority",
    )
    source = keys(
        snapshot["source"],
        {
            "repository",
            "commit_sha",
            "path",
            "git_blob_sha",
            "content_sha256",
            "plan_sha256",
        },
    )
    encoded = snapshot["content_base64"]
    require(isinstance(encoded, str) and len(encoded) <= 4 * MAX_CONTENT, "invalid_snapshot")
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise Refused("invalid_snapshot") from None
    expected = make_snapshot({k: source[k] for k in ("repository", "commit_sha", "path")}, content)
    require(canonical(snapshot) == canonical(expected), "snapshot_conflict")
    return expected


def project_snapshot(value):
    """Revalidate the entire source, then produce a bounded plain-data review view."""
    snapshot = validate_snapshot(value)
    plan = _document(base64.b64decode(snapshot["content_base64"]))["plan"]
    return {
        "id": snapshot["snapshot_id"],
        "status": snapshot["status"],
        "approval": None,
        "executionAuthority": False,
        "spendingAuthority": False,
        "verification": VERIFICATION,
        "source": snapshot["source"],
        "project": plan["project"],
        "planId": plan["plan_id"],
        "version": plan["version"],
        "baseline": plan["baseline_revision"],
        "scope": plan["scope"],
        "deliverables": plan["deliverables"],
        "requirements": canonical(
            {
                k: plan[k]
                for k in (
                    "boundaries",
                    "validation",
                    "budgets",
                    "recovery",
                    "notifications",
                    "actions",
                )
            }
        ),
        "milestones": [
            {
                "id": milestone["id"],
                "dependencies": milestone["depends_on"],
                "deliverable": milestone["deliverable"],
                "acceptance": milestone["acceptance"],
                "proposalId": proposal["ingestion_id"],
                "taskSHA256": proposal["bundle"]["task_sha256"],
                "instruction": proposal["bundle"]["request"]["instruction"],
                "allowedPaths": proposal["bundle"]["request"]["allowed_paths"],
                "checks": canonical(proposal["bundle"]["request"]["required_checks"]),
            }
            for milestone, proposal in zip(plan["milestones"], snapshot["proposals"], strict=True)
        ],
    }


def safe_local(path):
    require(not str(path).replace("\\", "/").startswith("//"), "local_storage_required")
    absolute = Path(path).absolute()
    require(
        all(not p.is_symlink() and not p.is_junction() for p in (absolute, *absolute.parents)),
        "linked_storage_refused",
    )
    return absolute


def storage_folder(folder):
    folder = safe_local(folder)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(folder.is_dir(), "storage_unavailable")
    return folder


def read_snapshot(folder, identity):
    sha(identity)
    path = safe_local(storage_folder(folder) / f"{identity}.json")
    require(stat.S_ISREG(path.stat().st_mode), "regular_snapshot_required")
    with path.open("rb") as stream:
        raw = stream.read(MAX_SNAPSHOT + 1)
    require(len(raw) < MAX_SNAPSHOT, "snapshot_too_large")
    value = validate_snapshot(_document_response(raw))
    require(value["snapshot_id"] == identity, "snapshot_identity_mismatch")
    return value


def history(folder):
    folder = storage_folder(folder)
    entries = []
    # Include unexpected files in the cap, and never scan an unbounded directory.
    for entry in folder.iterdir():
        entries.append(entry)
        require(len(entries) <= MAX_HISTORY + 100, "storage_limit")
    results, damaged = [], []
    for entry in sorted(entries, key=lambda p: p.name):
        if re.fullmatch(r"[a-f0-9]{64}\.json", entry.name):
            try:
                value = read_snapshot(folder, entry.stem)
                view = project_snapshot(value)
                results.append(
                    {
                        "id": view["id"],
                        "project": view["project"],
                        "planId": view["planId"],
                        "source": view["source"],
                    }
                )
            except (Refused, OSError, ValueError, TypeError, RecursionError):
                damaged.append(entry.stem)
    require(len(results) + len(damaged) <= MAX_HISTORY, "storage_limit")
    return {"imports": results, "damaged": damaged}


def save_snapshot(folder, value):
    value = validate_snapshot(value)
    folder = storage_folder(folder)
    identity = value["snapshot_id"]
    target = safe_local(folder / f"{identity}.json")
    payload = (canonical(value) + "\n").encode()
    if target.exists():
        require(
            canonical(read_snapshot(folder, identity)) + "\n" == payload.decode(),
            "snapshot_conflict",
        )
        require(target.read_bytes() == payload, "snapshot_conflict")
        return "already_present"
    entries = list(islice(folder.iterdir(), MAX_HISTORY + 101))
    require(len(entries) < MAX_HISTORY, "storage_limit")
    size = 0
    for entry in entries:
        safe_local(entry)
        try:
            info = entry.stat()
        except FileNotFoundError:
            # Another identical import may have just removed its staging link.
            require(entry.name.startswith(".incomplete-"), "storage_changed")
            continue
        require(stat.S_ISREG(info.st_mode), "regular_snapshot_required")
        size += info.st_size
    require(size + len(payload) <= MAX_STORAGE, "storage_limit")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".incomplete-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)  # Atomic publish of complete bytes; never overwrite.
        except FileExistsError:
            require(
                read_snapshot(folder, identity) == value and target.read_bytes() == payload,
                "snapshot_conflict",
            )
            return "already_present"
        return "imported"
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
