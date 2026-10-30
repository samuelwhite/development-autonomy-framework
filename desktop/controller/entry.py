"""Fixed one-request stdio entry point, with parent-pipe and hard-deadline watchdogs."""

import json
import os
import sys
import threading
from pathlib import Path

# Fixed bundled code directory only; -I -S ignores user modules and site configuration.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from service import MAX_INPUT, MAX_OUTPUT, SCHEMA, perform, safe_error, validate  # noqa: E402

from daf.contract import Refused, require  # noqa: E402
from daf.github_planning import _document_response  # noqa: E402


def main():
    request_id, operation = "0" * 32, ""
    # Includes DNS/read stalls and storage; parent independently kills at 35 seconds.
    timer = threading.Timer(30, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        require(len(sys.argv) == 2, "invalid_request")
        raw = sys.stdin.buffer.readline(MAX_INPUT + 1)
        require(len(raw) <= MAX_INPUT and raw.endswith(b"\n"), "invalid_request")
        request = _document_response(raw)
        validate(request, SCHEMA["$defs"]["request"])
        request_id, operation = request["requestId"], request["operation"]

        def parent_pipe():
            # EOF means the parent exited. Any extra input violates one-request framing.
            sys.stdin.buffer.read(1)
            os._exit(125)

        threading.Thread(target=parent_pipe, daemon=True).start()
        response = perform(request, Path(sys.argv[1]))
    except (Refused, OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        response = {
            "protocol": 1,
            "requestId": request_id,
            "outcome": "refused",
            "error": {"code": safe_error(error, operation)},
        }
    validate(response, SCHEMA["$defs"]["response"])
    encoded = (json.dumps(response, ensure_ascii=True, allow_nan=False) + "\n").encode()
    require(len(encoded) <= MAX_OUTPUT, "response_too_large")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    # Avoid interpreter shutdown waiting for the daemon's blocked buffered input lock.
    os._exit(0)


if __name__ == "__main__":
    main()
