"""Separate readback process; no process launch, cleanup mutation or native retry."""

import ctypes as C
import json
import sys
from ctypes import wintypes as W
from pathlib import Path

import a4_observations as diagnostic
from a3_qualify import verify_cleanup
from a4_qualify import verify_build
from qualify import FOUNDATION, WORKERS, c, publish


def storage_absent(attempt):
    import winreg

    name = (attempt / "owned-profile.txt").read_text().splitlines()[0]
    u, a, k = C.WinDLL("userenv"), C.WinDLL("advapi32"), C.WinDLL("kernel32")
    u.DeriveAppContainerSidFromAppContainerName.argtypes = [W.LPCWSTR, C.POINTER(C.c_void_p)]
    a.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(W.LPWSTR)]
    a.FreeSid.argtypes = [C.c_void_p]
    k.LocalFree.argtypes = [C.c_void_p]
    sid, text = C.c_void_p(), W.LPWSTR()
    c.require(
        u.DeriveAppContainerSidFromAppContainerName(name, C.byref(sid)) == 0, "derive_owned_sid"
    )
    try:
        c.require(a.ConvertSidToStringSidW(sid, C.byref(text)), "owned_sid_string")
        key = (
            r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
            r"\AppContainer\Storage" + "\\" + text.value
        )
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
                raise RuntimeError("owned_storage_remains")
        except FileNotFoundError:
            pass
    finally:
        if text:
            k.LocalFree(C.cast(text, C.c_void_p))
        if sid:
            a.FreeSid(sid)


def fixture_file_identity(path):
    class FileId(C.Structure):
        _fields_ = [("volume", C.c_ulonglong), ("identifier", C.c_ubyte * 16)]

    k = C.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    k.CreateFileW.restype = W.HANDLE
    k.GetFileInformationByHandleEx.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
    k.CloseHandle.argtypes = [W.HANDLE]
    handle = k.CreateFileW(str(path), 0x80, 3, None, 3, 0, None)
    c.require(handle and handle != C.c_void_p(-1).value, "readback_fixture_open")
    try:
        value = FileId()
        c.require(
            k.GetFileInformationByHandleEx(handle, 18, C.byref(value), C.sizeof(value)),
            "readback_file_identity",
        )
        raw = bytes(value.identifier)
        return {
            "volume": value.volume,
            "file_low": int.from_bytes(raw[:8], "little"),
            "file_high": int.from_bytes(raw[8:], "little"),
        }
    finally:
        k.CloseHandle(handle)


def verify(output, case):
    c.require(case in ("A4-01", "A4-02"), "a4_readback_case")
    repo = FOUNDATION.parents[1]
    c.require(output.is_relative_to(repo / "dist"), "readback_owned_root")
    sequence = 1 if case == "A4-01" else 2
    attempt = output / f"{sequence:02d}-{case}-probe"
    raw = (output / f"{case}-completion.json").read_bytes()
    complete = c.load(raw, 100000)
    result_raw = (attempt / "result.json").read_bytes()
    record = c.load(result_raw, 100000)
    c.require(
        complete["records"] == [record] and record["status"] == "passed", "complete_case_result"
    )
    c.require(
        complete["case"] == case and complete["retries"] == 0 and complete["qualified"] is False,
        "case_completion",
    )
    c.require(complete["initial_detector_sensitivity"] is True, "case_outcome")
    checked = diagnostic.validate(record)
    c.require(json.loads(json.dumps(checked)) == record["inspection"], "saved_inspection")
    start = (output / f"{case}-started.json").read_bytes()
    claim = repo / "dist" / f"m21b-a4-0{sequence}-execution-claimed.json"
    c.require(start == claim.read_bytes(), "consumed_claim_identity")
    for key, value in c.load(start, 100000).items():
        c.require(complete.get(key) == value, "start_completion_identity")
    build = (repo / complete["build_directory"]).resolve()
    c.require(build.is_relative_to(repo / "dist"), "readback_owned_build")
    c.require(
        verify_build(build, repo / "dist/m21a-persistence-01") == complete["build_manifest"],
        "readback_build_identity",
    )
    for target, source in (("harness.exe", "fixture-host.exe"), ("probe.exe", "handle-probe.exe")):
        c.require(
            (attempt / target).read_bytes() == (build / source).read_bytes(), "executed_image_copy"
        )
    for role, expected in WORKERS.items():
        c.require(
            c.sha((attempt / (role + ".exe")).read_bytes()) == expected, "unchanged_worker_copy"
        )
    for leaf, expected in {
        "smuggled-read.txt": b"R" * 32,
        "smuggled-write.txt": b"S" * 32,
        "ambient-shared.txt": b"Synthetic resource shared with all LPACs",
        "request.bin": b"",
    }.items():
        c.require((attempt / leaf).read_bytes() == expected, "independent_fixture_bytes")
    values = {r["native"]: r["value"] for r in record["observations"] if "value" in r}
    identity = fixture_file_identity(attempt / "smuggled-read.txt")
    for key, value in identity.items():
        c.require(
            values["a4_original_" + key] == value == values["a3_fixture_" + key],
            "independent_fixture_identity",
        )
    cleaned = verify_cleanup(attempt, record["observations"], values["helper_pid"])
    storage_absent(attempt)
    receipt = {
        "schema": "daf-a4-independent/v1",
        "case": case,
        "independently_verified": True,
        "qualified": False,
        "completion_sha256": c.sha(raw),
        "result_sha256": c.sha(result_raw),
        "build_manifest": complete["build_manifest"],
        "verifier_sha256": c.sha(Path(__file__).read_bytes()),
        "inspection": checked,
        "cleanup_readback": cleaned,
        "fixture_file_identity": identity,
        "fixture_bytes_unchanged": True,
        "owned_registry_storage_independently_absent": True,
        "native_processes_launched_by_readback": 0,
    }
    path = output / f"{case}-independent.json"
    publish(path, receipt)
    return {
        "case": case,
        "independently_verified": True,
        "receipt_sha256": c.sha(path.read_bytes()),
    }


if __name__ == "__main__":
    c.require(len(sys.argv) == 3, "readback_arguments")
    print(json.dumps(verify(Path(sys.argv[1]).resolve(), sys.argv[2])))
