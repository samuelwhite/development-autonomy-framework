"""Pinned A7-only generation. Never writes a production inspector/header path."""

import hashlib
import sys
from pathlib import Path

import instrument_fixture

INSPECTOR_SHA = "53233a1165e2044858979a1c19eb13addfa454863ce834d01db586926114063d"
ANCHOR = b"        auto first = snapshot(*s, 0), second = snapshot(*s, 1);"
BOUNDARY = (
    b"        auto first = snapshot(*s, 0);\n"
    b"        a7::boundary(first);\n"
    b"        auto second = snapshot(*s, 1);"
)


def inspector(raw):
    canonical = raw.replace(b"\r\n", b"\n")
    if raw not in (canonical, canonical.replace(b"\n", b"\r\n")):
        raise ValueError("a7_mixed_newlines")
    if hashlib.sha256(canonical).hexdigest() != INSPECTOR_SHA:
        raise ValueError("a7_exact_inspector_source")
    if canonical.count(ANCHOR) != 1 or b"a7::" in canonical:
        raise ValueError("a7_unique_boundary")
    generated = canonical.replace(ANCHOR, BOUNDARY)
    if generated.count(BOUNDARY) != 1 or generated.replace(BOUNDARY, ANCHOR) != canonical:
        raise ValueError("a7_complete_inverse")
    if b"\r\n" in raw:
        generated = generated.replace(b"\n", b"\r\n")
    return generated


def instrument(raw):
    generated = instrument_fixture.instrument(raw)
    for before, after in (
        (b"a4::beforeResume", b"a7::beforeResume"),
        (b"a4::ControlComplete", b"a7::ControlComplete"),
        (b"a4_controlled_stop", b"a7_controlled_stop"),
    ):
        if generated.count(before) != 1:
            raise ValueError("a7_harness_hook_identity")
        generated = generated.replace(before, after)
    return generated


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[2]
    output = Path(sys.argv[1]).resolve()
    if not output.is_relative_to(repo / "dist"):
        raise ValueError("a7_build_directory_only")
    sources = {
        "a7-fixture-harness.h": instrument(
            (repo / "desktop/native-foundation/harness.cpp").read_bytes()
        ),
        "a7-suspended-inspection.generated.h": inspector(
            Path(__file__).with_name("suspended-inspection.h").read_bytes()
        ),
        "a7-inspector-baseline.h": Path(__file__).with_name("suspended-inspection.h").read_bytes(),
    }
    for name, raw in sources.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
    with (output / "a7-preprocess-baseline.cpp").open("x", encoding="utf-8") as stream:
        stream.write('#include "a7-inspector-baseline.h"\n')
