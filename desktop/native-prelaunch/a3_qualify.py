"""A3 single suspended-child feasibility attempt. No resume, retry or other cases."""

import ctypes as C
import json
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes as W
from pathlib import Path

import a3_observations as diagnostic
from instrument_harness import instrument
from qualify import FOUNDATION, WORKERS, a, c, cleanup, publish

CASES = (("case-01", "probe", None),)
HISTORY = {
    "original": "3193d12765bb063ca394d7bbd92e01face4c787ed62ca103a6ccbd856fd529f3",
    "a1": "cc8cfc5d3689c3ff19f78efd6c7ec9f5f6ff23ff3db35960d8b6083d7f9acaf4",
}


def bounded_cleanup(attempt, rows, helper_pid, deadline):
    result = {}

    def work():
        try:
            cleanup(attempt)
            result["verified"] = verify_cleanup(attempt, rows, helper_pid)
        except (OSError, RuntimeError, AssertionError, c.Refused) as error:
            result["error"] = error

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(timeout=max(0, deadline - time.monotonic()))
    c.require(not worker.is_alive(), "cleanup_deadline_unconfirmed")
    if "error" in result:
        raise result["error"]
    c.require("verified" in result, "cleanup_unconfirmed")
    return result["verified"]


def verify_cleanup(attempt, rows, helper_pid):
    """Independent readback of only this case's recorded generated resources."""
    import winreg

    name, profile = (attempt / "owned-profile.txt").read_text().splitlines()[:2]
    c.require(not Path(profile).parent.exists(), "profile_remains")
    k, adv = C.WinDLL("kernel32", use_last_error=True), C.WinDLL("advapi32", use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    k.CloseHandle.argtypes = [W.HANDLE]
    k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    pids = {helper_pid}
    for row in rows:
        if row["native"] in {"a3_created_pid", "child_pid"}:
            pids.add(row["value"])
    c.require(len(pids) == 2, "missing_child_identity")
    processes = []
    for pid in sorted(pids):
        handle = k.OpenProcess(0x101000, False, pid)
        error = C.get_last_error()
        if handle:
            try:
                wait = k.WaitForSingleObject(handle, 0)
                code = W.DWORD()
                queried = k.GetExitCodeProcess(handle, C.byref(code))
                c.require(
                    wait == 0 and queried and code.value != 259, "process_termination_unconfirmed"
                )
                processes.append({"pid": pid, "terminated": True, "wait": wait, "exit": code.value})
            finally:
                k.CloseHandle(handle)
        else:
            c.require(error == 87, "process_absence_unconfirmed")
            processes.append({"pid": pid, "terminated": True, "open_error": error})
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software\\" + name):
            raise RuntimeError("synthetic_key_remains")
    except FileNotFoundError:
        pass
    adv.CredReadW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(C.c_void_p)]
    adv.CredReadW.restype = W.BOOL
    adv.CredFree.argtypes = [C.c_void_p]
    credential = C.c_void_p()
    exists = adv.CredReadW(name, 1, 0, C.byref(credential))
    error = C.get_last_error()
    if exists:
        adv.CredFree(credential)
    c.require(not exists and error == 1168, "credential_absence_unconfirmed")
    return {
        "processes": processes,
        "profile_absent": True,
        "synthetic_key_absent": True,
        "synthetic_credential_absent": True,
        "owned_storage_absent": True,
    }  # also independently checked by cleanup()


def run_case(build, workers, output, sequence, case, role, refusal):
    c.require((case, role, refusal) == CASES[0] and sequence == 1, "a3_case_01_only")
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


def main():
    c.require(len(sys.argv) == 5 and sys.argv[1] == "--a3-case-01", "a3_single_invocation_required")
    build, workers, output = [Path(p).resolve() for p in sys.argv[2:]]
    repo = FOUNDATION.parents[1]
    c.require(output.is_relative_to(repo / "dist") and not output.exists(), "fresh_evidence_root")
    manifest = c.load((build / "build-manifest.json").read_bytes(), 200000)
    for relative, expected in manifest["files"].items():
        raw = (build / relative).read_bytes()
        c.require(
            len(raw) == expected["bytes"] and c.sha(raw) == expected["sha256"], "build_identity"
        )
        if relative.startswith("source/"):
            current = repo / "desktop" / relative.removeprefix("source/")
            c.require(current.read_bytes() == raw, "tested_source_identity")
    c.require(
        (build / "a3-harness.h").read_bytes()
        == instrument((FOUNDATION / "harness.cpp").read_bytes()),
        "exact_two_insertions",
    )
    for role, expected in WORKERS.items():
        c.require(
            c.sha((workers / (role + ".exe")).read_bytes()) == expected, "accepted_worker_identity"
        )
    for name, expected in HISTORY.items():
        run = "m21b-gates-run-01" if name == "original" else "m21b-a1-run-01"
        c.require(
            c.sha((repo / "dist" / run / "completion.json").read_bytes()) == expected,
            "historical_identity",
        )
    initial = {
        "schema": "daf-a3-feasibility/v1",
        "run": uuid.uuid4().hex,
        "build_manifest": c.sha((build / "build-manifest.json").read_bytes()),
        "qualifier": c.sha(Path(__file__).read_bytes()),
        "cases": CASES,
        "retries": 0,
        "historical_failures": HISTORY,
        "gate_b": "unqualified_not_executed",
    }
    # Exclusive consumed claim is retained on every outcome. Not an execution grant.
    publish(repo / "dist" / "m21b-a3-single-execution-claimed.json", initial)
    output.mkdir()
    publish(output / "started.json", initial)
    record = run_case(build, workers, output, 1, *CASES[0])
    complete = record["status"] == "passed"
    label = (
        "Host-owned Gate A inspection feasibility demonstrated."
        if complete
        else "A3 feasibility failed."
    )
    publish(
        output / "completion.json",
        {
            **initial,
            "qualified": False,
            "feasibility_demonstrated": complete,
            "result_label": label,
            "records": [record],
            "other_native_cases_executed": 0,
        },
    )
    print(json.dumps({"result": label, "failure": record.get("failure")}), flush=True)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
