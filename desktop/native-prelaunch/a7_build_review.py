"""Review actual MSVC dependencies/preprocessing without executing a binary."""

import hashlib
import json
import re
import sys
from pathlib import Path

from instrument_a7 import ANCHOR, BOUNDARY, INSPECTOR_SHA, inspector


def normalized(path):
    return str(path).replace("\\", "/").casefold()


def tokens(text):
    # Preserve string/character literals; only token-boundary whitespace is ignored.
    return re.findall(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\w+|[^\s]', text)


def section(text, path):
    selected = False
    lines = []
    for line in text.splitlines():
        directive = re.fullmatch(r'\s*#(?:line)?\s+\d+\s+"(.*)"\s*', line)
        if directive:
            selected = normalized(directive[1]) == normalized(path)
        elif selected:
            lines.append(line)
    if not lines:
        raise ValueError("a7_missing_actual_preprocessed_header")
    return tokens("\n".join(lines))


def inverse_tokens(value):
    changed, original = tokens(BOUNDARY.decode()), tokens(ANCHOR.decode())
    positions = [i for i in range(len(value)) if value[i : i + len(changed)] == changed]
    if len(positions) != 1:
        raise ValueError("a7_preprocessed_unique_boundary")
    at = positions[0]
    return value[:at] + original + value[at + len(changed) :]


def review(build):
    generated = build / "a7-suspended-inspection.generated.h"
    baseline = build / "a7-inspector-baseline.h"
    raw = baseline.read_bytes()
    if generated.read_bytes() != inspector(raw):
        raise ValueError("a7_generated_source_difference")
    dependency = json.loads(
        (build / "a7-fixture-host.dependencies.json").read_text(encoding="utf-8-sig")
    )
    includes = dependency["Data"]["Includes"]
    if normalized(dependency["Data"]["Source"]) != normalized(
        Path(__file__).with_name("a7-fixture-host.cpp").resolve()
    ):
        raise ValueError("a7_unexpected_compilation_unit")
    names = [normalized(p) for p in includes]
    if names.count(normalized(generated.resolve())) != 1:
        raise ValueError("a7_actual_generated_include")
    forbidden = ("/suspended-inspection.h", "/a7-inspector-baseline.h")
    if any(name.endswith(forbidden) for name in names):
        raise ValueError("a7_production_or_baseline_header_in_fixture")
    actual = section(
        (build / "a7-fixture-host.i").read_text(encoding="utf-8-sig"), generated.resolve()
    )
    normal = section(
        (build / "a7-preprocess-baseline.i").read_text(encoding="utf-8-sig"), baseline.resolve()
    )
    if inverse_tokens(actual) != normal:
        raise ValueError("a7_preprocessed_semantics_difference")
    return {
        "schema": "daf-a7-build-review/v1",
        "original_canonical_sha256": INSPECTOR_SHA,
        "original_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "generated_raw_sha256": hashlib.sha256(generated.read_bytes()).hexdigest(),
        "inverse_source_exact": True,
        "actual_include_verified": True,
        "preprocessed_inverse_exact": True,
        "original_preprocessed_tokens": len(normal),
        "original_preprocessed_sha256": hashlib.sha256(json.dumps(normal).encode()).hexdigest(),
        "generated_preprocessed_sha256": hashlib.sha256(json.dumps(actual).encode()).hexdigest(),
        "native_executions": 0,
    }


if __name__ == "__main__":
    build = Path(sys.argv[1]).resolve()
    result = review(build)
    with (build / "a7-build-review.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result))
