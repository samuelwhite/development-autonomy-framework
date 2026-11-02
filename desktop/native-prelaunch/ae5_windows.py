"""Dormant diagnostic Win32 adapter. Never imported by the closed public entry.

No PID reopening, arbitrary process discovery, resume, privilege adjustment or
breakaway. Native process creation has its own source gate, also closed.
"""

import ctypes as C
import os
import threading
from ctypes import wintypes as W
from pathlib import Path

from ae5_contract import INNER, OUTER, require

NATIVE_RELEASE = False
HANDLE = C.c_void_p
SIZE = C.c_size_t
Q = C.c_ulonglong
PROCESS_OBSERVE = 0x101000
PROCESS_CUSTODY = 0x101001
PROCESS_HANDOFF = 0x101041
THREAD_OBSERVE = 0x100800
JOB_QUERY = 4
JOB_CUSTODY = 12
INVALID = C.c_void_p(-1).value


class BasicLimits(C.Structure):
    _fields_ = [
        ("process_time", C.c_longlong),
        ("job_time", C.c_longlong),
        ("flags", W.DWORD),
        ("minimum", SIZE),
        ("maximum", SIZE),
        ("processes", W.DWORD),
        ("affinity", SIZE),
        ("priority", W.DWORD),
        ("scheduling", W.DWORD),
    ]


class IO(C.Structure):
    _fields_ = [
        (name, Q) for name in ("read_ops", "write_ops", "other_ops", "read", "write", "other")
    ]


class Limits(C.Structure):
    _fields_ = [
        ("basic", BasicLimits),
        ("io", IO),
        ("memory", SIZE),
        ("job_memory", SIZE),
        ("peak_process", SIZE),
        ("peak_job", SIZE),
    ]


class Accounting(C.Structure):
    _fields_ = [
        ("user", C.c_longlong),
        ("kernel", C.c_longlong),
        ("period_user", C.c_longlong),
        ("period_kernel", C.c_longlong),
        ("faults", W.DWORD),
        ("total", W.DWORD),
        ("active", W.DWORD),
        ("terminated", W.DWORD),
    ]


class Security(C.Structure):
    _fields_ = [("size", W.DWORD), ("descriptor", HANDLE), ("inherit", W.BOOL)]


class Startup(C.Structure):
    _fields_ = [
        ("cb", W.DWORD),
        ("reserved", W.LPWSTR),
        ("desktop", W.LPWSTR),
        ("title", W.LPWSTR),
        ("x", W.DWORD),
        ("y", W.DWORD),
        ("sx", W.DWORD),
        ("sy", W.DWORD),
        ("cx", W.DWORD),
        ("cy", W.DWORD),
        ("fill", W.DWORD),
        ("flags", W.DWORD),
        ("show", W.WORD),
        ("reserved_size", W.WORD),
        ("reserved_bytes", HANDLE),
        ("stdin", HANDLE),
        ("stdout", HANDLE),
        ("stderr", HANDLE),
    ]


class StartupEx(C.Structure):
    _fields_ = [("startup", Startup), ("attributes", HANDLE)]


class ProcessInfo(C.Structure):
    _fields_ = [("process", HANDLE), ("thread", HANDLE), ("pid", W.DWORD), ("tid", W.DWORD)]


class FileInfo(C.Structure):
    _fields_ = [
        ("attributes", W.DWORD),
        ("created", W.FILETIME),
        ("accessed", W.FILETIME),
        ("written", W.FILETIME),
        ("volume", W.DWORD),
        ("size_high", W.DWORD),
        ("size_low", W.DWORD),
        ("links", W.DWORD),
        ("id_high", W.DWORD),
        ("id_low", W.DWORD),
    ]


def bind(dll, name, result, *args):
    method = getattr(dll, name)
    method.restype, method.argtypes = result, list(args)
    return method


class WindowsCustody:
    def __init__(self, root):
        require(os.name == "nt" and C.sizeof(HANDLE) == 8, "windows_x64_only")
        self.root = Path(root).resolve(strict=True)
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.a = C.WinDLL("advapi32", use_last_error=True)
        self.u = C.WinDLL("userenv", use_last_error=True)
        self.nt = C.WinDLL("ntdll")
        self.parent_pid = os.getpid()
        self.outer = self.helper = self.child = None
        self.transfer = None
        self.thread = None
        self.owned, self.acls = [], []
        self.inherited_helper_handles = ()
        self.profile = None
        self.pending_resource = self.pending_intent = None
        self.verified_rights = {}
        self.image_pins = []
        self._bindings()
        self.parent_creation = self.identity(self.k.GetCurrentProcess())["creation"]

    def _bindings(self):
        k, a, u = self.k, self.a, self.u
        bind(
            self.nt, "NtQueryObject", C.c_long, HANDLE, C.c_int, HANDLE, W.DWORD, C.POINTER(W.DWORD)
        )
        signatures = (
            ("GetCurrentProcess", HANDLE, ()),
            ("GetTickCount64", Q, ()),
            ("CloseHandle", W.BOOL, (HANDLE,)),
            ("GetProcessId", W.DWORD, (HANDLE,)),
            ("GetProcessIdOfThread", W.DWORD, (HANDLE,)),
            ("GetThreadId", W.DWORD, (HANDLE,)),
            ("GetProcessTimes", W.BOOL, (HANDLE, *([C.POINTER(W.FILETIME)] * 4))),
            ("GetHandleInformation", W.BOOL, (HANDLE, C.POINTER(W.DWORD))),
            ("SetHandleInformation", W.BOOL, (HANDLE, W.DWORD, W.DWORD)),
            ("WaitForSingleObject", W.DWORD, (HANDLE, W.DWORD)),
            ("GetExitCodeProcess", W.BOOL, (HANDLE, C.POINTER(W.DWORD))),
            (
                "DuplicateHandle",
                W.BOOL,
                (HANDLE, HANDLE, HANDLE, C.POINTER(HANDLE), W.DWORD, W.BOOL, W.DWORD),
            ),
            ("CreateJobObjectW", HANDLE, (HANDLE, W.LPCWSTR)),
            ("SetInformationJobObject", W.BOOL, (HANDLE, C.c_int, HANDLE, W.DWORD)),
            ("QueryInformationJobObject", W.BOOL, (HANDLE, C.c_int, HANDLE, W.DWORD, HANDLE)),
            ("IsProcessInJob", W.BOOL, (HANDLE, HANDLE, C.POINTER(W.BOOL))),
            ("TerminateJobObject", W.BOOL, (HANDLE, W.UINT)),
            ("TerminateProcess", W.BOOL, (HANDLE, W.UINT)),
            (
                "CreatePipe",
                W.BOOL,
                (C.POINTER(HANDLE), C.POINTER(HANDLE), C.POINTER(Security), W.DWORD),
            ),
            (
                "InitializeProcThreadAttributeList",
                W.BOOL,
                (HANDLE, W.DWORD, W.DWORD, C.POINTER(SIZE)),
            ),
            (
                "UpdateProcThreadAttribute",
                W.BOOL,
                (HANDLE, W.DWORD, SIZE, HANDLE, SIZE, HANDLE, HANDLE),
            ),
            ("DeleteProcThreadAttributeList", None, (HANDLE,)),
            (
                "CreateProcessW",
                W.BOOL,
                (
                    W.LPCWSTR,
                    W.LPWSTR,
                    HANDLE,
                    HANDLE,
                    W.BOOL,
                    W.DWORD,
                    HANDLE,
                    W.LPCWSTR,
                    C.POINTER(StartupEx),
                    C.POINTER(ProcessInfo),
                ),
            ),
            ("QueryFullProcessImageNameW", W.BOOL, (HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD))),
            ("ReadFile", W.BOOL, (HANDLE, HANDLE, W.DWORD, C.POINTER(W.DWORD), HANDLE)),
            ("WriteFile", W.BOOL, (HANDLE, HANDLE, W.DWORD, C.POINTER(W.DWORD), HANDLE)),
            ("GetFileInformationByHandle", W.BOOL, (HANDLE, C.POINTER(FileInfo))),
            ("GetFinalPathNameByHandleW", W.DWORD, (HANDLE, W.LPWSTR, W.DWORD, W.DWORD)),
            (
                "CreateFileW",
                HANDLE,
                (W.LPCWSTR, W.DWORD, W.DWORD, HANDLE, W.DWORD, W.DWORD, HANDLE),
            ),
            ("LocalFree", HANDLE, (HANDLE,)),
        )
        for name, result, args in signatures:
            bind(k, name, result, *args)
        bind(
            a,
            "GetSecurityInfo",
            W.DWORD,
            HANDLE,
            C.c_int,
            W.DWORD,
            HANDLE,
            HANDLE,
            C.POINTER(HANDLE),
            HANDLE,
            C.POINTER(HANDLE),
        )
        bind(a, "GetSecurityDescriptorLength", W.DWORD, HANDLE)
        bind(a, "IsValidSecurityDescriptor", W.BOOL, HANDLE)
        bind(
            a, "GetSecurityDescriptorControl", W.BOOL, HANDLE, C.POINTER(W.WORD), C.POINTER(W.DWORD)
        )
        bind(
            a,
            "GetSecurityDescriptorDacl",
            W.BOOL,
            HANDLE,
            C.POINTER(W.BOOL),
            C.POINTER(HANDLE),
            C.POINTER(W.BOOL),
        )
        bind(
            a,
            "GetSecurityDescriptorSacl",
            W.BOOL,
            HANDLE,
            C.POINTER(W.BOOL),
            C.POINTER(HANDLE),
            C.POINTER(W.BOOL),
        )
        bind(
            a, "SetSecurityInfo", W.DWORD, HANDLE, C.c_int, W.DWORD, HANDLE, HANDLE, HANDLE, HANDLE
        )
        bind(u, "DeriveAppContainerSidFromAppContainerName", C.c_long, W.LPCWSTR, C.POINTER(HANDLE))
        bind(u, "GetAppContainerFolderPath", C.c_long, W.LPCWSTR, C.POINTER(HANDLE))
        bind(u, "DeleteAppContainerProfile", C.c_long, W.LPCWSTR)
        bind(a, "ConvertSidToStringSidW", W.BOOL, HANDLE, C.POINTER(HANDLE))
        bind(a, "FreeSid", HANDLE, HANDLE)

    def check(self, ok):
        if not ok:
            raise OSError(C.get_last_error(), "A-E5 Win32 operation failed")

    def close(self, handle):
        if handle:
            self.check(self.k.CloseHandle(handle))

    def identity(self, handle):
        times = [W.FILETIME() for _ in range(4)]
        self.check(self.k.GetProcessTimes(handle, *(C.byref(t) for t in times)))
        pid = self.k.GetProcessId(handle)
        self.check(pid)
        return {"pid": pid, "creation": times[0].dwLowDateTime | times[0].dwHighDateTime << 32}

    def noninheritable(self, handle):
        flags = W.DWORD()
        self.check(self.k.GetHandleInformation(handle, C.byref(flags)))
        return flags.value & 1 == 0

    def duplicate(self, source, value, rights):
        result = HANDLE()
        self.check(
            self.k.DuplicateHandle(
                source, value, self.k.GetCurrentProcess(), C.byref(result), rights, False, 0
            )
        )
        try:
            require(self.noninheritable(result), "inheritable_custody_handle")
            # PUBLIC_OBJECT_BASIC_INFORMATION, same bounded basic query used by A7.
            basic, returned = C.create_string_buffer(56), W.DWORD()
            require(
                self.nt.NtQueryObject(result, 0, basic, 56, C.byref(returned)) == 0
                and returned.value == 56,
                "granted_rights_unavailable",
            )
            granted = int.from_bytes(basic.raw[4:8], "little")
            require(granted == rights, "unexpected_granted_rights")
            self.verified_rights[result.value] = granted
            return result.value
        except BaseException:
            self.close(result)
            raise

    def limits(self, job):
        value = Limits()
        self.check(self.k.QueryInformationJobObject(job, 9, C.byref(value), C.sizeof(value), None))
        require(
            value.basic.job_time == 0
            and value.job_memory == 0
            and value.basic.minimum == 0
            and value.basic.maximum == 0
            and value.basic.priority == 0
            and value.basic.scheduling == 0,
            "unexpected_additional_job_limits",
        )
        return {
            "flags": value.basic.flags,
            "processes": value.basic.processes,
            "memory": value.memory,
            "cpu": value.basic.process_time,
        }

    def member(self, process_handle, job):
        found = W.BOOL()
        self.check(self.k.IsProcessInJob(process_handle, job, C.byref(found)))
        return bool(found.value)

    def create_helper(self, executable):
        # Second independent closed gate, before Job/pipe/process creation.
        require(NATIVE_RELEASE is True, "ae5_native_creation_unreleased")
        require(len(self.image_pins) == 4, "four_binary_pins_required")
        require(not self.member(self.k.GetCurrentProcess(), None), "unreviewed_ancestor_job")
        executable = Path(executable).resolve(strict=True)
        require(
            executable.parent == self.root and executable.name == "ae5-fixture-host.exe",
            "fixed_owned_helper_only",
        )
        job = self.k.CreateJobObjectW(None, None)
        self.check(job)
        self.outer = job
        limits = Limits()
        limits.basic.flags, limits.basic.processes = OUTER["flags"], OUTER["processes"]
        self.check(self.k.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)))
        require(self.limits(job) == OUTER and self.noninheritable(job), "outer_policy")
        # Stable supervision handle; setup's assignment handle never replaces it.
        self.outer = self.duplicate(self.k.GetCurrentProcess(), job, JOB_CUSTODY)
        from ae5_parent import SetupGuard

        self.started = self.k.GetTickCount64()
        self.setup_guard = SetupGuard(self, self.started, self.k.GetTickCount64)
        threading.Thread(target=self.setup_guard.supervise, daemon=True).start()
        pairs = []
        attributes = None
        attributes_ready = False
        try:
            sa = Security(C.sizeof(Security), None, True)
            for _ in range(3):
                read, write = HANDLE(), HANDLE()
                self.check(self.k.CreatePipe(C.byref(read), C.byref(write), C.byref(sa), 0))
                pairs.append((read.value, write.value))
            parent_ends = (pairs[0][1], pairs[1][0], pairs[2][0])
            helper_ends = (pairs[0][0], pairs[1][1], pairs[2][1])
            self.inherited_helper_handles = helper_ends
            for handle in parent_ends:
                self.check(self.k.SetHandleInformation(handle, 1, 0))
            size = SIZE()
            self.k.InitializeProcThreadAttributeList(None, 2, 0, C.byref(size))
            require(0 < size.value <= 65536, "attribute_bound")
            attributes = C.create_string_buffer(size.value)
            self.check(self.k.InitializeProcThreadAttributeList(attributes, 2, 0, C.byref(size)))
            attributes_ready = True
            jobs, handles = (HANDLE * 1)(job), (HANDLE * 3)(*helper_ends)
            for key, values in ((0x2000D, jobs), (0x20002, handles)):
                self.check(
                    self.k.UpdateProcThreadAttribute(
                        attributes, 0, key, values, C.sizeof(values), None, None
                    )
                )
            startup = StartupEx()
            startup.startup.cb = C.sizeof(startup)
            startup.startup.flags = 0x100
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = helper_ends
            startup.attributes = C.cast(attributes, HANDLE)
            info = ProcessInfo()
            command = C.create_unicode_buffer(f'"{executable}"')
            self.check(
                self.k.CreateProcessW(
                    str(executable),
                    command,
                    None,
                    None,
                    True,
                    0x08080000,
                    None,
                    str(self.root),
                    C.byref(startup),
                    C.byref(info),
                )
            )
            self.helper = self.duplicate(self.k.GetCurrentProcess(), info.process, PROCESS_CUSTODY)
            self.transfer = self.duplicate(self.k.GetCurrentProcess(), info.process, 0x40)
            self.close(info.process)
            self.close(info.thread)
            require(self.member(self.helper, job), "helper_not_in_outer")
            for handle in helper_ends:
                self.close(handle)
            self.control_write, self.control_read, self.stderr_read = parent_ends
            self.close(job)
            job = None
            require(not self.setup_guard.stopped, "setup_watchdog_stopped")
            return self.identity(self.helper), self.started
        except BaseException:
            # Preserve ownership if termination is uncertain. No blind handle reuse.
            threading.Thread(target=self.terminate, args=("outer",), daemon=True).start()
            raise
        finally:
            if attributes_ready:
                self.k.DeleteProcThreadAttributeList(attributes)
            if job:
                self.close(job)

    def acquire(self, offered):
        from ae51_snapshot import observe_suspended

        require(
            self.child is None
            and offered["helper_creation"] == self.identity(self.helper)["creation"],
            "duplicate_custody_or_wrong_helper",
        )
        inner = None
        try:
            self.child = self.duplicate(self.transfer, offered["process"], PROCESS_CUSTODY)
            self.thread = self.duplicate(self.transfer, offered["thread"], THREAD_OBSERVE)
            inner = self.duplicate(self.transfer, offered["job"], JOB_QUERY)
            child = self.identity(self.child)
            require(
                child == {"pid": offered["pid"], "creation": offered["creation"]}
                and self.k.GetThreadId(self.thread) == offered["tid"]
                and self.k.WaitForSingleObject(self.child, 0) == 258,
                "child_creation_binding",
            )
            image, length = C.create_unicode_buffer(32768), W.DWORD(32768)
            self.check(self.k.QueryFullProcessImageNameW(self.child, 0, image, C.byref(length)))
            require(Path(image.value).resolve() == self.root / "probe.exe", "child_image_path")
            observed = {
                "helper": self.identity(self.helper),
                "child": child,
                "inner": self.limits(inner),
                "outer": self.limits(self.outer),
                "members": {
                    "helper_outer": self.member(self.helper, self.outer),
                    "child_outer": self.member(self.child, self.outer),
                    "child_inner": self.member(self.child, inner),
                    "helper_inner": self.member(self.helper, inner),
                },
                "thread_pid": self.k.GetProcessIdOfThread(self.thread),
                "inner_query_closed": False,
                "noninheritable": all(
                    self.noninheritable(h) for h in (self.child, self.thread, inner, self.outer)
                ),
                # Ownership by closed construction, not a system-wide
                # census. Parent-death controls must qualify this claim.
                "outer_owner_only": self.noninheritable(self.outer)
                and self.outer not in self.inherited_helper_handles,
                "rights": {
                    name: self.verified_rights[handle]
                    for name, handle in (
                        ("helper", self.helper),
                        ("child", self.child),
                        ("thread", self.thread),
                        ("inner", inner),
                        ("outer", self.outer),
                    )
                },
                "helper_transfer_closed": False,
            }
            require(observed["inner"] == INNER and observed["outer"] == OUTER, "effective_limits")
            # Temporary read/duplicate authority exists only before the custody ACK.
            # It never enters the safety lane and never changes the child's state.
            self.independent_snapshot = observe_suspended(self, offered)
            from ae51_contract import digest

            with (self.root / "protected.bin").open("rb") as protected:
                ciphertext = protected.read(4097)
            require(0 < len(ciphertext) <= 4096, "synthetic_ciphertext_bound")
            self.protected_fixture_sha256 = digest(ciphertext)
            self.close(inner)
            inner = None
            observed["inner_query_closed"] = True
            self.close(self.transfer)
            self.transfer = None
            observed["helper_transfer_closed"] = True
            return observed
        finally:
            if inner is not None:
                self.close(inner)

    def helper_alive(self):
        result = self.k.WaitForSingleObject(self.helper, 0)
        require(result in (0, 258), "helper_wait_failed")
        return result == 258

    def pin_images(self, expected):
        require(NATIVE_RELEASE is True, "ae51_image_pin_gate_closed")
        require(
            not self.image_pins
            and set(expected)
            == {"ae5-fixture-host.exe", "probe.exe", "producer.exe", "verifier.exe"},
            "fixed_binary_inventory",
        )
        from ae51_contract import digest

        for name, wanted in expected.items():
            handle = self.k.CreateFileW(
                str(self.root / name), 0x80020000, 1, None, 3, 0x00200000, None
            )
            require(handle and handle != INVALID, "binary_pin_failed")
            self.image_pins.append(handle)
            from ae5_resources import file_binding

            require(file_binding(self, handle)["path"] == str(self.root / name), "binary_pin_path")
            data = bytearray()
            while len(data) <= wanted["bytes"]:
                buffer, count = C.create_string_buffer(65536), W.DWORD()
                self.check(self.k.ReadFile(handle, buffer, len(buffer), C.byref(count), None))
                if not count.value:
                    break
                data.extend(buffer.raw[: count.value])
            require(
                {"bytes": len(data), "sha256": digest(data)} == wanted, "pinned_binary_identity"
            )

    def close_custody(self):
        # Caller first joins all normal diagnostic lanes. Never close/reuse a
        # handle while an unresolved termination or observation call owns it.
        for name in (
            "control_write",
            "control_read",
            "stderr_read",
            "thread",
            "child",
            "helper",
            "transfer",
            "outer",
        ):
            handle = getattr(self, name, None)
            if handle:
                self.close(handle)
                setattr(self, name, None)
        for handle in self.image_pins:
            self.close(handle)
        self.image_pins.clear()

    def child_exited(self):
        return self.child is not None and self.k.WaitForSingleObject(self.child, 0) == 0

    def terminate(self, target):
        require(target in {"child", "outer"}, "termination_target")
        if target == "child":
            if self.child is None:
                return False, 6
            ok = self.k.TerminateProcess(self.child, 123)
        else:
            ok = self.k.TerminateJobObject(self.outer, 123)
        return bool(ok), 0 if ok else C.get_last_error()

    def exits(self):
        result = {}
        for name, handle in (("helper", self.helper), ("child", self.child)):
            require(handle is not None, "missing_retained_process")
            wait = self.k.WaitForSingleObject(handle, 0)
            code = W.DWORD()
            ok = wait == 0 and self.k.GetExitCodeProcess(handle, C.byref(code))
            result[name] = {
                "identity": self.identity(handle),
                "wait": "signalled" if ok else "unknown",
                "exit": code.value if ok else None,
            }
        account = Accounting()
        self.check(
            self.k.QueryInformationJobObject(
                self.outer, 1, C.byref(account), C.sizeof(account), None
            )
        )
        self.last_total_processes = account.total
        return result, account.active

    def read_control(self, length):
        require(0 < length <= 32768, "read_bound")
        result = bytearray()
        while len(result) < length:
            data, count = C.create_string_buffer(length - len(result)), W.DWORD()
            ok = self.k.ReadFile(self.control_read, data, len(data), C.byref(count), None)
            if not ok and C.get_last_error() == 109:
                return bytes(result)  # Preserve a truncated frame after helper death.
            self.check(ok)
            if not count.value:
                break
            result.extend(data.raw[: count.value])
        return bytes(result)

    def write_control(self, raw):
        require(len(raw) == 64, "ack_size")
        data, count = C.create_string_buffer(raw), W.DWORD()
        self.check(self.k.WriteFile(self.control_write, data, len(raw), C.byref(count), None))
        return count.value

    def read_stderr(self, length):
        require(0 < length <= 4096, "stderr_read_bound")
        data, count = C.create_string_buffer(length), W.DWORD()
        ok = self.k.ReadFile(self.stderr_read, data, length, C.byref(count), None)
        if not ok and C.get_last_error() == 109:  # Broken pipe is EOF, not process-exit proof.
            return b""
        self.check(ok)
        return data.raw[: count.value]

    def release_recovery_handles(self):
        for item in self.acls:
            if item["handle"]:
                if item["object"] == 4:
                    import winreg

                    winreg.CloseKey(item["handle"])
                else:
                    self.close(item["handle"])
                item["handle"] = None

    # Resource methods live separately so their potentially blocking operations
    # cannot accidentally enter the safety loop.
    def resource_intent(self, data):
        from ae5_resources import resource_intent

        return resource_intent(self, data)

    def resource_commit(self, data):
        from ae5_resources import resource_commit

        return resource_commit(self, data)
