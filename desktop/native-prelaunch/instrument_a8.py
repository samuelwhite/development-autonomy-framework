"""A8 diagnostic-only transformations; complete byte inverses, no native execution."""

import hashlib
import sys
from pathlib import Path

import instrument_harness
from instrument_a7 import INSPECTOR_SHA

TRANSFORMS = (
    (
        b"inline void inspect(std::shared_ptr<State> s) {",
        b"inline void inspect(std::shared_ptr<State> s, std::shared_ptr<a8::Context> a8Context) {",
    ),
    (
        b"    std::thread inspector(inspect, state);",
        b"    std::thread inspector(inspect, state, a8::context);",
    ),
    (
        b"        auto first = snapshot(*s, 0), second = snapshot(*s, 1);",
        b"        auto first = snapshot(*s, 0);\n"
        b"        a8::boundary(*s, first, a8Context);\n"
        b"        auto second = snapshot(*s, 1);",
    ),
    (
        b"    ULONGLONG start = GetTickCount64();",
        b"    ULONGLONG start = GetTickCount64();\n    a8::started(start);",
    ),
    (
        b"    DWORD inspectorWait = WaitForSingleObject(inspector.native_handle(), DeadlineMs);",
        b"    DWORD inspectorWait = WaitForSingleObject(inspector.native_handle(), DeadlineMs);\n"
        b"    DWORD a8WaitError = inspectorWait == a8::FailedWait ? GetLastError() : 0;\n"
        b"    const auto a8WaitQpc = a8::clock();",
    ),
    (
        b"    if (!finished || deadline) state->stop.store(true);",
        b"    if (!finished || deadline) state->stop.store(true);\n"
        b"    a8::decision(*state, a8WaitError, a8WaitQpc, deadline);",
    ),
    (
        b"    ULONGLONG killing = GetTickCount64();",
        b"    ULONGLONG killing = GetTickCount64();\n    a8::killing();",
    ),
    (
        b"    ULONGLONG latency = GetTickCount64() - killing;",
        b"    ULONGLONG latency = GetTickCount64() - killing;\n    a8::terminated();",
    ),
    (
        b"    unsigned count = state->published.load(std::memory_order_acquire);",
        b"    unsigned count = state->published.load(std::memory_order_acquire);\n"
        b"    a8::published(count);",
    ),
)


def canonical(raw):
    value = raw.replace(b"\r\n", b"\n")
    if raw not in (value, value.replace(b"\n", b"\r\n")):
        raise ValueError("a8_mixed_newlines")
    return value


def inverse(raw):
    result = canonical(raw)
    for before, after in reversed(TRANSFORMS):
        if result.count(after) != 1:
            raise ValueError("a8_inverse_anchor")
        result = result.replace(after, before)
    if b"a8::" in result or hashlib.sha256(result).hexdigest() != INSPECTOR_SHA:
        raise ValueError("a8_inverse_identity")
    return result.replace(b"\n", b"\r\n") if b"\r\n" in raw else result


def inspector(raw):
    result = canonical(raw)
    if hashlib.sha256(result).hexdigest() != INSPECTOR_SHA:
        raise ValueError("a8_original_identity")
    for before, after in TRANSFORMS:
        if result.count(before) != 1:
            raise ValueError("a8_unique_anchor")
        result = result.replace(before, after)
    if b"\r\n" in raw:
        result = result.replace(b"\n", b"\r\n")
    if inverse(result) != raw:
        raise ValueError("a8_full_inverse")
    return result


def instrument(raw):
    result = instrument_harness.instrument(raw)
    # Keep the ORIGINAL typed success catch. Only the pre-resume wrapper differs.
    before, after = (
        b"a3::beforeResume(process, thread, job)",
        b"a8::beforeResume(process, thread, job)",
    )
    if result.count(before) != 1:
        raise ValueError("a8_harness_anchor")
    return result.replace(before, after)


def harness_inverse(generated, raw):
    if generated != instrument(raw):
        raise ValueError("a8_harness_difference")
    restored = generated.replace(b"a8::beforeResume", b"a3::beforeResume")
    for _, insertion in reversed(instrument_harness.INSERTIONS):
        if restored.count(insertion) != 1:
            raise ValueError("a8_harness_inverse_anchor")
        restored = restored.replace(insertion, b"")
    if restored != raw:
        raise ValueError("a8_harness_inverse")
    return restored


def generate(output):
    source = Path(__file__).resolve().parent
    repo = source.parents[1]
    if not output.is_relative_to(repo / "dist"):
        raise ValueError("a8_build_directory_only")
    baseline = (source / "suspended-inspection.h").read_bytes()
    harness = (source.parent / "native-foundation/harness.cpp").read_bytes()
    for name, raw in {
        "a8-suspended-inspection.generated.h": inspector(baseline),
        "a8-inspector-baseline.h": baseline,
        "a8-fixture-harness.h": instrument(harness),
        "a8-preprocess-baseline.cpp": b'#include "a8-inspector-baseline.h"\n',
    }.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)


if __name__ == "__main__":
    generate(Path(sys.argv[1]).resolve())
