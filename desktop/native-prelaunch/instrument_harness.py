"""Exactly two diagnostic-only insertions into the hash-pinned accepted host."""

import hashlib
import sys
from pathlib import Path

ACCEPTED = "deb2bf8aff650db0fdfea89939c402b507308b60bd5ed93cd5f9df9eb123a5ee"
INSERTIONS = (
    (
        b'        check(ResumeThread(thread) != (DWORD)-1, "resume");',
        b"        a3::beforeResume(process, thread, job);\n",
    ),
    (
        b"    } catch (const std::string&)",
        b"    } catch (const a3::FeasibilityComplete&) { result = 0; "
        b'event("a3_controlled_stop", 1);\n',
    ),
)


def instrument(raw):
    # Git may check text out as CRLF. Validate reviewed LF content, preserve raw bytes.
    if hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() != ACCEPTED:
        raise ValueError("accepted_harness_identity")
    result = raw
    for marker, insertion in INSERTIONS:
        if result.count(marker) != 1:
            raise ValueError("instrumentation_marker")
        result = result.replace(marker, insertion + marker)
    return result


if __name__ == "__main__":
    with Path(sys.argv[2]).open("xb") as output:
        output.write(instrument(Path(sys.argv[1]).read_bytes()))
