"""Independent parent PSS readback before ACK; never resume or capture memory/context."""

import ctypes as C
from ctypes import wintypes as W

import ae5_windows as win
from ae5_contract import exact, integer, require

TEMPORARY_PROCESS_RIGHTS = (
    0x1450  # QUERY_INFORMATION/QUERY_LIMITED | VM_READ | DUP_HANDLE; pre-ACK only.
)


def validate_snapshot(value, offered):
    exact(
        value,
        (
            "capture_flags",
            "context_flags",
            "identity",
            "thread",
            "count_before",
            "count_after",
            "handles",
            "strict_flags",
            "temporary_handles_closed",
            "temporary_process_rights",
        ),
    )
    for key in ("capture_flags", "context_flags", "count_before", "count_after", "strict_flags"):
        integer(value[key])
    for item in value["thread"].values():
        integer(item)
    require(value["capture_flags"] == 132 and value["context_flags"] == 0, "witness_capture")
    require(
        value["identity"] == {"pid": offered["pid"], "creation": offered["creation"]},
        "witness_process",
    )
    require(
        value["thread"]
        == {
            "pid": offered["pid"],
            "tid": offered["tid"],
            "suspend": 1,
            "exit": 259,
            "context_bytes": 0,
        },
        "witness_suspended_thread",
    )
    require(
        value["count_before"] == value["count_after"] == len(value["handles"]) == 3,
        "witness_complete_count",
    )
    require(value["strict_flags"] == 3, "witness_strict_handles")
    require(value["temporary_process_rights"] == TEMPORARY_PROCESS_RIGHTS, "witness_process_rights")
    inventory = {}
    for row in value["handles"]:
        for item in row.values():
            integer(item)
        require(set(row) == {"value", "pipes", "hostile", "checked"}, "witness_row")
        require(
            row["checked"] == 255 and row["hostile"] == 0 and row["pipes"] in (1, 2, 4),
            "witness_object_identity",
        )
        require(
            row["value"] == offered["pipe_values"][(1, 2, 4).index(row["pipes"])], "witness_stream"
        )
        require(row["value"] not in inventory, "witness_duplicate")
        inventory[row["value"]] = row["pipes"]
    require(set(inventory.values()) == {1, 2, 4}, "witness_pipe_uniqueness")
    require(value["temporary_handles_closed"] is True, "witness_handles_retained")


def observe_suspended(b, offered):
    require(win.NATIVE_RELEASE is True, "ae51_observer_gate_closed")
    k, pointer, dword = b.k, win.HANDLE, W.DWORD
    for name, result, args in (
        ("PssCaptureSnapshot", dword, (pointer, dword, dword, C.POINTER(pointer))),
        ("PssQuerySnapshot", dword, (pointer, C.c_int, pointer, dword)),
        ("PssWalkMarkerCreate", dword, (pointer, C.POINTER(pointer))),
        ("PssWalkSnapshot", dword, (pointer, C.c_int, pointer, pointer, dword)),
        ("PssWalkMarkerFree", dword, (pointer,)),
        ("PssFreeSnapshot", dword, (pointer, pointer)),
        ("CompareObjectHandles", W.BOOL, (pointer, pointer)),
        ("GetProcessHandleCount", W.BOOL, (pointer, C.POINTER(dword))),
        ("GetProcessMitigationPolicy", W.BOOL, (pointer, C.c_int, pointer, win.SIZE)),
        ("GetFileType", dword, (pointer,)),
    ):
        win.bind(k, name, result, *args)
    owned, snap, markers = [], pointer(), []

    def copy(source, handle):
        result = pointer()
        b.check(
            k.DuplicateHandle(source, handle, k.GetCurrentProcess(), C.byref(result), 0, False, 2)
        )
        owned.append(result.value)
        require(b.noninheritable(result), "witness_inheritable")
        return result.value

    def count(process):
        result = dword()
        b.check(k.GetProcessHandleCount(process, C.byref(result)))
        require(result.value <= 16, "witness_count_bound")
        return result.value

    def same(left, right):
        C.set_last_error(0)
        yes = k.CompareObjectHandles(left, right)
        require(yes or C.get_last_error() == 1656, "witness_ambiguous_comparison")
        return bool(yes)

    result = None
    try:
        process = b.duplicate(b.transfer, offered["process"], TEMPORARY_PROCESS_RIGHTS)
        owned.append(process)
        references = [copy(b.transfer, h) for h in offered["references"]]
        require(same(references[4], b.helper), "witness_hostile_process")
        from ae5_resources import file_binding

        for index, leaf in enumerate(("smuggled-read.txt", "smuggled-write.txt")):
            require(
                file_binding(b, references[index])["path"] == str(b.root / leaf),
                "witness_hostile_file",
            )
        require(all(k.GetFileType(h) == 3 for h in references[5:]), "witness_pipe_type")
        before = count(process)
        require(
            k.PssCaptureSnapshot(process, 132, 0, C.byref(snap)) == 0 and snap,
            "witness_capture_failed",
        )
        hi, ti = dword(), (dword * 2)()
        require(
            k.PssQuerySnapshot(snap, 4, C.byref(hi), 4) == 0
            and k.PssQuerySnapshot(snap, 5, ti, 8) == 0
            and hi.value == before
            and ti[0] == 1
            and ti[1] == 0,
            "witness_capture_complete",
        )
        for _ in range(2):
            marker = pointer()
            require(k.PssWalkMarkerCreate(None, C.byref(marker)) == 0 and marker, "witness_marker")
            markers.append(marker)
        thread = C.create_string_buffer(120)
        require(k.PssWalkSnapshot(snap, 3, markers[1], thread, 120) == 0, "witness_thread")
        raw = thread.raw
        thread_data = {
            "pid": int.from_bytes(raw[16:20], "little"),
            "tid": int.from_bytes(raw[20:24], "little"),
            "suspend": int.from_bytes(raw[108:110], "little"),
            "exit": int.from_bytes(raw[:4], "little"),
            "context_bytes": int.from_bytes(raw[110:112], "little"),
        }
        require(k.PssWalkSnapshot(snap, 3, markers[1], thread, 120) == 259, "witness_thread_end")
        rows = []
        for index in range(17):
            entry = C.create_string_buffer(136)
            code = k.PssWalkSnapshot(snap, 2, markers[0], entry, 136)
            if code == 259:
                break
            require(code == 0 and index < 16, "witness_handle_walk")
            handle = int.from_bytes(entry.raw[:8], "little")
            require(0 < handle < 2**63, "witness_handle_value")
            duplicate = copy(process, handle)
            matches = [same(duplicate, ref) for ref in references]
            rows.append(
                {
                    "value": handle,
                    "checked": 255,
                    "hostile": sum(1 << i for i in range(5) if matches[i]),
                    "pipes": sum(1 << i for i in range(3) if matches[i + 5]),
                }
            )
        else:
            raise ValueError("witness_missing_end")
        flags = dword()
        b.check(k.GetProcessMitigationPolicy(process, 3, C.byref(flags), 4))
        result = {
            "capture_flags": 132,
            "context_flags": 0,
            "identity": b.identity(process),
            "thread": thread_data,
            "count_before": before,
            "count_after": count(process),
            "handles": rows,
            "strict_flags": flags.value,
            "temporary_handles_closed": False,
            "temporary_process_rights": b.verified_rights[process],
        }
    finally:
        errors = []
        for marker in markers:
            if k.PssWalkMarkerFree(marker) != 0:
                errors.append("marker")
        if snap and k.PssFreeSnapshot(k.GetCurrentProcess(), snap) != 0:
            errors.append("snapshot")
        for handle in reversed(owned):
            try:
                b.close(handle)
            except OSError:
                errors.append("handle")
        require(not errors, "witness_release_unconfirmed")
    result["temporary_handles_closed"] = True
    validate_snapshot(result, offered)
    return result
