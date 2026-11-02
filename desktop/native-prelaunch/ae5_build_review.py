"""Read-only review of frozen sources, complete inverses and actual compiler inputs."""

import hashlib
import json
import sys
from pathlib import Path

from a7_build_review import normalized, section
from ae51_contract import source_gates
from instrument_a7 import INSPECTOR_SHA
from instrument_ae5 import (
    ACCEPTED,
    LAUNCHER_SHA,
    canonical,
    changes,
    inverse,
    launcher_changes,
    transform,
)


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def dependencies(build, unit, phase):
    data = json.loads((build / f"{unit}.{phase}.json").read_text("utf-8-sig"))["Data"]
    prelaunch = build / "source/native-prelaunch"
    foundation = build / "source/native-foundation"
    source = (
        build / "ae5-fixture-host.cpp"
        if unit == "ae5-fixture-host"
        else prelaunch / "handle-probe.cpp"
    )
    required = (
        {
            build / "ae5-fixture-harness.h",
            build / "probe-identity.h",
            prelaunch / "ae5-custody.h",
            prelaunch / "identity.h",
            prelaunch / "suspended-inspection.h",
            prelaunch / "handle-diagnostic.h",
            foundation / "readiness.h",
            foundation / "sha256.h",
        }
        if unit == "ae5-fixture-host"
        else set()
    )
    require = _require
    require(normalized(data["Source"]) == normalized(source), "actual_translation_unit")
    require(
        not any(
            data.get(key)
            for key in ("ImportedModules", "ImportedHeaderUnits", "ProvidedModule", "PCH")
        ),
        "unexpected_module",
    )
    includes = [Path(name).resolve() for name in data["Includes"]]
    for path in required:
        require(
            sum(normalized(path) == normalized(p) for p in includes) == 1,
            "required_unique_project_include",
        )
    inventory = {}
    for path in [source, *includes]:
        norm = normalized(path)
        if path != source and path not in required:
            require(
                norm.startswith(
                    (
                        (
                            "c:/program files (x86)/microsoft visual studio/18/build"
                            "tools/vc/tools/msvc/14.50.35717/include/"
                        ),
                        "c:/program files (x86)/windows kits/10/include/10.0.26100.0/ucrt/",
                        "c:/program files (x86)/windows kits/10/include/10.0.26100.0/shared/",
                        "c:/program files (x86)/windows kits/10/include/10.0.26100.0/um/",
                    )
                ),
                "unapproved_compiler_input",
            )
        inventory[str(path)] = identity(path)
    return inventory


def _require(ok, reason):
    if not ok:
        raise ValueError("ae5_" + reason)


def source_review(build):
    prelaunch, foundation = build / "source/native-prelaunch", build / "source/native-foundation"
    originals = {
        "harness": foundation / "harness.cpp",
        "launcher": prelaunch / "a8-fixture-host.cpp",
        "inspector": prelaunch / "suspended-inspection.h",
    }
    for label, path in originals.items():
        expected = {"harness": ACCEPTED, "launcher": LAUNCHER_SHA, "inspector": INSPECTOR_SHA}[
            label
        ]
        _require(
            hashlib.sha256(canonical(path.read_bytes())).hexdigest() == expected,
            "original_identity",
        )
    for target, original, edits, expected in (
        (build / "ae5-fixture-harness.h", originals["harness"], changes(), ACCEPTED),
        (build / "ae5-fixture-host.cpp", originals["launcher"], launcher_changes(), LAUNCHER_SHA),
    ):
        _require(
            target.read_bytes() == transform(original.read_bytes(), edits, expected),
            "generated_difference",
        )
        _require(
            inverse(target.read_bytes(), edits) == canonical(original.read_bytes()),
            "full_byte_inverse",
        )
    _require(
        (build / "ae5-original-harness.h").read_bytes()
        == canonical(originals["harness"].read_bytes()),
        "baseline_harness",
    )
    source_gate = (prelaunch / "ae5-custody.h").read_text()
    _require("inline volatile const LONG NativeRelease = 0;" in source_gate, "native_source_gate")
    for name in ("ae5_parent.py", "ae5_windows.py"):
        _require("NATIVE_RELEASE = False" in (prelaunch / name).read_text(), "python_native_gate")
    _require(
        "RECOVERY_RELEASE = False" in (prelaunch / "ae5_resources.py").read_text(), "recovery_gate"
    )
    return {key: identity(value) for key, value in originals.items()}


def review(build, compiled=False):
    originals = source_review(build)
    actual = (build / "ae5-fixture-host.i").read_text("utf-8-sig")
    baseline = (build / "ae5-host-baseline.i").read_text("utf-8-sig")
    snippets = (build / "ae5-transform-tokens.i").read_text("utf-8-sig")
    restored = section(actual, (build / "ae5-fixture-harness.h").resolve())
    for i in reversed(range(len(changes()))):
        before, after = [section(snippets, f"ae5-{kind}-{i:02d}") for kind in ("before", "after")]
        positions = [at for at in range(len(restored)) if restored[at : at + len(after)] == after]
        _require(len(positions) == 1, f"preprocessed_inverse_{i}")
        at = positions[0]
        restored = restored[:at] + before + restored[at + len(after) :]
    normal = section(baseline, (build / "ae5-original-harness.h").resolve())
    _require(restored == normal, "complete_preprocessed_harness_inverse")
    inspector = (build / "source/native-prelaunch/suspended-inspection.h").resolve()
    shared = section(actual, inspector)
    _require(
        shared == section((build / "ae5-baseline.i").read_text("utf-8-sig"), inspector),
        "unchanged_complete_inspector",
    )
    inputs = dependencies(build, "ae5-fixture-host", "preprocess")
    if compiled:
        saved = json.loads((build / "ae5-input-review.json").read_text())
        _require(
            inputs
            == saved["compiler_inputs"]
            == dependencies(build, "ae5-fixture-host", "compiled"),
            "compiler_input_drift",
        )
        _require(
            dependencies(build, "handle-probe", "preprocess")
            == dependencies(build, "handle-probe", "compiled"),
            "probe_input_drift",
        )
        binary = (build / "ae5-fixture-host.inspection.txt").read_text("utf-8-sig")
        _require(
            not any(
                name in binary for name in ("ResumeThread", "TerminateThread", "CreateRemoteThread")
            ),
            "forbidden_import",
        )
        for name in (
            "TerminateJobObject",
            "WaitForSingleObject",
            "CreateProcessAsUserW",
            "ReadFile",
            "WriteFile",
        ):
            _require(name in binary, "missing_required_import")
    gates = source_gates(build / "source/native-prelaunch")
    return {
        "schema": "daf-ae5-build-review/v1",
        "compiled": compiled,
        "native_executions": 0,
        "native_gate": "CLOSED"
        if all(gates[k] is False for k in ("python", "windows", "cpp"))
        else "SOURCE_RELEASE_CHANGED",
        "source_gates": gates,
        "qualified": False,
        "originals": originals,
        "full_generated_inverses": True,
        "complete_preprocessed_harness_inverse": True,
        "unchanged_complete_inspector": True,
        "harness_tokens": len(normal),
        "inspector_tokens": len(shared),
        "compiler_inputs": inputs,
    }


if __name__ == "__main__":
    build = Path(sys.argv[1]).resolve()
    if sys.argv[2:] == ["--probe"]:
        result = dependencies(build, "handle-probe", "preprocess")
        target = "ae5-probe-input-review.json"
    else:
        compiled = sys.argv[2:] == ["--compiled"]
        result = review(build, compiled)
        target = "ae5-build-review.json" if compiled else "ae5-input-review.json"
    with (build / target).open("x", encoding="utf-8") as output:
        json.dump(result, output, sort_keys=True)
        output.write("\n")
    print(json.dumps({"review": target, "native_executions": 0, "result": "PASS"}))
