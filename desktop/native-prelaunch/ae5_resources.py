"""Exact-resource diagnostic ledger adapter. Never used by the safety lane.

Recovery is separately source-gated and never infers ownership from a prefix.
Interrupted creation transactions remain unresolved. No recursive filesystem or
registry deletion is implemented here; profile removal uses its scoped OS API.
"""

import ctypes as C
from ctypes import wintypes as W
from pathlib import Path

from ae5_contract import MAX_DESCRIPTOR, PROFILE, exact, integer, require
from ae5_windows import HANDLE, INVALID, FileInfo, bind

RECOVERY_RELEASE = False
STORAGE = (
    "Software\\Classes\\Local Settings\\Software\\Microsoft\\Wind"
    "ows\\CurrentVersion\\AppContainer\\Storage"
)
MAPPINGS = (
    "Software\\Classes\\Local Settings\\Software\\Microsoft\\Wind"
    "ows\\CurrentVersion\\AppContainer\\Mappings"
)


def file_binding(backend, handle):
    info = FileInfo()
    backend.check(backend.k.GetFileInformationByHandle(handle, C.byref(info)))
    require(not info.attributes & 0x400, "resource_reparse_point")
    require(info.attributes & 0x10 or info.links == 1, "resource_hardlink")
    text = C.create_unicode_buffer(32768)
    length = backend.k.GetFinalPathNameByHandleW(handle, text, len(text), 0)
    require(0 < length < len(text), "resource_final_path")
    path = text.value
    require(
        path.startswith("\\\\?\\") and not path.startswith("\\\\?\\UNC\\"), "local_resource_path"
    )
    return {
        "path": str(Path(path[4:])),
        "volume": info.volume,
        "file_id": info.id_low | info.id_high << 32,
        "attributes": info.attributes,
        "links": info.links,
    }


def descriptor(backend, handle, object_type, information):
    sd, acl = HANDLE(), HANDLE()
    require(
        backend.a.GetSecurityInfo(
            handle,
            object_type,
            information,
            None,
            None,
            C.byref(acl) if information == 4 else None,
            C.byref(acl) if information == 16 else None,
            C.byref(sd),
        )
        == 0,
        "resource_descriptor_query",
    )
    try:
        size = backend.a.GetSecurityDescriptorLength(sd)
        control, revision = W.WORD(), W.DWORD()
        require(
            0 < size <= MAX_DESCRIPTOR
            and backend.a.IsValidSecurityDescriptor(sd)
            and backend.a.GetSecurityDescriptorControl(sd, C.byref(control), C.byref(revision))
            and control.value & 0x8000,
            "bounded_self_relative_descriptor",
        )
        return C.string_at(sd, size).hex()
    finally:
        backend.k.LocalFree(sd)


def open_exact(b, name, expected=None):
    path = Path(name)
    require(path.is_absolute() and path.resolve(strict=True) == path, "canonical_resource_path")
    require(
        path.is_relative_to(b.root)
        or b.profile
        and b.profile["storage"]
        and path.is_relative_to(b.profile["storage"]),
        "owned_resource_path",
    )
    for parent in (path, *path.parents):
        require(not parent.is_symlink() and not parent.is_junction(), "resource_ancestor_link")
    handle = b.k.CreateFileW(str(path), 0x60000, 7, None, 3, 0x02200000, None)
    require(handle and handle != INVALID, "open_owned_resource")
    try:
        actual = file_binding(b, handle)
        require(
            actual["path"] == str(path) and (expected is None or actual == expected),
            "resource_identity_changed",
        )
        return handle, actual
    except BaseException:
        b.close(handle)
        raise


def profile_sid(backend, name):
    sid, text = HANDLE(), HANDLE()
    require(
        backend.u.DeriveAppContainerSidFromAppContainerName(name, C.byref(sid)) == 0,
        "derive_profile_sid",
    )
    try:
        backend.check(backend.a.ConvertSidToStringSidW(sid, C.byref(text)))
        return C.wstring_at(text)
    finally:
        if text:
            backend.k.LocalFree(text)
        backend.a.FreeSid(sid)


def registry_absent(name):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, name, 0, winreg.KEY_READ):
            return False
    except FileNotFoundError:
        return True


def credential_absent(backend, name):
    bind(backend.a, "CredReadW", W.BOOL, W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(HANDLE))
    bind(backend.a, "CredFree", None, HANDLE)
    pointer = HANDLE()
    if backend.a.CredReadW(name, 1, 0, C.byref(pointer)):
        backend.a.CredFree(pointer)  # Never read or serialize credential bytes.
        return False
    require(C.get_last_error() == 1168, "credential_absence_unknown")
    return True


def desktop_absent(name):
    user = C.WinDLL("user32", use_last_error=True)
    bind(user, "OpenDesktopW", HANDLE, W.LPCWSTR, W.DWORD, W.BOOL, W.DWORD)
    bind(user, "CloseDesktop", W.BOOL, HANDLE)
    handle = user.OpenDesktopW(name, 0, False, 0x20000)
    if handle:
        user.CloseDesktop(handle)
        return False
    require(C.get_last_error() == 2, "desktop_absence_unknown")
    return True


def resource_intent(b, data):
    exact(data, ("kind", "name", "handle", "object", "information", "original"))
    require(b.pending_resource is None, "overlapping_resource")
    kind, name = data["kind"], data["name"]
    require(type(name) is str and 0 < len(name) <= 2048 and "\x00" not in name, "resource_name")
    integer(data["handle"])
    integer(data["object"])
    integer(data["information"])
    require(
        type(data["original"]) is str and len(data["original"]) <= MAX_DESCRIPTOR * 2,
        "resource_descriptor_bound",
    )
    identity, original = {}, ""
    if kind == "profile":
        require(b.profile is None and PROFILE.fullmatch(name), "fresh_profile_name")
        sid = profile_sid(b, name)
        require(registry_absent(MAPPINGS + "\\" + sid), "existing_profile_mapping")
        b.profile = {"name": name, "sid": sid, "storage": None}
        identity = {"sid": sid, "mapping_absent": True}
    else:
        require(b.profile is not None, "profile_required")
        if kind == "credential":
            require(
                name == b.profile["name"] and credential_absent(b, name), "credential_collision"
            )
            identity = {"absent": True}
        elif kind == "registry":
            require(
                name in {"Software\\" + b.profile["name"], STORAGE + "\\" + b.profile["sid"]},
                "registry_scope",
            )
            identity = {"absent": registry_absent(name)}
        elif kind == "desktop":
            require(
                name == b.profile["name"] + ".Desktop" and desktop_absent(name), "desktop_collision"
            )
            identity = {"absent": True}
        elif kind == "acl":
            require(data["object"] in (1, 4) and data["information"] in (4, 16), "acl_scope")
            require(data["information"] == 4 or data["object"] == 1, "label_scope")
            if data["object"] == 1:
                handle = b.duplicate(b.transfer, data["handle"], 0x60000)
                try:
                    identity = file_binding(b, handle)
                    path = Path(identity["path"])
                    owned_profile = b.profile["storage"]
                    require(
                        path == Path(name)
                        and (
                            path.is_relative_to(b.root)
                            or owned_profile
                            and path.is_relative_to(owned_profile)
                        ),
                        "acl_path_scope",
                    )
                    original = descriptor(b, handle, 1, data["information"])
                    require(original == data["original"], "independent_descriptor_difference")
                except BaseException:
                    b.close(handle)
                    raise
                b.acls.append(
                    {
                        "handle": handle,
                        "object": 1,
                        "information": data["information"],
                        "original": original,
                        "identity": identity,
                    }
                )
            else:
                import winreg

                require(name == STORAGE + "\\" + b.profile["sid"], "registry_acl_scope")
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, name, 0, 0x60000)
                try:
                    original = descriptor(b, int(key), 4, 4)
                    require(
                        original == data["original"], "independent_registry_descriptor_difference"
                    )
                except BaseException:
                    key.Close()
                    raise
                identity = {"registry": name, "profile_sid": b.profile["sid"]}
                b.acls.append(
                    {
                        "handle": key.Detach(),
                        "object": 4,
                        "information": 4,
                        "original": original,
                        "identity": identity,
                    }
                )
            identity = {**identity, "object": data["object"], "information": data["information"]}
        else:
            raise ValueError("unknown_resource")
    if kind != "acl":
        require(
            data["handle"] == 0
            and data["object"] == 0
            and data["information"] == 0
            and data["original"] == "",
            "creation_frame_shape",
        )
    result = {
        "kind": kind,
        "name": name,
        "identity": identity,
        "original": original,
        "created": False,
    }
    b.pending_resource = result
    return result


def resource_commit(b, data):
    exact(data, ("ok", "created"))
    require(type(data["ok"]) is bool and type(data["created"]) is bool, "commit_types")
    pending = b.pending_resource
    require(pending is not None, "no_resource_intent")
    identity = dict(pending["identity"])
    if data["ok"]:
        kind, name = pending["kind"], pending["name"]
        if kind in {"profile", "credential", "desktop"}:
            require(data["created"] is True, "fresh_creation_receipt_required")
        if kind == "profile":
            pointer = HANDLE()
            require(
                b.u.GetAppContainerFolderPath(b.profile["sid"], C.byref(pointer)) == 0,
                "independent_profile_path",
            )
            try:
                folder = Path(C.wstring_at(pointer))
            finally:
                ole = C.WinDLL("ole32")
                bind(ole, "CoTaskMemFree", None, HANDLE)(pointer)
            storage = folder.parent
            require(
                storage.name == b.profile["sid"]
                and storage.is_dir()
                and not storage.is_symlink()
                and not storage.is_junction(),
                "profile_storage_binding",
            )
            b.profile["storage"] = storage
            handle, binding = open_exact(b, str(storage))
            b.close(handle)
            b.profile["identity"] = binding
            identity.update(folder=str(folder), storage=str(storage), file=binding)
        elif kind == "credential":
            require(not credential_absent(b, name), "credential_creation_unobserved")
        elif kind == "registry":
            require(not registry_absent(name), "registry_creation_unobserved")
            require(
                data["created"] == pending["identity"]["absent"], "registry_disposition_difference"
            )
        elif kind == "desktop":
            require(not desktop_absent(name), "desktop_creation_unobserved")
        elif kind == "acl":
            require(data["created"] is False, "acl_not_creation")
            entry = b.acls[-1]
            identity["after_descriptor"] = descriptor(
                b, entry["handle"], entry["object"], entry["information"]
            )
        b.owned.append({"resource": pending, "outcome": {**data, "identity": identity}})
    b.pending_resource = None
    return {**data, "identity": identity}


def recovery_plan(records, exercise):
    from ae5_verify import ledger_prefix

    checked = ledger_prefix(records, exercise)
    require(checked["complete"], "interrupted_resource_ledger_unresolved")
    # A plan is not permission. Revalidate objects immediately before each effect.
    return list(reversed(checked["operations"]))


def recover_exact(b, records, exercise):
    require(RECOVERY_RELEASE is True, "ae5_recovery_unreleased")
    exits, active = b.exits()
    require(
        active == 0 and all(v["wait"] == "signalled" for v in exits.values()),
        "recovery_before_quiescence",
    )
    plan = recovery_plan(records, exercise)
    require(len(plan) == len(b.owned), "retained_resource_inventory")
    require(
        all(
            op["intent"]["resource"] == live["resource"]
            and op["commit"]["outcome"] == live["outcome"]
            for op, live in zip(reversed(plan), b.owned, strict=True)
        ),
        "resource_ledger_binding",
    )
    restored = []
    for entry in plan:
        require(b.k.GetTickCount64() < b.started + 35000, "recovery_deadline")
        r = entry["intent"]["resource"]
        outcome = entry["commit"]["outcome"]
        name, kind = r["name"], r["kind"]
        if kind == "acl":
            object_type, information = r["identity"]["object"], r["identity"]["information"]
            key_identity = {
                k: v for k, v in r["identity"].items() if k not in {"object", "information"}
            }
            match = [
                a
                for a in b.acls
                if a["original"] == r["original"]
                and a["identity"] == key_identity
                and a["information"] == information
            ]
            require(match, "exact_acl_inventory")
            handle, reopened = match[-1]["handle"], False
            if not handle:
                require(object_type == 1, "lost_registry_object_identity")
                handle, _ = open_exact(b, name, key_identity)
                reopened = True
            try:
                if object_type == 1:
                    require(file_binding(b, handle) == key_identity, "retained_file_identity")
                current = descriptor(b, handle, object_type, information)
                require(
                    current in {r["original"], outcome["identity"]["after_descriptor"]},
                    "unexpected_resource_acl_state",
                )
                raw = C.create_string_buffer(bytes.fromhex(r["original"]))
                present, defaulted, acl = W.BOOL(), W.BOOL(), HANDLE()
                control, revision = W.WORD(), W.DWORD()
                query = (
                    b.a.GetSecurityDescriptorDacl
                    if information == 4
                    else b.a.GetSecurityDescriptorSacl
                )
                b.check(query(raw, C.byref(present), C.byref(acl), C.byref(defaulted)))
                b.check(b.a.GetSecurityDescriptorControl(raw, C.byref(control), C.byref(revision)))
                require(present.value, "missing_original_acl")
                flags = information
                if information == 4:
                    flags |= 0x80000000 if control.value & 0x1000 else 0x20000000
                require(
                    b.a.SetSecurityInfo(
                        handle,
                        object_type,
                        flags,
                        None,
                        None,
                        acl if information == 4 else None,
                        acl if information == 16 else None,
                    )
                    == 0,
                    "restore_exact_acl",
                )
                require(
                    descriptor(b, handle, object_type, information) == r["original"],
                    "acl_restore_readback",
                )
                restored.append(name)
            finally:
                if reopened:
                    b.close(handle)
        elif kind == "desktop":
            require(desktop_absent(name), "desktop_still_live")
        elif kind == "registry" and outcome["created"]:
            import winreg

            if not registry_absent(name):
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, name, 0, winreg.KEY_READ) as key:
                    subkeys, values, _ = winreg.QueryInfoKey(key)
                    require(subkeys == 0, "unexpected_registry_children")
                    if name == "Software\\" + b.profile["name"]:
                        require(
                            values == 1
                            and winreg.EnumValue(key, 0)
                            == (
                                "HostPrivateSentinel",
                                b"DAF synthetic credential; no real secret\0",
                                winreg.REG_BINARY,
                            ),
                            "unexpected_registry_value",
                        )
                    else:
                        require(values == 0, "nonempty_profile_storage_key")
                # Close only this known retained key, never someone else's handle.
                for item in b.acls:
                    if (
                        item["object"] == 4
                        and item["identity"]["registry"] == name
                        and item["handle"]
                    ):
                        winreg.CloseKey(item["handle"])
                        item["handle"] = None
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, name)
            require(registry_absent(name), "registry_delete_readback")
        elif kind == "credential" and outcome["created"]:
            bind(b.a, "CredDeleteW", W.BOOL, W.LPCWSTR, W.DWORD, W.DWORD)
            if not credential_absent(b, name):
                b.check(b.a.CredDeleteW(name, 1, 0))
            require(credential_absent(b, name), "credential_delete_readback")
        elif kind == "profile" and outcome["created"]:
            require(
                name == b.profile["name"] and profile_sid(b, name) == b.profile["sid"],
                "profile_recovery_identity",
            )
            if b.profile["storage"].exists():
                handle, _ = open_exact(b, str(b.profile["storage"]), b.profile["identity"])
                b.close(handle)
            b.release_recovery_handles()
            require(b.u.DeleteAppContainerProfile(name) == 0, "profile_delete_failed")
            require(
                not b.profile["storage"].exists()
                and registry_absent(MAPPINGS + "\\" + b.profile["sid"]),
                "profile_delete_readback",
            )
        require(b.k.GetTickCount64() < b.started + 35000, "recovery_completion_deadline")
    # Independent verifier must perform its own resource readback after this return.
    return {"requested_operations_completed": True, "restored": restored, "confirmed": False}
