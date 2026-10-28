"""Opt-in read-only public GitHub ingestion sidecar; not a DAF runtime controller.

Run from this source checkout. No credential discovery, token, redirect, retry,
worker dispatch, CI request, or write to a GitHub repository is supported.
"""

import argparse
import http.client
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from daf.contract import Refused, require  # noqa: E402
from daf.github_planning import (  # noqa: E402
    MAX_RESPONSE,
    _document_response,
    ingest_public_milestone,
    store_idempotently,
)

GITHUB_HOST = "api.github.com"


def get_public_github_json(path):
    """Two fixed GitHub REST GET endpoints; no arbitrary URLs or HTTP redirects."""
    require(isinstance(path, str) and path.startswith("/repos/"), "invalid_github_path")
    conn = http.client.HTTPSConnection(GITHUB_HOST, timeout=8)
    try:
        conn.request(
            "GET",
            path,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "daf-m1-pinned-planning/1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = conn.getresponse()
        require(response.status == 200, "public_github_read_failed")
        require(
            response.getheader("Content-Type", "").split(";")[0].strip().lower()
            == "application/json",
            "unexpected_github_content_type",
        )
        payload = response.read(MAX_RESPONSE + 1)
        require(len(payload) <= MAX_RESPONSE, "github_response_too_large")
        return _document_response(payload)
    except (OSError, http.client.HTTPException):
        raise Refused("public_github_read_failed") from None
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="Public GitHub owner/repository")
    parser.add_argument("--commit", required=True, help="Exact 40-character commit SHA")
    parser.add_argument("--path", required=True, help="Exact repository-relative JSON file path")
    parser.add_argument("--milestone", required=True, help="Milestone ID in the pinned plan")
    parser.add_argument("--output-dir", type=Path, required=True, help="Existing local directory")
    parser.add_argument(
        "--public-read", action="store_true", help="Explicit opt-in to two GitHub GETs"
    )
    args = parser.parse_args(argv)
    try:
        require(args.public_read, "explicit_public_read_required")
        record = ingest_public_milestone(
            args.repository,
            args.commit,
            args.path,
            args.milestone,
            get_json=get_public_github_json,
        )
        result = store_idempotently(record, args.output_dir)
        print(json.dumps({**result, "execution_authority": False}, sort_keys=True))
        return 0
    except (Refused, OSError, TypeError, ValueError, RecursionError) as error:
        reason = str(error) if isinstance(error, Refused) else "ingestion_unavailable"
        print(json.dumps({"outcome": "refused", "reason": reason}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
