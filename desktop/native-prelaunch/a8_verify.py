"""Independent original-byte readback; never launches, retries or repairs a case."""

import ctypes as C
from ctypes import wintypes as W

import a8_observations as diagnostic
from a8_qualify import require_native_release, stop, verify_build
from qualify import a, c, publish


def native_resource_readback(attempt, record):
    """Exact recorded owned resources only; no launch, termination or repair."""
    from a3_qualify import verify_cleanup
    from a4_verify import fixture_file_identity, storage_absent
    from qualify import WORKERS

    rows = record["observations"]
    values = {row["native"]: row["value"] for row in rows if "value" in row}
    helper = record["helper_identity"]
    c.require(
        helper["query_ok"]
        and helper["pid"] == values["helper_pid"] == values["a1_control_h4_process_pid"]
        and helper["creation"] == values["a1_control_h4_process_creation"],
        "owned_helper_binding",
    )
    child = values["a3_expected_pid"]
    c.require(
        child == values["a3_created_pid"] == values["child_pid"] and child != helper["pid"],
        "owned_child_binding",
    )
    expected = {
        child: (values["a3_expected_creation"], 123),
        helper["pid"]: (helper["creation"], int(record["case"] == "A8-S1")),
    }
    k = C.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    k.CloseHandle.argtypes = [W.HANDLE]
    k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    k.GetProcessTimes.argtypes = [W.HANDLE, *([C.POINTER(W.FILETIME)] * 4)]
    processes = []
    for pid, (creation, exit_code) in sorted(expected.items()):
        c.require(
            type(pid) is int and 0 < pid < 2**32 and creation > 0, "recorded_process_identity"
        )
        handle = k.OpenProcess(0x101000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
        error = C.get_last_error()
        if not handle:
            c.require(error == 87, "process_absence_ambiguous")
            processes.append({"pid": pid, "terminated": True, "open_error": error})
            continue
        try:
            times = [W.FILETIME() for _ in range(4)]
            ok = k.GetProcessTimes(handle, *(C.byref(value) for value in times))
            actual = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            code = W.DWORD()
            c.require(ok and actual == creation, "pid_reuse_or_identity_ambiguity")
            c.require(
                k.WaitForSingleObject(handle, 0) == 0
                and k.GetExitCodeProcess(handle, C.byref(code))
                and code.value == exit_code,
                "owned_process_survived",
            )
            processes.append(
                {"pid": pid, "creation": actual, "terminated": True, "wait": 0, "exit": code.value}
            )
        finally:
            k.CloseHandle(handle)
    for leaf, expected_bytes in {
        "smuggled-read.txt": b"R" * 32,
        "smuggled-write.txt": b"S" * 32,
        "ambient-shared.txt": b"Synthetic resource shared with all LPACs",
        "request.bin": b"",
    }.items():
        c.require((attempt / leaf).read_bytes() == expected_bytes, "fixture_bytes")
    for role, digest in WORKERS.items():
        c.require(c.sha((attempt / (role + ".exe")).read_bytes()) == digest, "worker_copy")
    for i, name in enumerate(("read", "write")):
        for key, value in fixture_file_identity(attempt / f"smuggled-{name}.txt").items():
            c.require(values[f"a1_control_h{i}_" + key] == value, "fixture_identity")
    cleaned = verify_cleanup(attempt, rows, helper["pid"])
    storage_absent(attempt)
    return {**cleaned, "processes": processes}


def verify(output, case, resource_readback=None):
    """Independent readback. Native activation remains explicitly refused."""
    c.require(not (output / "STOP.json").exists(), "irreversible_stop")
    result_raw = (output / f"{case}-result.json").read_bytes()
    result = c.load(result_raw, 100000)
    mode = result["mode"]
    c.require(result["case"] == case and mode in ("simulated", "native"), "readback_binding")
    if mode == "native":
        require_native_release()
        from qualify import FOUNDATION

        repo = FOUNDATION.parents[1]
        c.require(
            resource_readback is None and output.is_relative_to(repo / "dist"),
            "native_readback_adapter",
        )
        binding = c.load((repo / "dist/m21b-a8-exercise-claimed.json").read_bytes(), 100000)
        build = (repo / binding["build_directory"]).resolve()
        c.require(
            binding["output"] == output.relative_to(repo).as_posix()
            and verify_build(build, repo / "dist/m21a-persistence-01")
            == result["build_manifest"]
            == binding["build_manifest"],
            "native_readback_build",
        )
        claim = c.load(
            (repo / "dist" / f"m21b-a8-{case}-execution-claimed.json").read_bytes(), 100000
        )
        c.require(claim == {**binding, "case": case}, "native_global_claim")
        for target, source in (
            ("harness.exe", "a8-fixture-host.exe"),
            ("probe.exe", "handle-probe.exe"),
        ):
            c.require(
                (output / case / target).read_bytes() == (build / source).read_bytes(),
                "native_executed_copy",
            )

        def resource_readback():
            return native_resource_readback(output / case, result["evidence"])

    c.require(callable(resource_readback), "independent_readback_required")
    try:
        evidence = result["evidence"]
        for name, field in (("stdout.capture", "stdout"), ("stderr.jsonl", "stderr")):
            raw = (output / f"{case}-{name}").read_bytes()
            c.require(
                len(raw) == evidence[field]["bytes"] and c.sha(raw) == evidence[field]["sha256"],
                "capture_identity",
            )
        original = a.observations((output / f"{case}-stderr.jsonl").read_bytes())
        c.require(original == evidence["observations"], "original_observations")
        checked = diagnostic.validate({**evidence, "independent_cleanup": resource_readback()})
        c.require(
            checked == result["control"] and result["status"] == "expected_control_observed",
            "control_identity",
        )
        claim = c.load((output / f"{case}-claimed.json").read_bytes(), 100000)
        c.require(
            claim == c.load((output / f"{case}-started.json").read_bytes(), 100000), "claim_binding"
        )
        for key, value in claim.items():
            c.require(result[key] == value, "result_binding")
        receipt = {
            "schema": "daf-a8-independent/v1",
            "case": case,
            "mode": mode,
            "build_manifest": result["build_manifest"],
            "result_sha256": c.sha(result_raw),
            "independently_verified": True,
            "qualified": False,
            "execution_authority": False,
            "control": checked,
            "native_processes_launched": 0,
        }
        publish(output / f"{case}-independent.json", receipt)
        return receipt
    except Exception as error:
        stop(
            output,
            case,
            {"stage": "independent_readback", "type": type(error).__name__},
            mode,
        )
        raise


if __name__ == "__main__":
    raise PermissionError("A8 native verification activation requires separate Product review")
