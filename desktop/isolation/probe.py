"""Adversarial standalone probe; runs ONLY in the feasibility LPAC, not DAF.

All credential/file payloads are synthetic. No real credential enumeration.
"""

import ctypes as C
import json
import os
import socket
import subprocess
import sys
import time
import winreg
from ctypes import wintypes as W
from pathlib import Path


def emit(name, status, **details):
    print(json.dumps({"probe": name, "status": status, **details}), flush=True)


def attempt(name, operation):
    try:
        value = operation()
        emit(name, "allowed", value=value)
    except OSError as exc:
        emit(
            name,
            "denied" if exc.winerror in (5, 367, 10013, 1314) or exc.errno == 13 else "error",
            winerror=exc.winerror,
            errno=exc.errno,
            message=str(exc),
        )
    except Exception as exc:
        emit(name, "error", message=str(exc))


root = Path(os.environ["DAF_ROOT"])
profile = Path(os.environ["DAF_PROFILE"])
emit(
    "runtime",
    "observed",
    version=sys.version,
    pid=os.getpid(),
    temp=os.environ.get("TEMP"),
    localappdata=os.environ.get("LOCALAPPDATA"),
)
if os.environ["DAF_PROBE_MODE"] == "hold":
    emit("hold_ready", "observed")
    time.sleep(60)
    sys.exit(0)
if os.environ["DAF_PROBE_MODE"] == "cpu":
    emit("cpu_ready", "observed")
    while True:
        pass
if os.environ["DAF_PROBE_MODE"] == "memory":
    try:
        allocation = bytearray(160 * 1024 * 1024)
    except MemoryError:
        emit("memory_limit", "denied")
        sys.exit(0)
    emit("memory_limit", "allowed", value=len(allocation))
    sys.exit(1)


def read(path):
    return len(path.read_bytes())


def write(path):
    with path.open("xb") as stream:
        stream.write(b"synthetic probe")
    path.unlink()
    return True


attempt("read_allowed_fixture", lambda: read(root / "allowed.txt"))
attempt("read_host_private_fixture", lambda: read(root / "private.txt"))
attempt("write_workspace", lambda: write(root / "worker-created.txt"))
attempt("write_runtime", lambda: write(root / "runtime" / "worker-created.txt"))


def ambient_write():
    with (root / "ambient-shared.txt").open("ab") as stream:
        stream.write(b"\nUNAPPROVED WRITE from feasibility child")
    return True


attempt("write_unapproved_ambient_shared_file", ambient_write)
attempt("write_profile_root", lambda: write(profile / "worker-created.txt"))
attempt("write_profile_package_root", lambda: write(profile.parent / "worker-created.txt"))
attempt("write_profile_temp", lambda: write(profile / "Temp" / "worker-created.txt"))
attempt("write_effective_temp", lambda: write(Path(os.environ["TEMP"]) / "worker-created.txt"))
attempt("read_profile_sentinel", lambda: read(profile / "owned-sentinel.txt"))


def append_profile():
    with (profile / "owned-sentinel.txt").open("ab") as stream:
        stream.write(b"changed")
    return True


attempt("append_profile_file", append_profile)
advapi = C.WinDLL("advapi32", use_last_error=True)
advapi.SetNamedSecurityInfoW.argtypes = [
    W.LPWSTR,
    W.DWORD,
    W.DWORD,
    C.c_void_p,
    C.c_void_p,
    C.c_void_p,
    C.c_void_p,
]
advapi.SetNamedSecurityInfoW.restype = W.DWORD


def replace_profile_dacl():
    # Attempt an owner-rights bypass: null DACL on this owned synthetic file.
    result = advapi.SetNamedSecurityInfoW(
        str(profile / "owned-sentinel.txt"), 1, 4, None, None, None, None
    )
    if result:
        raise C.WinError(result)
    return True


if os.environ["DAF_PROBE_MODE"] == "baseline":
    emit("replace_profile_dacl", "not_run", reason="Preserve the negative-control profile ACL")
else:
    attempt("replace_profile_dacl", replace_profile_dacl)
attempt("append_after_dacl_attempt", append_profile)


def change_owner_dacl(path):
    result = advapi.SetNamedSecurityInfoW(str(path), 1, 4, None, None, None, None)
    if result:
        raise C.WinError(result)
    return True


if os.environ["DAF_PROBE_MODE"] == "baseline":
    emit("replace_profile_root_dacl", "not_run", reason="Preserve negative-control ACL")
    emit("replace_temp_dacl", "not_run", reason="Preserve negative-control ACL")
else:
    attempt("replace_profile_root_dacl", lambda: change_owner_dacl(profile))
    attempt("replace_temp_dacl", lambda: change_owner_dacl(profile / "Temp"))
attempt("write_after_directory_dacl_attempt", lambda: write(profile / "worker-created.txt"))
attempt(
    "write_host_profile",
    lambda: write(Path(os.environ["USERPROFILE"]) / (os.environ["DAF_CREDENTIAL_TARGET"] + ".txt")),
)
attempt(
    "write_windows_temp",
    lambda: write(
        Path(os.environ["SystemRoot"]) / "Temp" / (os.environ["DAF_CREDENTIAL_TARGET"] + ".txt")
    ),
)


def registry_read():
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    ) as key:
        return winreg.QueryValueEx(key, "CurrentBuildNumber")[0]


def registry_write():
    # Only a unique synthetic key. Never query or mutate existing user settings.
    name = "Software\\" + os.environ["DAF_CREDENTIAL_TARGET"]
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, name, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, "probe", 0, winreg.REG_SZ, "synthetic")
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, name)
    return True


def registry_profile():
    userenv = C.WinDLL("userenv", use_last_error=True)
    key = W.HANDLE()
    userenv.GetAppContainerRegistryLocation.argtypes = [W.DWORD, C.POINTER(W.HANDLE)]
    userenv.GetAppContainerRegistryLocation.restype = C.c_long
    result = userenv.GetAppContainerRegistryLocation(
        winreg.KEY_READ | winreg.KEY_WRITE, C.byref(key)
    )
    if result < 0:
        raise C.WinError(result & 0xFFFF)
    try:
        winreg.SetValueEx(key.value, "DAF-synthetic-probe", 0, winreg.REG_SZ, "synthetic")
        winreg.DeleteValue(key.value, "DAF-synthetic-probe")
    finally:
        winreg.CloseKey(key.value)
    return True


attempt("registry_machine_read", registry_read)


def read_host_registry():
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Software\\" + os.environ["DAF_CREDENTIAL_TARGET"]
    ) as key:
        value, _ = winreg.QueryValueEx(key, "HostPrivateSentinel")
        return len(value)


attempt("read_host_private_registry_fixture", read_host_registry)
attempt("registry_user_write", registry_write)
attempt("registry_profile_write", registry_profile)


def registry_dacl():
    userenv = C.WinDLL("userenv", use_last_error=True)
    key = W.HANDLE()
    userenv.GetAppContainerRegistryLocation.argtypes = [W.DWORD, C.POINTER(W.HANDLE)]
    userenv.GetAppContainerRegistryLocation.restype = C.c_long
    result = userenv.GetAppContainerRegistryLocation(0x40000, C.byref(key))
    if result < 0:
        raise C.WinError(result & 0xFFFF)
    winreg.CloseKey(key.value)
    return "WRITE_DAC granted"


attempt("registry_profile_write_dacl", registry_dacl)


def reinitialize_own_profile():
    userenv = C.WinDLL("userenv", use_last_error=True)
    sid = C.c_void_p()
    userenv.CreateAppContainerProfile.argtypes = [
        W.LPCWSTR,
        W.LPCWSTR,
        W.LPCWSTR,
        C.c_void_p,
        W.DWORD,
        C.POINTER(C.c_void_p),
    ]
    userenv.CreateAppContainerProfile.restype = C.c_long
    result = userenv.CreateAppContainerProfile(
        os.environ["DAF_CREDENTIAL_TARGET"],
        "DAF synthetic probe",
        "synthetic",
        None,
        0,
        C.byref(sid),
    )
    if sid:
        advapi.FreeSid.argtypes = [C.c_void_p]
        advapi.FreeSid(sid)
    if result < 0:
        raise C.WinError(result & 0xFFFF)
    return True


attempt("reinitialize_own_profile", reinitialize_own_profile)
attempt("write_profile_after_reinitialize", lambda: write(profile / "worker-created.txt"))
attempt("write_temp_after_reinitialize", lambda: write(profile / "Temp" / "worker-created.txt"))
attempt("registry_write_after_reinitialize", registry_profile)


def credential_read():
    credential = C.c_void_p()
    advapi.CredReadW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(C.c_void_p)]
    advapi.CredReadW.restype = W.BOOL
    if not advapi.CredReadW(os.environ["DAF_CREDENTIAL_TARGET"], 1, 0, C.byref(credential)):
        raise C.WinError(C.get_last_error())
    advapi.CredFree(credential)
    return "synthetic credential accessible"


class Blob(C.Structure):
    _fields_ = [("size", W.DWORD), ("data", C.POINTER(C.c_ubyte))]


def dpapi_read():
    data = (root / "protected.bin").read_bytes()
    buf = (C.c_ubyte * len(data)).from_buffer_copy(data)
    source, output = Blob(len(data), buf), Blob()
    crypt = C.WinDLL("crypt32", use_last_error=True)
    crypt.CryptUnprotectData.argtypes = [
        C.POINTER(Blob),
        C.c_void_p,
        C.c_void_p,
        C.c_void_p,
        C.c_void_p,
        W.DWORD,
        C.POINTER(Blob),
    ]
    if not crypt.CryptUnprotectData(C.byref(source), None, None, None, None, 1, C.byref(output)):
        raise C.WinError(C.get_last_error())
    C.windll.kernel32.LocalFree(C.cast(output.data, C.c_void_p))
    return "synthetic host-user DPAPI blob decrypted"


attempt("host_credential_read", credential_read)
attempt("host_dpapi_decrypt", dpapi_read)


def tcp(host):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        sock.connect((host, 49372))
    return True


def udp(host):
    with socket.socket(type=socket.SOCK_DGRAM) as sock:
        sock.settimeout(0.5)
        return sock.sendto(b"DAF synthetic isolation probe", (host, 49372))


attempt("loopback_tcp", lambda: tcp("127.0.0.1"))
attempt("loopback_udp", lambda: udp("127.0.0.1"))
attempt("external_tcp_testnet", lambda: tcp("203.0.113.1"))
attempt("external_udp_testnet", lambda: udp("203.0.113.1"))
attempt("dns_resolution", lambda: len(socket.getaddrinfo("example.com", 443)))


def child(breakaway=False):
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", "pass"],
        timeout=1,
        check=True,
        capture_output=True,
        creationflags=0x08000000 | (0x01000000 if breakaway else 0),
    )
    return completed.returncode


attempt("child_process", child)
attempt("breakaway_child", lambda: child(True))
emit("probe_complete", "observed")
