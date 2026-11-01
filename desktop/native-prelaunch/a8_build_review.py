"""Independent source/input/preprocessor review. Reads files; never runs a binary."""

import hashlib
import json
import sys
from pathlib import Path

from a7_build_review import normalized, section, tokens
from instrument_a8 import TRANSFORMS, harness_inverse, inspector, inverse

SOURCE = Path(__file__).resolve().parent
LAUNCHER_SHA = "2529f55defa04e0e758007628d5af52d211cbc0e756c4bf2045f440875d6739e"


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def launcher():
    baseline = (SOURCE / "a7-fixture-host.cpp").read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(baseline).hexdigest() != LAUNCHER_SHA:
        raise ValueError("a8_launcher_baseline")
    expected = (
        baseline.replace(b"A7-only", b"A8-only")
        .replace(b"a7", b"a8")
        .replace(b"a8-fixture-inspection.h", b"a8-stall-control.h")
    )
    line = (
        b'        a8::emit("case", a8::sequence == 1 ? 0 : 15); '
        b'a8::emit("sequence", a8::sequence);\n'
    )
    if expected.count(line) != 1 or (SOURCE / "a8-fixture-host.cpp").read_bytes().replace(
        b"\r\n", b"\n"
    ) != expected.replace(line, b""):
        raise ValueError("a8_original_three_pipe_launcher")
    return identity(SOURCE / "a8-fixture-host.cpp")


def inverse_tokens(value):
    for before, after in reversed(TRANSFORMS):
        old, new = tokens(before.decode()), tokens(after.decode())
        positions = [i for i in range(len(value)) if value[i : i + len(new)] == new]
        if len(positions) != 1:
            raise ValueError("a8_preprocessed_inverse_anchor")
        i = positions[0]
        value = value[:i] + old + value[i + len(new) :]
    return value


def dependencies(build, unit, phase):
    data = json.loads((build / f"{unit}.{phase}.json").read_text("utf-8-sig"))["Data"]
    source = SOURCE / f"{unit}.cpp"
    if normalized(data["Source"]) != normalized(source):
        raise ValueError("a8_actual_compilation_unit")
    includes = data["Includes"]
    if (
        data.get("ImportedModules")
        or data.get("ImportedHeaderUnits")
        or data.get("ProvidedModule")
        or data.get("PCH")
    ):
        raise ValueError("a8_unexpected_module_or_pch")
    required = (
        {
            build / "a8-suspended-inspection.generated.h",
            build / "a8-fixture-harness.h",
            build / "probe-identity.h",
            SOURCE / "a8-stall-control.h",
            SOURCE / "identity.h",
            SOURCE / "handle-diagnostic.h",
            SOURCE.parent / "native-foundation/readiness.h",
            SOURCE.parent / "native-foundation/sha256.h",
        }
        if unit == "a8-fixture-host"
        else set()
    )
    if not {normalized(p) for p in required}.issubset(set(map(normalized, includes))):
        raise ValueError("a8_actual_includes_missing")
    approved_local = {normalized(p) for p in required}
    # SDK packing headers legitimately repeat. Generated project headers remain
    # unique even when the diagnostic build lives outside the source checkout.
    resolved = [normalized(Path(name).resolve()) for name in includes]
    if any(resolved.count(name) != 1 for name in approved_local):
        raise ValueError("a8_duplicate_or_missing_project_include")
    if normalized(source) in resolved:
        raise ValueError("a8_compilation_unit_cannot_be_an_include")
    inventory = {}
    for name in [data["Source"], *includes]:
        path = Path(name).resolve()
        # SDK/toolset inputs are inventoried; every project include has a closed path.
        norm = normalized(path)
        if norm != normalized(source) and norm not in approved_local:
            trusted = (
                "c:/program files (x86)/microsoft visual studio/18/buildtools/"
                "vc/tools/msvc/14.50.35717/include/",
                "c:/program files (x86)/windows kits/10/include/10.0.26100.0/ucrt/",
                "c:/program files (x86)/windows kits/10/include/10.0.26100.0/shared/",
                "c:/program files (x86)/windows kits/10/include/10.0.26100.0/um/",
            )
            if not norm.startswith(trusted):
                raise ValueError("a8_unexpected_dependency_path")
        if any(
            norm.endswith("/" + name)
            for name in ("suspended-inspection.h", "a8-inspector-baseline.h")
        ):
            raise ValueError("a8_production_or_baseline_include")
        inventory[str(path)] = identity(path)
    return inventory


def review(build, compiled=False):
    baseline = build / "a8-inspector-baseline.h"
    generated = build / "a8-suspended-inspection.generated.h"
    raw = (SOURCE / "suspended-inspection.h").read_bytes()
    if (
        baseline.read_bytes() != raw
        or generated.read_bytes() != inspector(raw)
        or inverse(generated.read_bytes()) != raw
    ):
        raise ValueError("a8_full_source_inverse")
    harness_inverse(
        (build / "a8-fixture-harness.h").read_bytes(),
        (SOURCE.parent / "native-foundation/harness.cpp").read_bytes(),
    )
    normal = section(
        (build / "a8-preprocess-baseline.i").read_text("utf-8-sig"), baseline.resolve()
    )
    actual = section((build / "a8-fixture-host.i").read_text("utf-8-sig"), generated.resolve())
    if inverse_tokens(actual) != normal:
        raise ValueError("a8_complete_preprocessed_inverse")
    inputs = dependencies(build, "a8-fixture-host", "preprocess")
    if compiled:
        prior = json.loads((build / "a8-input-review.json").read_text("utf-8"))
        if prior["compiler_inputs"] != inputs:
            raise ValueError("a8_changed_inputs_after_preflight")
        if inputs != dependencies(build, "a8-fixture-host", "compiled"):
            raise ValueError("a8_preprocess_compile_inventory_difference")
        inspection = (build / "a8-fixture-host.inspection.txt").read_text("utf-8-sig")
        if any(name in inspection for name in ("ResumeThread", "TerminateThread")):
            raise ValueError("a8_forbidden_import")
        for name in ("SignalObjectAndWait", "TerminateJobObject", "WaitForSingleObject"):
            if name not in inspection:
                raise ValueError("a8_required_import")
        probe = dependencies(build, "handle-probe", "compiled")
        saved_probe = json.loads((build / "probe-input-review.json").read_text("utf-8"))
        if probe != saved_probe:
            raise ValueError("a8_probe_input_difference")
    return {
        "schema": "daf-a8-build-review/v1",
        "native_executions": 0,
        "compiled": compiled,
        "inspector": identity(baseline),
        "generated": identity(generated),
        "launcher": launcher(),
        "byte_inverse_exact": True,
        "harness_inverse_exact": True,
        "inspect_and_supervisor_token_inverse_exact": True,
        "normal_token_count": len(normal),
        "normal_tokens_sha256": hashlib.sha256(json.dumps(normal).encode()).hexdigest(),
        "actual_tokens_sha256": hashlib.sha256(json.dumps(actual).encode()).hexdigest(),
        "compiler_inputs": inputs,
    }


if __name__ == "__main__":
    build = Path(sys.argv[1]).resolve()
    if sys.argv[2:] == ["--probe"]:
        result = dependencies(build, "handle-probe", "preprocess")
        with (build / "probe-input-review.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, sort_keys=True)
        raise SystemExit(0)
    compiled = sys.argv[2:] == ["--compiled"]
    result = review(build, compiled)
    target = build / ("a8-build-review.json" if compiled else "a8-input-review.json")
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key != "compiler_inputs"}))
