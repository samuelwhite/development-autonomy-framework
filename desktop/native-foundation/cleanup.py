"""Cleanup only recorded generated acceptance identities; no general delete API."""

import ctypes as C
import re
from ctypes import wintypes as W
from pathlib import Path


def cleanup(attempt):
    """Only the exact generated identity, including its manually created empty key."""
    import winreg

    name, profile = (attempt / "owned-profile.txt").read_text().splitlines()[:2]
    if not re.fullmatch(
        r"DAF\.M21A\.Acceptance\.[0-9A-F]{8}-(?:[0-9A-F]{4}-){3}[0-9A-F]{12}", name
    ):
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
