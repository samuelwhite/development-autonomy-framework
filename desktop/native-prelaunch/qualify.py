"""A1 single-case diagnostic only; no desktop execution or Gate B progression.

Immutable start/result records retain a failed gate. No automatic retry, resume,
relabeling, raw child-output persistence, or worker publication is supported.
"""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import handle_observations as diagnostic

FOUNDATION = Path(__file__).resolve().parents[1] / "native-foundation"
sys.path.insert(0, str(FOUNDATION))
import acceptance as a  # noqa: E402
import contracts as c  # noqa: E402
from cleanup import cleanup  # noqa: E402

HISTORICAL_CASES = (
    ("handles", "probe", None),
    ("positive", "producer", None),
    ("positive", "verifier", None),
    ("substitute", "producer", "image_digest"),
    ("modified", "producer", "image_digest"),
    ("existing-writer", "producer", "pin_open"),
    ("existing-mapping", "producer", "pin_open"),
    ("write-race", "producer", None),
    ("rename-race", "producer", None),
    ("parent-rename-race", "producer", None),
    ("hardlink-race", "producer", "hard_link"),
    ("wrong-launched-image", "producer", "process_image_path"),
    ("post-create-write", "producer", None),
    ("path-dot", "producer", "path_component"),
    ("path-slash", "producer", "path_syntax"),
    ("path-device", "producer", "path_syntax"),
    ("path-ads", "producer", "path_syntax"),
    ("path-case", "producer", "canonical_path"),
    ("path-short", "producer", "path_syntax"),
    ("path-hardlink", "producer", "hard_link"),
)
CASES = (("handles", "probe", None),)
WORKERS = {
    "producer": "be7b85e698f278e74cf94138385ba9d0990d8045eae2e8d833d580de245b6ed0",
    "verifier": "34bd5f3612790adb40155c9dde74785bf4527382a15be15e076315d7584f1850",
}


def publish(path, value):
    raw = c.canonical(value) + b"\n"
    with path.open("xb") as stream:
        c.require(stream.write(raw) == len(raw), "evidence_write")
        stream.flush()
        os.fsync(stream.fileno())
    c.require(path.read_bytes() == raw, "evidence_readback")
    return c.sha(raw)


def check_rows(record, refusal):
    rows = record["observations"]
    value = lambda key: a.value(rows, key)  # noqa: E731
    c.require(record["cleanup"] == "confirmed", "cleanup")
    failures = [r["native"] for r in rows if r["native"].startswith("gate_refusal_")]
    if refusal:
        c.require(failures == ["gate_refusal_" + refusal], "expected_refusal")
        c.require(not any(r["native"] == "child_resumed" for r in rows), "rejected_child_resumed")
        if record["case"] == "wrong-launched-image":
            c.require(value("rejected_suspended_image_terminated") == 1, "rejected_image_survived")
        c.require(
            record["helper_exit"] == (0 if record["case"].startswith("path-") else 1),
            "refusal_exit",
        )
        return
    c.require(not failures and record["helper_exit"] == 0, "native_gate_failure")
    c.require(not any(r["native"] == "host_failure" for r in rows), "host_failure")
    for key, expected in {
        "prelaunch_image_verified": 1,
        "launched_image_independently_verified": 1,
        "host_elevated": 0,
        "host_appcontainer": 0,
        "appcontainer": 1,
        "final_elevated": 0,
        "CreateRestrictedToken_flags": 9,
        "job_at_creation": 1,
        "job_limit_flags": 8458,
        "job_process_limit": 1,
        "job_memory_bytes": 134217728,
        "job_cpu_100ns": 20000000,
        "capability_count": 1,
        "child_resumed": 1,
        "active_after_wait": 0,
        "retained_process_handle_signalled": 1,
        "worker_output_rejected": 0,
        "child_exit": 0,
        "termination_reason": 0,
    }.items():
        c.require(value(key) == expected, "security_observation")
    c.require(a.value(rows, "native_ambient_write", "allowed") is False, "ambient_write")
    c.require(a.value(rows, "native_ambient_write", "error") == 5, "ambient_denial")
    c.require(a.value(rows, "native_explicit_dual_write", "allowed") is True, "write_control")
    c.require(
        a.value(rows, "requested_attempt_sid", "sid")
        == a.value(rows, "final_child_restricted_sids", "sid"),
        "attempt_identity",
    )
    c.require(value("wall_elapsed_ms") < 10000, "wall_deadline")
    for name in (
        "restore_registry_acl",
        "delete_explicitly_created_registry_storage",
        "delete_synthetic_registry_key",
        "delete_owned_profile_hresult",
    ):
        c.require(value(name) == 0, "native_cleanup")
    c.require(value("delete_synthetic_credential") == 1, "credential_cleanup")
    restored = [r["value"] for r in rows if r["native"] == "restore_profile_acl"]
    c.require(bool(restored) and all(v == 0 for v in restored), "profile_acl_cleanup")


def run_case(build, workers, output, sequence, case, role, refusal):
    c.require((case, role, refusal) == CASES[0] and sequence == 1, "a1_single_case_only")
    attempt = output / f"{sequence:02d}-{case}-{role}"
    attempt.mkdir()
    (attempt / "runtime").mkdir()
    record = {"sequence": sequence, "case": case, "role": role, "status": "unconfirmed"}
    publish(attempt / "started.json", record)
    for leaf, origin in {
        "harness.exe": build / "gate-host.exe",
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
    if case == "substitute":
        (attempt / "producer.exe").write_bytes((attempt / "verifier.exe").read_bytes())
    elif case == "modified":
        image = bytearray((attempt / "producer.exe").read_bytes())
        image[-1] ^= 1
        (attempt / "producer.exe").write_bytes(image)
    elif case == "path-hardlink":
        os.link(attempt / "producer.exe", attempt / "alias.exe")
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
        process.wait(timeout=35)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
        record["parent_deadline_exceeded"] = True
    out.thread.join(timeout=3)
    err.thread.join(timeout=3)
    record.update(
        {
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "helper_exit": process.returncode,
            "observations": [],
            "cleanup": "unconfirmed",
        }
    )
    try:
        if (attempt / "owned-profile.txt").exists():
            cleanup(attempt)
        elif not case.startswith("path-"):
            raise c.Refused("missing_profile_marker")
        record["cleanup"] = "confirmed"
        c.require(not out.overflow and not err.overflow, "bounded_capture")
        c.require(not out.thread.is_alive() and not err.thread.is_alive(), "capture_complete")
        record["observations"] = a.observations(bytes(err.data))
        # Closed numeric progress is saved before exit/outcome checks, including
        # incomplete observations on a timeout. Unknown output is never saved.
        record["probes"] = diagnostic.parse(bytes(out.data))
        c.require(not record.get("parent_deadline_exceeded"), "parent_deadline")
        for leaf in ("ambient-shared.txt", "smuggled-read.txt", "smuggled-write.txt"):
            c.require((attempt / leaf).read_bytes() == fixtures[leaf], "unauthorized_write")
        record["synthetic_resources_unchanged"] = True
        check_rows(record, refusal)
        if role == "probe":
            record["handle_determinations"] = diagnostic.validate(
                record["probes"], record["observations"]
            )
        elif not refusal:
            record["response"], _ = c.response(
                bytes(out.data),
                1 if role == "producer" else 2,
                prepared.digest,
                candidate if role == "verifier" else None,
            )
        else:
            c.require(not out.data, "refused_output")
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


def main():
    c.require(len(sys.argv) == 5 and sys.argv[1] == "--a1-single", "a1_single_invocation_required")
    build, workers, output = [Path(p).resolve() for p in sys.argv[2:]]
    repo = FOUNDATION.parents[1]
    c.require(output.is_relative_to(repo / "dist") and not output.exists(), "fresh_evidence_root")
    output.mkdir()
    manifest = c.load((build / "build-manifest.json").read_bytes(), 200000)
    for leaf in ("gate-host.exe", "handle-probe.exe"):
        c.require(
            c.sha((build / leaf).read_bytes()) == manifest["files"][leaf]["sha256"],
            "gate_build_identity",
        )
    for role, expected in WORKERS.items():
        c.require(
            c.sha((workers / (role + ".exe")).read_bytes()) == expected, "accepted_worker_identity"
        )
    for leaf in (
        "qualify.py",
        "handle_observations.py",
        "handle-probe.cpp",
        "handle-diagnostic.h",
        "gate-host.cpp",
        "identity.h",
        "build.ps1",
    ):
        expected = manifest["files"]["source/native-prelaunch/" + leaf]
        c.require(
            c.sha(Path(__file__).with_name(leaf).read_bytes()) == expected["sha256"],
            "tested_source_identity",
        )
    initial = {
        "schema": "daf-a1-targeted-diagnostic/v1",
        "run": uuid.uuid4().hex,
        "build_manifest": c.sha((build / "build-manifest.json").read_bytes()),
        "qualifier": c.sha(Path(__file__).read_bytes()),
        "cases": CASES,
        "retries": 0,
        "historical_failure": "3193d12765bb063ca394d7bbd92e01face4c787ed62ca103a6ccbd856fd529f3",
        "gate_b": "unqualified_not_executed",
    }
    publish(output / "started.json", initial)
    # A task-local one-execution guard, not production admission or authority.
    # Retained permanently even if preparation, execution or recording fails.
    publish(repo / "dist" / "m21b-a1-single-execution-claimed.json", initial)
    records = []
    for sequence, (case, role, refusal) in enumerate(CASES, 1):
        record = run_case(build, workers, output, sequence, case, role, refusal)
        records.append(record)
        print(
            json.dumps(
                {
                    "case": case,
                    "role": role,
                    "status": record["status"],
                    "failure": record.get("failure"),
                }
            ),
            flush=True,
        )
        if record["status"] != "passed":
            break
    complete = len(records) == len(CASES) and all(r["status"] == "passed" for r in records)
    publish(
        output / "completion.json",
        {
            **initial,
            "qualified": False,
            "targeted_diagnostic_passed": complete,
            "result_label": "Targeted Gate A diagnostic passed provisionally."
            if complete
            else "Targeted Gate A diagnostic failed.",
            "records": records,
            "other_native_cases_executed": 0,
        },
    )
    if complete:
        print("Targeted Gate A diagnostic passed provisionally.", flush=True)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
