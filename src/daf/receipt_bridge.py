"""Offline receipt CLI: explicit local inputs and JSON stdout; no repository writes."""

import argparse
import json
import stat
from pathlib import Path

from .contract import Refused, require
from .external_receipts import receipt_sha256, validate_external_receipt
from .supervised_handoff import MAX_BYTES, SUPPLIED, prepare_task, reconcile_receipt


def read_bytes(path: Path) -> bytes:
    # Refuse explicit UNC/device paths before even stat/lstat can contact a share.
    require(not str(path).replace("\\", "/").startswith("//"), "network_or_device_input_refused")
    path = path.absolute()
    require(
        not any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)),
        "linked_input_refused",
    )
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
        else:
            artifacts = {}
            for name, path in args.artifact:
                require(name not in artifacts, "duplicate_artifact_input")
                require(len(artifacts) < 32, "too_many_artifact_inputs")
                artifacts[name] = read_bytes(Path(path))
            result = reconcile_receipt(
                read_document(args.bundle),
                read_document(args.receipt),
                read_document(args.evidence),
                artifacts,
            )
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (Refused, OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        reason = str(error) if isinstance(error, Refused) else "invalid_or_unavailable_local_input"
        print(json.dumps({"outcome": "refused", "reason": reason}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
