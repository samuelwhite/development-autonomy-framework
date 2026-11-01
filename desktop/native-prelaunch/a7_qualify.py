"""Single-case A7 entry point. Closed two-case sequence; no automatic native loop."""

import ctypes as C
import json
import os
import subprocess
import sys
import time
import uuid
from ctypes import wintypes as W
from pathlib import Path

import a7_observations as diagnostic
from a3_qualify import bounded_cleanup
from a6_qualify import HISTORY as PRIOR_HISTORY
from a7_build_review import review as review_build
from a7_cases import NAMES, specification
from instrument_a7 import inspector, instrument
from qualify import FOUNDATION, WORKERS, a, c, publish

HISTORY = {
    **PRIOR_HISTORY,
    "docs/evidence/m2.1b-a6-controls-windows.json": (
        "400d42d00e410822cdb110008ea0d9fde1f273b72662221751b931974612c1ed"
    ),
    "dist/m21b-a6-run-01/exercise-completion.json": (
        "637cc82de8014602dd53caea74759d43bfd60dcb92380f88564ae62048235e3f"
    ),
}


def helper_identity(process):
    """Parent-owned process handle corroborates the process-control witness."""
    k = C.WinDLL("kernel32", use_last_error=True)
    k.GetProcessTimes.argtypes = [W.HANDLE, *([C.POINTER(W.FILETIME)] * 4)]
    values = [W.FILETIME() for _ in range(4)]
    ok = k.GetProcessTimes(int(process._handle), *(C.byref(value) for value in values))
    return {
        "pid": process.pid,
        "query_ok": bool(ok),
        "error": 0 if ok else C.get_last_error(),
        "creation": (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime,
    }


def run_case(build, workers, output, sequence, case, role, refusal):
    c.require(case in NAMES and role == "probe" and refusal is None, "a7_controls_only")
    c.require(sequence == specification(case)[0], "a7_case_order")
    attempt = output / f"{sequence:02d}-{case}-{role}"
    attempt.mkdir()
    (attempt / "runtime").mkdir()
    record = {"sequence": sequence, "case": case, "role": role, "status": "unconfirmed"}
    publish(attempt / "started.json", record)
    for leaf, origin in {
        "harness.exe": build / "a7-fixture-host.exe",
        "probe.exe": build / "handle-probe.exe",
        "producer.exe": workers / "producer.exe",
        "verifier.exe": workers / "verifier.exe",
    }.items():
        (attempt / leaf).write_bytes(origin.read_bytes())
    prepared, source = a.preparation(attempt)
    _, _, candidate = c.specification(c.load(prepared.encoded)["local_spec"], source)
    payload = (
        b""
        if role == "probe"
        else c.request(
            prepared,
            source,
            1 if role == "producer" else 2,
            b"" if role == "producer" else candidate,
        )
    )
    fixtures = {
        "allowed.txt": b"Explicitly readable synthetic fixture",
        "private.txt": b"Host-private synthetic fixture",
        "ambient-shared.txt": b"Synthetic resource shared with all LPACs",
        "dual-grant.txt": b"Explicit dual-grant synthetic fixture",
        "protected.bin": b"",
        "fixture-root.marker": b"DAF M2.1A owned acceptance fixture",
        "request.bin": payload,
        "smuggled-read.txt": b"R" * 32,
        "smuggled-write.txt": b"S" * 32,
    }
    for leaf, data in fixtures.items():
        (attempt / leaf).write_bytes(data)
    record["input_manifest"] = prepared.digest
    record["image_before"] = {
        leaf: c.sha((attempt / (leaf + ".exe")).read_bytes()) for leaf in WORKERS
    }
    start = time.monotonic()
    process = subprocess.Popen(
        [str(attempt / "harness.exe"), case, role],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x08000000,
    )
    out, err = a.Capture(process.stdout, c.MAX_OUTPUT), a.Capture(process.stderr, 32768)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
        record["parent_deadline_exceeded"] = True
    record["helper_identity"] = helper_identity(process)
    out.thread.join(timeout=max(0, min(3, start + 35 - time.monotonic())))
    err.thread.join(timeout=max(0, min(3, start + 35 - time.monotonic())))
    record.update(
        {
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "helper_exit": process.returncode,
            "observations": [],
            "cleanup": "unconfirmed",
        }
    )
    record["stdout"] = {
        "sha256": c.sha(bytes(out.data)),
        "bytes": len(out.data),
        "overflow": out.overflow,
    }
    record["stderr"] = {
        "sha256": c.sha(bytes(err.data)),
        "bytes": len(err.data),
        "overflow": err.overflow,
    }
    # Preserve bounded original evidence before parsing; exclusive durable files.
    for name, data in (("stdout.capture", bytes(out.data)), ("stderr.jsonl", bytes(err.data))):
        with (attempt / name).open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    try:
        c.require(not out.overflow and not err.overflow, "bounded_capture")
        c.require(not out.thread.is_alive() and not err.thread.is_alive(), "capture_complete")
        record["observations"] = a.observations(bytes(err.data))
    except (c.Refused, ValueError):
        record["capture_invalid"] = True
    try:
        c.require((attempt / "owned-profile.txt").exists(), "missing_profile_marker")
        record["independent_cleanup"] = bounded_cleanup(
            attempt, record["observations"], process.pid, start + 35
        )
        record["cleanup"] = "confirmed"
        c.require(not record.get("capture_invalid"), "capture_invalid")
        for leaf in ("ambient-shared.txt", "smuggled-read.txt", "smuggled-write.txt"):
            c.require((attempt / leaf).read_bytes() == fixtures[leaf], "unauthorized_write")
        record["synthetic_resources_unchanged"] = True
        record["inspection"] = diagnostic.validate(record)
        record["status"] = "passed"
    except (
        c.Refused,
        diagnostic.InvalidObservation,
        AssertionError,
        OSError,
        RuntimeError,
    ) as error:
        record["status"] = "failed"
        record["failure"] = {
            "type": type(error).__name__,
            "errno": getattr(error, "errno", None),
            "winerror": getattr(error, "winerror", None),
        }
        if isinstance(error, (c.Refused, diagnostic.InvalidObservation)):
            record["failure"]["stage"] = str(error)
    record["stdout"] = {
        "sha256": c.sha(bytes(out.data)),
        "bytes": len(out.data),
        "overflow": out.overflow,
    }
    record["stderr"] = {
        "sha256": c.sha(bytes(err.data)),
        "bytes": len(err.data),
        "overflow": err.overflow,
    }
    if record["status"] != "passed":
        record["failure"]["classification"] = diagnostic.nonpass_classification(record)
    publish(attempt / "result.json", record)
    return record


def verify_build(build, workers):
    repo = FOUNDATION.parents[1]
    manifest = c.load((build / "build-manifest.json").read_bytes(), 250000)
    c.require(manifest["schema"] == "daf-a7-fixture-build/v1", "separate_fixture_build")
    for relative, expected in manifest["files"].items():
        raw = (build / relative).read_bytes()
        c.require(
            len(raw) == expected["bytes"] and c.sha(raw) == expected["sha256"], "build_identity"
        )
        if relative.startswith("source/"):
            current = repo / "desktop" / relative.removeprefix("source/")
            c.require(current.read_bytes() == raw, "tested_source_identity")
    c.require(
        (build / "a7-fixture-harness.h").read_bytes()
        == instrument((FOUNDATION / "harness.cpp").read_bytes()),
        "exact_fixture_hooks",
    )
    inspection = (build / "a7-fixture-host.inspection.txt").read_text()
    c.require("ResumeThread" not in inspection, "no_resume_import")
    for role, expected in WORKERS.items():
        c.require(
            c.sha((workers / (role + ".exe")).read_bytes()) == expected, "accepted_worker_identity"
        )
    for relative, expected in HISTORY.items():
        c.require(
            c.sha((repo / relative).read_bytes()) == expected,
            "historical_identity",
        )
    c.require(
        (build / "a7-suspended-inspection.generated.h").read_bytes()
        == inspector(Path(__file__).with_name("suspended-inspection.h").read_bytes()),
        "exact_inspector_boundary",
    )
    c.require(
        review_build(build) == c.load((build / "a7-build-review.json").read_bytes()),
        "actual_include_preprocessed_review",
    )
    return c.sha((build / "build-manifest.json").read_bytes())


def prerequisite(output, build_hash, case):
    c.require(case in NAMES and not (output / "STOP.json").exists(), "a7_stopped_or_unknown")
    prior = []
    for previous in NAMES[: NAMES.index(case)]:
        sequence = specification(previous)[0]
        receipt_path = output / f"{previous}-independent.json"
        receipt = c.load(receipt_path.read_bytes(), 100000)
        raw = (output / f"{previous}-completion.json").read_bytes()
        complete = c.load(raw, 100000)
        result_raw = (output / f"{sequence:02d}-{previous}-probe/result.json").read_bytes()
        record = c.load(result_raw, 100000)
        c.require(
            complete["records"] == [record] and record["status"] == "passed", "previous_result"
        )
        c.require(
            complete["case"] == previous
            and complete["retries"] == 0
            and complete["qualified"] is False,
            "previous_case",
        )
        c.require(complete["prior_independent_receipts"] == prior, "previous_chain")
        c.require(
            receipt["schema"] == "daf-a7-independent/v1" and receipt["case"] == previous,
            "previous_receipt",
        )
        c.require(
            receipt["build_manifest"] == build_hash == complete["build_manifest"], "previous_build"
        )
        c.require(
            receipt["completion_sha256"] == c.sha(raw)
            and receipt["result_sha256"] == c.sha(result_raw),
            "previous_hashes",
        )
        for key, value in {
            "independently_verified": True,
            "qualified": False,
            "fixture_bytes_unchanged": True,
            "owned_registry_storage_independently_absent": True,
            "native_processes_launched_by_readback": 0,
        }.items():
            c.require(
                type(receipt.get(key)) is type(value) and receipt[key] == value, "previous_readback"
            )
        c.require(
            receipt["verifier_sha256"]
            == c.sha(Path(__file__).with_name("a7_verify.py").read_bytes()),
            "previous_verifier",
        )
        c.require(isinstance(receipt.get("cleanup_readback"), dict), "previous_cleanup")
        checked = diagnostic.validate(
            {**record, "independent_cleanup": receipt["cleanup_readback"]}
        )
        c.require(json.loads(json.dumps(checked)) == receipt["inspection"], "previous_inspection")
        values = {row["native"]: row["value"] for row in record["observations"] if "value" in row}
        expected_files = {
            name: {
                key: values[f"a1_control_h{i}_" + key]
                for key in ("volume", "file_low", "file_high")
            }
            for i, name in enumerate(("read", "write"))
        }
        c.require(receipt["fixture_file_identities"] == expected_files, "previous_fixture_identity")
        prior.append({"case": previous, "sha256": c.sha(receipt_path.read_bytes())})
    return prior


def stop(output, case, failure):
    """An immutable native-allowance stop; no repair, retry or next case."""
    at = NAMES.index(case)
    value = {
        "schema": "daf-a7-stop/v1",
        "failed_case": case,
        "qualified": False,
        "failure": failure,
        "retries": 0,
        "results": {
            name: "PASS" if i < at else "FAIL" if i == at else "NOT RUN"
            for i, name in enumerate(NAMES)
        },
    }
    publish(output / "STOP.json", value)
    return value


def main():
    c.require(len(sys.argv) == 5 and sys.argv[1] in NAMES, "a7_single_authorized_case")
    case = sys.argv[1]
    sequence, _, _, _ = specification(case)
    build, workers, output = [Path(p).resolve() for p in sys.argv[2:]]
    repo = FOUNDATION.parents[1]
    c.require(output.is_relative_to(repo / "dist"), "owned_evidence_root")
    build_hash = verify_build(build, workers)
    manifest = c.load((build / "build-manifest.json").read_bytes(), 250000)
    exercise_path = repo / "dist/m21b-a7-exercise-claimed.json"
    binding = {
        "schema": "daf-a7-exercise/v1",
        "case_order": NAMES,
        "build_manifest": build_hash,
        "output": output.relative_to(repo).as_posix(),
        "maximum_native_executions": 2,
        "retries": 0,
        "qualified": False,
    }
    if sequence == 1:
        c.require(not output.exists(), "fresh_exercise_root")
        publish(exercise_path, binding)
        output.mkdir()
    else:
        c.require(
            c.load(exercise_path.read_bytes(), 100000) == json.loads(json.dumps(binding)),
            "same_exercise",
        )
    prior = prerequisite(output, build_hash, case)
    initial = {
        "schema": "daf-a7-control/v1",
        "run": uuid.uuid4().hex,
        "case": case,
        "sequence": sequence,
        "build_manifest": build_hash,
        "build_directory": build.relative_to(repo).as_posix(),
        "implementation_commit": manifest["git_parent"],
        "binary_identities": {
            name: manifest["files"][name]
            for name in (
                "a7-fixture-host.exe",
                "handle-probe.exe",
                "a7-fixture-harness.h",
                "a7-suspended-inspection.generated.h",
            )
        },
        "qualifier": c.sha(Path(__file__).read_bytes()),
        "retries": 0,
        "prior_independent_receipts": prior,
        "historical_identities": HISTORY,
        "qualified": False,
        "gate_b": "unqualified_not_executed",
    }
    publish(repo / "dist" / f"m21b-a7-{case}-execution-claimed.json", initial)
    publish(output / f"{case}-started.json", initial)
    try:
        record = run_case(build, workers, output, sequence, case, "probe", None)
    except Exception as error:
        record = {
            "case": case,
            "sequence": sequence,
            "role": "probe",
            "status": "failed",
            "cleanup": "unconfirmed",
            "failure": {"type": type(error).__name__, "errno": getattr(error, "errno", None)},
        }
        publish(output / f"{case}-unexpected.json", record)
    passed = record["status"] == "passed"
    publish(
        output / f"{case}-completion.json",
        {
            **initial,
            "expected_control_observed": passed,
            "records": [record],
            "independent_verification_required": True,
        },
    )
    if not passed:
        stop(output, case, record.get("failure", {"stage": "incomplete_case"}))
    print(
        json.dumps(
            {
                "case": case,
                "native_result": record["status"],
                "failure": record.get("failure"),
                "independent_verification_required": True,
            }
        ),
        flush=True,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        result = main()
    except Exception as error:
        # An exclusive claim also blocks repeats if storage cannot persist STOP.
        if len(sys.argv) == 5 and sys.argv[1] in NAMES:
            case = sys.argv[1]
            output = Path(sys.argv[4]).resolve()
            claim = FOUNDATION.parents[1] / "dist" / f"m21b-a7-{case}-execution-claimed.json"
            if claim.exists() and output.is_relative_to(FOUNDATION.parents[1] / "dist"):
                if not (output / "STOP.json").exists():
                    stop(output, case, {"type": type(error).__name__, "stage": "entry_failure"})
        raise
    raise SystemExit(result)
