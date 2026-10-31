"""Exactly two staged A4 controls. No batch loop, retries, resume or authority."""

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import a4_observations as diagnostic
from a3_qualify import bounded_cleanup
from instrument_fixture import instrument
from qualify import FOUNDATION, WORKERS, a, c, publish

HISTORY = {
    "m21b-gates-run-01": "3193d12765bb063ca394d7bbd92e01face4c787ed62ca103a6ccbd856fd529f3",
    "m21b-a1-run-01": "cc8cfc5d3689c3ff19f78efd6c7ec9f5f6ff23ff3db35960d8b6083d7f9acaf4",
    "m21b-a3-run-01": "4a1225ca421bfcf67ba7b096a60f6df70d5ca61a6fe90d3289452df1f71b0ab3",
}


def run_case(build, workers, output, sequence, case, role, refusal):
    c.require(
        (sequence, case, role, refusal)
        in ((1, "A4-01", "probe", None), (2, "A4-02", "probe", None)),
        "a4_two_controls_only",
    )
    attempt = output / f"{sequence:02d}-{case}-{role}"
    attempt.mkdir()
    (attempt / "runtime").mkdir()
    record = {"sequence": sequence, "case": case, "role": role, "status": "unconfirmed"}
    publish(attempt / "started.json", record)
    for leaf, origin in {
        "harness.exe": build / "fixture-host.exe",
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
    publish(attempt / "result.json", record)
    return record


def verify_build(build, workers):
    repo = FOUNDATION.parents[1]
    manifest = c.load((build / "build-manifest.json").read_bytes(), 250000)
    c.require(manifest["schema"] == "daf-a4-fixture-build/v1", "separate_fixture_build")
    for relative, expected in manifest["files"].items():
        raw = (build / relative).read_bytes()
        c.require(
            len(raw) == expected["bytes"] and c.sha(raw) == expected["sha256"], "build_identity"
        )
        if relative.startswith("source/"):
            current = repo / "desktop" / relative.removeprefix("source/")
            c.require(current.read_bytes() == raw, "tested_source_identity")
    c.require(
        (build / "a4-fixture-harness.h").read_bytes()
        == instrument((FOUNDATION / "harness.cpp").read_bytes()),
        "exact_fixture_hooks",
    )
    inspection = (build / "fixture-host.inspection.txt").read_text()
    c.require("ResumeThread" not in inspection, "no_resume_import")
    for role, expected in WORKERS.items():
        c.require(
            c.sha((workers / (role + ".exe")).read_bytes()) == expected, "accepted_worker_identity"
        )
    for run, expected in HISTORY.items():
        c.require(
            c.sha((repo / "dist" / run / "completion.json").read_bytes()) == expected,
            "historical_identity",
        )
    return c.sha((build / "build-manifest.json").read_bytes())


def prerequisite(output, build_hash):
    # A distinct readback invocation must publish this immutable receipt. It is
    # an accidental-continuation guard, never a production execution grant.
    receipt = c.load((output / "A4-01-independent.json").read_bytes(), 100000)
    raw = (output / "A4-01-completion.json").read_bytes()
    first = c.load(raw, 100000)
    c.require(
        receipt["case"] == "A4-01" and receipt["independently_verified"] is True,
        "first_case_not_verified",
    )
    c.require(
        receipt["build_manifest"] == build_hash == first["build_manifest"], "first_build_identity"
    )
    c.require(receipt["completion_sha256"] == c.sha(raw), "first_receipt_identity")
    c.require(
        first["records"][0]["status"] == "passed" and first["retries"] == 0, "first_case_failed"
    )
    result_raw = (output / "01-A4-01-probe/result.json").read_bytes()
    c.require(receipt["result_sha256"] == c.sha(result_raw), "first_result_identity")
    c.require(c.load(result_raw, 100000) == first["records"][0], "first_result_mismatch")
    c.require(receipt.get("schema") == "daf-a4-independent/v1", "first_receipt_schema")
    for key, value in {
        "qualified": False,
        "fixture_bytes_unchanged": True,
        "owned_registry_storage_independently_absent": True,
        "native_processes_launched_by_readback": 0,
    }.items():
        c.require(type(receipt.get(key)) is type(value) and receipt[key] == value, "first_readback")
    c.require(
        receipt.get("verifier_sha256")
        == c.sha(Path(__file__).with_name("a4_verify.py").read_bytes()),
        "first_verifier_identity",
    )
    c.require(isinstance(receipt.get("cleanup_readback"), dict), "first_cleanup_readback")
    independently_read = {**first["records"][0], "independent_cleanup": receipt["cleanup_readback"]}
    verified = diagnostic.validate(independently_read)
    c.require(
        json.loads(json.dumps(verified)) == receipt.get("inspection"), "first_readback_result"
    )
    values = {
        row["native"]: row["value"] for row in first["records"][0]["observations"] if "value" in row
    }
    c.require(
        receipt.get("fixture_file_identity")
        == {key: values["a4_original_" + key] for key in ("volume", "file_low", "file_high")},
        "first_fixture_readback",
    )
    return c.sha((output / "A4-01-independent.json").read_bytes())


def main():
    c.require(
        len(sys.argv) == 5 and sys.argv[1] in ("--a4-01", "--a4-02"), "a4_single_case_invocation"
    )
    sequence = 1 if sys.argv[1] == "--a4-01" else 2
    case = f"A4-0{sequence}"
    build, workers, output = [Path(p).resolve() for p in sys.argv[2:]]
    repo = FOUNDATION.parents[1]
    c.require(output.is_relative_to(repo / "dist"), "owned_evidence_root")
    build_hash = verify_build(build, workers)
    prior = None
    if sequence == 1:
        c.require(not output.exists(), "fresh_evidence_root")
    else:
        prior = prerequisite(output, build_hash)
    initial = {
        "schema": "daf-a4-control/v1",
        "run": uuid.uuid4().hex,
        "case": case,
        "build_manifest": build_hash,
        "build_directory": str(build.relative_to(repo)).replace("\\", "/"),
        "qualifier": c.sha(Path(__file__).read_bytes()),
        "retries": 0,
        "prior_independent_receipt": prior,
        "historical_failures_and_feasibility": HISTORY,
        "qualified": False,
        "gate_b": "unqualified_not_executed",
    }
    publish(repo / "dist" / f"m21b-a4-0{sequence}-execution-claimed.json", initial)
    if sequence == 1:
        output.mkdir()
    publish(output / f"{case}-started.json", initial)
    record = run_case(build, workers, output, sequence, case, "probe", None)
    complete = record["status"] == "passed"
    publish(
        output / f"{case}-completion.json",
        {
            **initial,
            "initial_detector_sensitivity": complete,
            "records": [record],
            "result_label": f"{case}: expected hostile-object refusal independently observable."
            if complete
            else f"{case}: detector-control failure; stop.",
        },
    )
    print(
        json.dumps(
            {
                "case": case,
                "status": record["status"],
                "failure": record.get("failure"),
                "independent_verification_required": True,
            }
        ),
        flush=True,
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
