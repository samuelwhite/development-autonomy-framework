"""Maintainer-only Windows feasibility runner. Never part of the desktop bundle.

Usage: bundled-python -I -S -B desktop/isolation/run.py dist/<fresh-test-build>
Runs only the fixed adjacent feasibility.exe and synthetic probes. No shell.
"""

import ctypes as C
import hashlib
import json
import re
import subprocess
import sys
import time
from ctypes import wintypes as W
from pathlib import Path


def load(path):
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("{")
        ]
    except (OSError, ValueError):
        return []


def cleanup(root):
    name = (root / "owned-profile.txt").read_text(encoding="utf-8").splitlines()[0]
    if not re.fullmatch(
        r"DAF\.M21\.Feasibility\.[0-9A-F]{8}-(?:[0-9A-F]{4}-){3}[0-9A-F]{12}", name
    ):
        raise RuntimeError("Invalid owned test profile marker")
    u = C.WinDLL("userenv", use_last_error=True)
    u.DeleteAppContainerProfile.argtypes = [W.LPCWSTR]
    u.DeleteAppContainerProfile.restype = C.c_long
    code = u.DeleteAppContainerProfile(name)
    a = C.WinDLL("advapi32", use_last_error=True)
    a.CredDeleteW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD]
    a.CredDeleteW(name, 1, 0)
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, "Software\\" + name)
    except FileNotFoundError:
        pass
    if code:
        raise RuntimeError(f"Owned profile cleanup failed: {code:#x}")


def spawn(root, mode, name):
    out = (root / f"{name}.jsonl").open("wb")
    err = (root / f"{name}-native.jsonl").open("wb")
    process = subprocess.Popen(
        [str(root / "feasibility.exe"), mode],
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=err,
        creationflags=0x08000000,
    )
    out.close()
    err.close()
    return process


def wait_ready(root, name, process):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any(row.get("probe") == "hold_ready" for row in load(root / f"{name}.jsonl")):
            native = load(root / f"{name}-native.jsonl")
            return next(row["value"] for row in native if row.get("native") == "child_pid")
        if process.poll() is not None:
            raise RuntimeError("Holder exited before ready")
        time.sleep(0.02)
    raise RuntimeError("No holder readiness")


def child_handle(pid):
    k = C.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    handle = k.OpenProcess(0x100000, False, pid)
    if not handle:
        raise C.WinError(C.get_last_error())
    return handle


def wait_child(handle):
    k = C.WinDLL("kernel32", use_last_error=True)
    k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k.CloseHandle.argtypes = [W.HANDLE]
    try:
        if k.WaitForSingleObject(handle, 3000) != 0:
            raise RuntimeError("Contained child survived supervisor death")
    finally:
        k.CloseHandle(handle)


root = Path(sys.argv[1]).resolve()
if not root.is_relative_to(Path(__file__).resolve().parents[2] / "dist"):
    raise RuntimeError("Runner accepts only this repository's dist test builds")
if len(sys.argv) == 3 and sys.argv[2] == "parent":
    holder = spawn(root, "hold", "parent-death")
    wait_ready(root, "parent-death", holder)
    (root / "parent-ready.json").write_text(json.dumps({"helper": holder.pid}), encoding="utf-8")
    holder.wait(timeout=15)
    sys.exit(0)

results = []
for mode in ("baseline", "sealed", "memory", "cpu", "hold"):
    started = time.monotonic()
    before = hashlib.sha256((root / "ambient-shared.txt").read_bytes()).hexdigest()
    process = spawn(root, mode, mode)
    code = process.wait(timeout=15)
    native = load(root / f"{mode}-native.jsonl")
    results.append(
        {
            "case": mode,
            "helper_exit": code,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "native": native,
            "probes": load(root / f"{mode}.jsonl"),
            "ambient_before_sha256": before,
            "ambient_after_sha256": hashlib.sha256(
                (root / "ambient-shared.txt").read_bytes()
            ).hexdigest(),
        }
    )
    if not any(
        row.get("native") == "delete_owned_profile_hresult" and row["value"] == 0 for row in native
    ):
        cleanup(root)

holder = spawn(root, "hold", "helper-death")
pid = wait_ready(root, "helper-death", holder)
handle = child_handle(pid)  # Retain identity, never treat a later reused PID as this process.
started = time.monotonic()
holder.kill()
holder.wait(timeout=3)
wait_child(handle)
results.append(
    {
        "case": "helper_death",
        "child_terminated": True,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
)
cleanup(root)

parent = subprocess.Popen(
    [sys.executable, "-I", "-S", "-B", __file__, str(root), "parent"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=0x08000000,
)
deadline = time.monotonic() + 5
while not (root / "parent-ready.json").exists():
    if parent.poll() is not None or time.monotonic() > deadline:
        raise RuntimeError("Supervising parent failed to become ready")
    time.sleep(0.02)
native = load(root / "parent-death-native.jsonl")
pid = next(row["value"] for row in native if row.get("native") == "child_pid")
helper = json.loads((root / "parent-ready.json").read_text())["helper"]
handle, helper_handle = child_handle(pid), child_handle(helper)
started = time.monotonic()
parent.kill()
parent.wait(timeout=3)
wait_child(handle)
wait_child(helper_handle)
results.append(
    {
        "case": "parent_death",
        "child_and_helper_terminated": True,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "native": load(root / "parent-death-native.jsonl"),
    }
)
cleanup(root)
(root / "lifecycle-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
sealed = next(case for case in results if case["case"] == "sealed")
gate = {
    "qualified": False,
    "implementation_authorized_by_this_report": False,
    "blockers": ["ambient_shared_file_write"]
    if any(
        row.get("probe") == "write_unapproved_ambient_shared_file" and row["status"] == "allowed"
        for row in sealed["probes"]
    )
    else ["requires_complete_independent_qualification"],
    "results": results,
}
(root / "gate-result.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
print(json.dumps({"qualified": False, "blockers": gate["blockers"]}))
# Diagnostic completion is not a passed isolation gate. No launch authority.
sys.exit(2)
