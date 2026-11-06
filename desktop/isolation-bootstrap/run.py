"""Fixed Windows bootstrap/containment matrix. Never grants execution authority."""

import ctypes as C
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from ctypes import wintypes as W
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    return [
        json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.startswith("{")
    ]


def value(items, kind, name, field="value"):
    found = [r[field] for r in items if r.get(kind) == name and field in r]
    if len(found) != 1:
        raise RuntimeError(f"Missing or duplicate observation: {name}")
    return found[0]


def cleanup(attempt):
    """Only the exact generated identity, including its manually created empty key."""
    import winreg

    name, profile = (attempt / "owned-profile.txt").read_text().splitlines()[:2]
    if not re.fullmatch(r"DAF\.M21\.Bootstrap\.[0-9A-F]{8}-(?:[0-9A-F]{4}-){3}[0-9A-F]{12}", name):
        raise RuntimeError("Invalid owned profile marker")
    u, a, k = C.WinDLL("userenv"), C.WinDLL("advapi32"), C.WinDLL("kernel32")
    u.DeriveAppContainerSidFromAppContainerName.argtypes = [W.LPCWSTR, C.POINTER(C.c_void_p)]
    u.DeleteAppContainerProfile.argtypes = [W.LPCWSTR]
    u.DeleteAppContainerProfile.restype = C.c_long
    a.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(W.LPWSTR)]
    a.FreeSid.argtypes = [C.c_void_p]
    a.CredDeleteW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD]
    k.LocalFree.argtypes = [C.c_void_p]
    sid, text = C.c_void_p(), W.LPWSTR()
    assert u.DeriveAppContainerSidFromAppContainerName(name, C.byref(sid)) == 0
    assert a.ConvertSidToStringSidW(sid, C.byref(text))
    storage = (
        r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
        r"\AppContainer\Storage" + "\\" + text.value
    )
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, storage) as key:
            children, values, _ = winreg.QueryInfoKey(key)
            assert children == 0 and values == 0, "Refuse nonempty storage cleanup"
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, storage)
    except FileNotFoundError:
        pass
    assert u.DeleteAppContainerProfile(name) == 0
    a.CredDeleteW(name, 1, 0)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, "Software\\" + name)
    except FileNotFoundError:
        pass
    k.LocalFree(C.cast(text, C.c_void_p))
    a.FreeSid(sid)
    assert not Path(profile).parent.exists()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, storage):
            raise RuntimeError("Owned registry storage remains")
    except FileNotFoundError:
        pass


def spawn(root, name, target, mode="sealed", policy="write-restricted"):
    attempt = root / "attempts" / name
    attempt.mkdir(parents=True, exist_ok=False)
    files = [
        "launcher.exe",
        "native-minimal.exe",
        "native-static.exe",
        "dbghelp.dll",
        "symsrv.dll",
        "probe.py",
        "allowed.txt",
        "private.txt",
        "ambient-shared.txt",
        "dual-grant.txt",
        "protected.bin",
        "fixture-root.marker",
    ]
    for file in files:
        shutil.copyfile(root / file, attempt / file)
    shutil.copytree(root / "runtime", attempt / "runtime")
    with (attempt / "child.jsonl").open("xb") as out, (attempt / "native.log").open("xb") as err:
        process = subprocess.Popen(
            [str(attempt / "launcher.exe"), policy, mode, target],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            creationflags=0x08000000,
        )
    return process, attempt


def ambient_guard(root, attempt):
    if sha(root / "ambient-shared.txt") != sha(attempt / "ambient-shared.txt"):
        raise RuntimeError("BLOCKING ambient write: stop all investigation cases")
    child, native = rows(attempt / "child.jsonl"), rows(attempt / "native.log")
    if any(r.get("probe") == "BLOCKING_ambient_write" for r in child):
        raise RuntimeError("BLOCKING ambient write reported by child")
    if any(r.get("native") == "native_ambient_write" and r.get("allowed") for r in native):
        raise RuntimeError("BLOCKING ambient write reported by native token probe")


def report(root, attempt, exit_code, elapsed):
    ambient_guard(root, attempt)
    native = rows(attempt / "native.log")
    # Only fixed kernel-device traces are public; other paths remain in local raw logs.
    traces = [r for r in native if r.get("trace") and r.get("object") == r"\Device\KsecDD"]
    native = [r for r in native if "native" in r]
    return {
        "case": attempt.name,
        "helper_exit": exit_code,
        "elapsed_seconds": round(elapsed, 3),
        "native": native,
        "probes": rows(attempt / "child.jsonl"),
        "cng_trace": traces,
        "ambient_sha256": sha(attempt / "ambient-shared.txt"),
        "dual_after_sha256": sha(attempt / "dual-grant.txt"),
        "native_log_sha256": sha(attempt / "native.log"),
        "child_log_sha256": sha(attempt / "child.jsonl"),
    }


def ordinary(root, name, target, mode="sealed", policy="write-restricted"):
    process, attempt = spawn(root, name, target, mode, policy)
    started = time.monotonic()
    try:
        code = process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
        cleanup(attempt)
        raise RuntimeError("Diagnostic deadline exceeded; no next case") from None
    result = report(root, attempt, code, time.monotonic() - started)
    cleanup(attempt)
    return result


def ready(attempt, process):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any(r.get("probe") == "hold_ready" for r in rows(attempt / "child.jsonl")):
            return value(rows(attempt / "native.log"), "native", "child_pid")
        if process.poll() is not None:
            raise RuntimeError("Holder failed before readiness; NOT a lifecycle pass")
        time.sleep(0.02)
    raise RuntimeError("No holder readiness")


def process_handle(pid):
    k = C.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    handle = k.OpenProcess(0x100000, False, pid)
    if not handle:
        raise C.WinError(C.get_last_error())
    return handle


def terminated(handle):
    k = C.WinDLL("kernel32")
    k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k.CloseHandle.argtypes = [W.HANDLE]
    try:
        assert k.WaitForSingleObject(handle, 3000) == 0, "Contained process survived"
    finally:
        k.CloseHandle(handle)


def run_matrix(root):
    results = []
    for name, target, mode, policy in [
        ("python-normal", "python", "sealed", "write-restricted"),
        ("python-traced", "python", "debug", "write-restricted"),
        ("native-minimal", "native-minimal", "sealed", "write-restricted"),
        ("native-dependency", "native-static", "dependency", "write-restricted"),
        ("native-suite", "native-static", "sealed", "write-restricted"),
        ("full-read-restriction", "native-minimal", "sealed", "full-restricted"),
        ("memory", "native-static", "memory", "write-restricted"),
        ("cpu", "native-static", "cpu", "write-restricted"),
        ("wall", "native-static", "hold", "write-restricted"),
    ]:
        result = ordinary(root, name, target, mode, policy)
        results.append(result)
        print(json.dumps({"case": name, "helper_exit": result["helper_exit"]}), flush=True)
        if name in ("native-minimal", "native-suite") and result["helper_exit"] != 0:
            raise RuntimeError("Native startup/suite failed; no further containment claim")
        if name == "native-suite":
            assert value(result["probes"], "probe", "native_suite_complete", "code") == 0
        if name == "full-read-restriction" and result["helper_exit"] == 0:
            results.append(
                ordinary(root, "full-native-suite", "native-static", policy="full-restricted")
            )
    holder, attempt = spawn(root, "helper-death", "native-static", "hold")
    handle = process_handle(ready(attempt, holder))
    ambient_guard(root, attempt)
    started = time.monotonic()
    holder.kill()
    holder.wait(timeout=3)
    terminated(handle)
    result = report(root, attempt, holder.returncode, time.monotonic() - started)
    result["child_handle_signalled"] = True
    results.append(result)
    cleanup(attempt)
    parent = subprocess.Popen(
        [sys.executable, "-I", "-S", "-B", __file__, str(root), "parent"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000,
    )
    marker = root / "parent-ready.json"
    deadline = time.monotonic() + 5
    while not marker.exists():
        if parent.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("Parent failed before readiness")
        time.sleep(0.02)
    record = json.loads(marker.read_text())
    child, helper = process_handle(record["child"]), process_handle(record["helper"])
    attempt = root / "attempts/parent-death"
    ambient_guard(root, attempt)
    started = time.monotonic()
    parent.kill()
    parent.wait(timeout=3)
    terminated(child)
    terminated(helper)
    result = report(root, attempt, None, time.monotonic() - started)
    result["child_and_helper_handles_signalled"] = True
    results.append(result)
    cleanup(attempt)
    return results


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "parent"):
        raise SystemExit("Usage: run.py dist/<fresh-build>")
    root = Path(sys.argv[1]).resolve()
    if not root.is_relative_to(Path(__file__).resolve().parents[2] / "dist"):
        raise RuntimeError("Only this repository's generated dist fixtures are accepted")
    if len(sys.argv) == 3:
        holder, attempt = spawn(root, "parent-death", "native-static", "hold")
        pid = ready(attempt, holder)
        with (root / "parent-ready.json").open("x", encoding="utf-8") as out:
            json.dump({"child": pid, "helper": holder.pid}, out)
        holder.wait(timeout=15)
        return 0
    if (root / "attempts").exists():
        raise RuntimeError("Fresh build required; never overwrite evidence")
    manifest = json.loads((root / "build-manifest.json").read_text())
    for path, identity in manifest["files"].items():
        assert sha(root / path) == identity["sha256"], f"Build input changed: {path}"
    results = run_matrix(root)
    record = {
        "schema": "daf-bootstrap-result/v1",
        "execution_authority": False,
        "production_qualified": False,
        "strict_read_isolation": False,
        "build_manifest_sha256": sha(root / "build-manifest.json"),
        "results": results,
    }
    with (root / "results.json").open("x", encoding="utf-8") as out:
        json.dump(record, out, indent=2)
    print(
        json.dumps(
            {"cases": len(results), "production_qualified": False, "execution_authority": False}
        ),
        flush=True,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
