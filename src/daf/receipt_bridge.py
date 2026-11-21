"""Offline receipt CLI with explicit local inputs and optional observation retention."""

import argparse
import json
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

from .contract import Refused, digest, require
from .external_receipts import receipt_sha256, validate_external_receipt
from .store import Store
from .supervised_handoff import (
    MAX_BYTES,
    SUPPLIED,
    interrupted_attempt,
    prepare_task,
    reconcile_receipt,
    recovery_observation,
    validate_interruption,
)


def local_path(path: Path) -> Path:
    # Refuse explicit UNC/device paths before even stat/lstat can contact a share.
    require(not str(path).replace("\\", "/").startswith("//"), "network_or_device_input_refused")
    path = path.absolute()
    require(
        not any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)),
        "linked_input_refused",
    )
    return path


def read_bytes(path: Path) -> bytes:
    path = local_path(path)
    require(stat.S_ISREG(path.stat().st_mode), "regular_input_required")
    with path.open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    require(len(content) <= MAX_BYTES, "document_too_large")
    return content


def read_document(path: Path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate_json_key")
            value[key] = item
        return value

    def nonfinite(_):
        raise Refused("nonfinite_json_value")

    return json.loads(
        read_bytes(path).decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite
    )


def journal_directory(path: Path, *names: str) -> Path:
    directory = local_path(path)
    require(directory.is_dir(), "local_journal_directory_required")
    for name in names:
        for suffix in ("", "-wal", "-shm", "-journal"):
            entry = local_path(directory / (name + suffix))
            require(not entry.exists() or entry.is_file(), "regular_journal_required")
    return directory


def open_journal(path: Path, *, existing: bool) -> Store:
    directory = journal_directory(path, "journal.sqlite", "stop-control.sqlite")
    if existing:
        require((directory / "journal.sqlite").is_file(), "observation_journal_not_found")
    return Store(directory)


def check_interruption(path: Path, fingerprint: str) -> None:
    database = journal_directory(path, "journal.sqlite") / "journal.sqlite"
    require(database.is_file(), "observation_journal_not_found")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        require(
            db.execute(
                "SELECT 1 FROM main.sqlite_schema WHERE type='table' AND name='observations'"
            ).fetchone()
            is not None,
            "observation_history_missing",
        )
        require(
            db.execute("SELECT body FROM main.observations WHERE hash=?", (fingerprint,)).fetchone()
            is None,
            "attempt_incomplete",
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="Export a proposed task, never an approval")
    prepare.add_argument("request", type=Path)
    validate = sub.add_parser("validate", help="Check a schema-1 unverified receipt")
    validate.add_argument("receipt", type=Path)
    reconcile = sub.add_parser("reconcile", help="Compare supplied PR/CI claims and artifact bytes")
    for name in ("bundle", "receipt", "evidence"):
        reconcile.add_argument(name, type=Path)
    reconcile.add_argument(
        "--artifact", nargs=2, action="append", default=[], metavar=("NAME", "LOCAL_FILE")
    )
    reconcile.add_argument("--journal", type=Path, help="Check retained interruptions first")
    interruption = sub.add_parser("record-interruption", help="Retain an incomplete attempt")
    interruption.add_argument("bundle", type=Path)
    interruption.add_argument("observation", type=Path)
    interruption.add_argument("--journal", type=Path, required=True)
    recovery = sub.add_parser("record-recovery", help="Append a separate cleanup observation")
    recovery.add_argument("bundle", type=Path)
    recovery.add_argument("observation", type=Path)
    recovery.add_argument("cleanup_evidence", type=Path)
    recovery.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_task(read_document(args.request))
        elif args.command == "validate":
            claim = validate_external_receipt(read_document(args.receipt))
            result = {
                "status": SUPPLIED,
                "receipt_sha256": receipt_sha256(claim),
                "execution_authority": False,
            }
        elif args.command == "reconcile":
            bundle = read_document(args.bundle)
            if args.journal is not None:
                check_interruption(args.journal, digest(interrupted_attempt(bundle)))
            artifacts = {}
            for name, path in args.artifact:
                require(name not in artifacts, "duplicate_artifact_input")
                require(len(artifacts) < 32, "too_many_artifact_inputs")
                artifacts[name] = read_bytes(Path(path))
            result = reconcile_receipt(
                bundle,
                read_document(args.receipt),
                read_document(args.evidence),
                artifacts,
            )
        else:
            attempt = interrupted_attempt(read_document(args.bundle))
            observation = read_document(args.observation)
            fingerprint = digest(attempt)
            result = {
                "attempt": attempt,
                "interruption_sha256": fingerprint,
                "acceptance": "refused",
                "automatic_retry": False,
                "fresh_approval_required": True,
                "execution_authority": False,
            }
            if args.command == "record-interruption":
                validate_interruption(attempt, observation)
                with closing(open_journal(args.journal, existing=False)) as journal:
                    journal.observe(attempt)
            else:
                recorded = recovery_observation(
                    fingerprint, observation, read_bytes(args.cleanup_evidence)
                )
                with closing(open_journal(args.journal, existing=True)) as journal:
                    require(
                        journal.observation(fingerprint) == attempt, "interruption_not_recorded"
                    )
                    result["recovery_sha256"] = journal.observe(recorded)
                result["recovery"] = recorded
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (
        Refused,
        OSError,
        sqlite3.Error,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
    ) as error:
        reason = str(error) if isinstance(error, Refused) else "invalid_or_unavailable_local_input"
        print(json.dumps({"outcome": "refused", "reason": reason}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
