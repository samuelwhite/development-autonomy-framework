"""Offline evaluation commands. No worker, credential or approval-service commands."""

import argparse
import json
import sqlite3
from pathlib import Path

from . import __version__
from .contract import Plan, Refused, read_json
from .preview import demonstrate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Create a new synthetic run and static dashboard")
    demo.add_argument("--output", type=Path, required=True)
    check = sub.add_parser(
        "validate-plan", help="Validate a schema-1 offline plan; grant no authority"
    )
    check.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "demo":
            result = demonstrate(args.output)
            print(json.dumps(result, indent=2))
        else:
            Plan.validate_data(read_json(args.path))
            print(json.dumps({"valid": True, "execution_authority": False}))
        return 0
    except (Refused, OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        # Never echo input, paths, exception messages or document contents.
        reason = str(error) if isinstance(error, Refused) else "invalid_or_unavailable_local_input"
        print(json.dumps({"outcome": "refused", "reason": reason}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
