"""One-shot standalone Windows gate qualification; no desktop execution path.

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

FOUNDATION = Path(__file__).resolve().parents[1] / "native-foundation"
sys.path.insert(0, str(FOUNDATION))
import acceptance as a  # noqa: E402
import contracts as c  # noqa: E402
from cleanup import cleanup  # noqa: E402

CASES = (
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


def run_case(build, workers, output, sequence, case, role, refusal):
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
        c.require(not out.overflow and not err.overflow, "bounded_capture")
        c.require(not out.thread.is_alive() and not err.thread.is_alive(), "capture_complete")
        record["observations"] = a.observations(bytes(err.data))
        if (attempt / "owned-profile.txt").exists():
            cleanup(attempt)
        elif not case.startswith("path-"):
            raise c.Refused("missing_profile_marker")
        record["cleanup"] = "confirmed"
        c.require(not record.get("parent_deadline_exceeded"), "parent_deadline")
        for leaf in ("ambient-shared.txt", "smuggled-read.txt", "smuggled-write.txt"):
            c.require((attempt / leaf).read_bytes() == fixtures[leaf], "unauthorized_write")
        check_rows(record, refusal)
        if role == "probe":
            probes = [c.load(line, 256) for line in bytes(out.data).splitlines()]
            c.require(all(set(p) == {"probe", "value"} for p in probes), "probe_fields")
            values = {p["probe"]: p["value"] for p in probes}
            c.require(len(values) == len(probes), "duplicate_probe")
            expected = {
                "pid": a.value(record["observations"], "child_pid"),
                "stdin_pipe": 1,
                "stdout_pipe": 1,
                "stderr_pipe": 1,
                "extra_read_succeeded": 0,
                "extra_read_bytes": 0,
                "extra_write_succeeded": 0,
                "extra_write_bytes": 0,
                "extra_mapping_succeeded": 0,
                "extra_event_succeeded": 0,
                "extra_process_pid": 0,
                "extra_duplicate_succeeded": 0,
            }
            c.require(values == expected, "hostile_handle_bypass")
            c.require(
                a.value(record["observations"], "hostile_handles_inheritable") == 5,
                "hostile_controls",
            )
            c.require(
                a.value(record["observations"], "hostile_positive_controls") == 1,
                "positive_controls",
            )
            record["probes"] = values
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
    except (c.Refused, AssertionError, OSError, RuntimeError) as error:
        record["status"] = "failed"
        record["failure"] = {
            "type": type(error).__name__,
            "errno": getattr(error, "errno", None),
            "winerror": getattr(error, "winerror", None),
        }
        if isinstance(error, c.Refused):
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
    build, workers, output = [Path(p).resolve() for p in sys.argv[1:]]
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
    initial = {
        "schema": "daf-prelaunch-qualification/v1",
        "run": uuid.uuid4().hex,
        "build_manifest": c.sha((build / "build-manifest.json").read_bytes()),
        "qualifier": c.sha(Path(__file__).read_bytes()),
        "cases": CASES,
        "retries": 0,
    }
    publish(output / "started.json", initial)
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
            "qualified": complete,
            "records": records,
            "unrun_cases": len(CASES) - len(records),
        },
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
