"""Standalone Windows acceptance. Never imported by DAF or packaged in the desktop.

Only validated closed results are persisted. Raw worker stdout/stderr remain in
bounded memory; no logging, exception interpolation or raw diagnostic bundles.
"""

import ctypes as C
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes as W
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import contracts as c  # noqa: E402
from cleanup import cleanup  # noqa: E402
from evidence import Evidence, StreamHash, observed  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def git_bytes(revision, path):
    return subprocess.check_output(["git", "show", revision + ":" + path], cwd=REPO)


class Capture:
    def __init__(self, pipe, limit):
        self.data = bytearray()
        self.overflow = False
        self.hash = StreamHash()
        self.thread = threading.Thread(target=self.read, args=(pipe, limit), daemon=True)
        self.thread.start()

    def read(self, pipe, limit):
        try:
            while chunk := os.read(pipe.fileno(), 4096):
                self.hash.update(chunk)
                if len(self.data) + len(chunk) > limit:
                    self.overflow = True
                else:
                    self.data.extend(chunk)
        finally:
            pipe.close()


def observations(raw):
    c.require(len(raw) <= 32768, "host_output_limit")
    result = []
    for line in raw.splitlines():
        r = c.load(line, 2048)
        c.require(type(r) is dict and type(r.get("native")) is str, "host_frame")
        c.require(
            set(r)
            in (
                {"native", "value"},
                {"native", "sid", "attributes"},
                {"native", "allowed", "requested", "granted"},
                {"native", "allowed", "error", "bytes_written"},
                {"native", "sha256", "bytes", "complete"},
            ),
            "host_fields",
        )
        result.append(r)
    return result


def value(rows, name, field="value"):
    matches = [r[field] for r in rows if r.get("native") == name and field in r]
    c.require(len(matches) == 1, "missing_or_duplicate_host_observation")
    return matches[0]


def process_handle(pid):
    k = C.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    handle = k.OpenProcess(0x100000, False, pid)
    c.require(bool(handle), "process_handle")
    return handle


def terminated(handle):
    k = C.WinDLL("kernel32")
    k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k.CloseHandle.argtypes = [W.HANDLE]
    try:
        c.require(k.WaitForSingleObject(handle, 3000) == 0, "termination_failed")
    finally:
        k.CloseHandle(handle)


class Run:
    def __init__(
        self, root, name, role, payload=b"", mode="sealed", *, evidence=None, forward=False
    ):
        self.evidence = evidence
        self.record = evidence.begin(name, role) if evidence else {"case": name, "role": role}
        self.attempt = root / "attempts" / name
        self.attempt.mkdir(parents=True, exist_ok=False)
        self.started = time.monotonic()
        self.mode, self.role, self.name = mode, role, name
        manifest = c.load((root / "build-manifest.json").read_bytes())
        for binary in ("harness", "producer", "verifier", "probe"):
            leaf = binary + ".exe"
            data = (root / leaf).read_bytes()
            c.require(c.sha(data) == manifest["files"][leaf]["sha256"], "binary_identity")
            (self.attempt / leaf).write_bytes(data)
        (self.attempt / "runtime").mkdir()
        for leaf, data in {
            "allowed.txt": b"Explicitly readable synthetic fixture",
            "private.txt": b"Host-private synthetic fixture",
            "ambient-shared.txt": b"Synthetic resource shared with all LPACs",
            "dual-grant.txt": b"Explicit dual-grant synthetic fixture",
            "protected.bin": b"",
            "fixture-root.marker": b"DAF M2.1A owned acceptance fixture",
            "request.bin": payload,
        }.items():
            (self.attempt / leaf).write_bytes(data)
        self.ambient = c.sha((self.attempt / "ambient-shared.txt").read_bytes())
        self.process = subprocess.Popen(
            [str(self.attempt / "harness.exe"), mode, role],
            stdin=subprocess.DEVNULL,
            stdout=sys.stdout.buffer if forward else subprocess.PIPE,
            stderr=sys.stderr.buffer if forward else subprocess.PIPE,
            creationflags=0x08000000,
        )
        self.out = None if forward else Capture(self.process.stdout, c.MAX_OUTPUT)
        self.err = None if forward else Capture(self.process.stderr, 32768)

    def ready(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            data = bytes(self.err.data)
            complete = data[: data.rfind(b"\n") + 1]
            rows = observations(complete)
            if any(r.get("native") == "hold_ready" for r in rows):
                return value(rows, "child_pid")
            c.require(self.process.poll() is None, "holder_failed_before_ready")
            time.sleep(0.02)
        raise c.Refused("holder_not_ready")

    def finish(self, *, killed=False):
        deadline_failed = False
        try:
            self.process.wait(timeout=max(0.01, 35 - (time.monotonic() - self.started)))
        except subprocess.TimeoutExpired:
            deadline_failed = True
            self.process.kill()
            self.process.wait(timeout=3)
        finally:
            self.out.thread.join(timeout=3)
            self.err.thread.join(timeout=3)
            record = self.record
            record.update(
                {
                    "helper_exit": self.process.returncode,
                    "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                    "stdout": self.out.hash.result(not self.out.thread.is_alive()),
                    "host_stderr": self.err.hash.result(not self.err.thread.is_alive()),
                    "stdout_overflow": self.out.overflow,
                    "stderr_overflow": self.err.overflow,
                    "parent_deadline_expired": deadline_failed,
                }
            )
            rows = []
            try:
                rows = observations(bytes(self.err.data))
            except c.Refused:
                record["host_records"] = "invalid_or_incomplete"
            observed(record, rows)
            try:
                if (self.attempt / "owned-profile.txt").exists():
                    cleanup(self.attempt)
                    record["cleanup"] = "confirmed"
                else:
                    record["cleanup"] = "no_profile_marker_unconfirmed"
            except (AssertionError, OSError, RuntimeError):
                record["cleanup"] = "failed"
            if self.evidence:
                self.evidence.persist()
        c.require(not deadline_failed, "parent_deadline")
        c.require(record["cleanup"] == "confirmed", "cleanup_unconfirmed")
        c.require(
            not self.out.thread.is_alive() and not self.err.thread.is_alive(), "pipe_not_closed"
        )
        c.require(not self.out.overflow and not self.err.overflow, "host_output_overflow")
        c.require(not any(r["native"] == "host_failure" for r in rows), "native_host_failure")
        c.require(
            c.sha((self.attempt / "ambient-shared.txt").read_bytes()) == self.ambient,
            "ambient_write",
        )
        for name, expected in {
            "host_elevated": 0,
            "host_appcontainer": 0,
            "appcontainer": 1,
            "final_elevated": 0,
            "CreateRestrictedToken_flags": 9,
            "job_at_creation": 1,
            "image_identity_checked": 1,
            "job_limit_flags": 8458,
            "job_process_limit": 1,
            "job_memory_bytes": 134217728,
            "job_cpu_100ns": 20000000,
            "capability_count": 1,
            "child_resumed": 1,
        }.items():
            c.require(value(rows, name) == expected, "token_or_job")
        c.require(value(rows, "native_ambient_write", "allowed") is False, "ambient_write")
        c.require(value(rows, "native_ambient_write", "error") == 5, "ambient_denial")
        c.require(value(rows, "native_explicit_dual_write", "allowed") is True, "positive_control")
        restriction = value(rows, "requested_attempt_sid", "sid")
        c.require(
            value(rows, "final_child_restricted_sids", "sid") == restriction, "restriction_identity"
        )
        record.update(
            {
                "final_token_checked": True,
                "image_checked": True,
                "ambient_write_denied": True,
                "positive_write_observed": True,
            }
        )
        if not killed:
            c.require(value(rows, "active_after_wait") == 0, "process_survived")
            c.require(value(rows, "retained_process_handle_signalled") == 1, "process_unconfirmed")
        if self.evidence:
            self.evidence.persist()
        return record, bytes(self.out.data)


def probe_result(raw, mode, record=None):
    c.require(len(raw) <= 16384, "probe_limit")
    rows = [c.load(line, 512) for line in raw.splitlines()]
    expected = {
        "native_entry": ("status", "observed"),
        "pid": ("value", None),
        "permitted_write_error": ("value", 0),
        "ambient_write_error": ("value", 5),
        "ambient_read_error": ("value", 0),
        "permitted_read_error": ("value", 0),
        "native_basic_complete": ("status", "observed"),
    }
    if mode == "sealed":
        permitted = (
            "load_advapi32 load_userenv load_crypt32 load_ws2_32 read_allowed_fixture "
            "read_profile_sentinel registry_machine_read"
        )
        denied = (
            "read_host_private_fixture write_workspace write_runtime write_profile_root "
            "write_profile_package_root write_profile_temp write_effective_temp "
            "append_profile_file replace_profile_dacl append_after_dacl_attempt "
            "replace_profile_root_dacl replace_temp_dacl "
            "write_after_directory_dacl_attempt write_host_profile write_windows_temp "
            "read_host_private_registry_fixture registry_user_write registry_profile_write "
            "registry_profile_write_dacl write_profile_after_reinitialize "
            "write_temp_after_reinitialize registry_write_after_reinitialize "
            "host_dpapi_decrypt"
        )
        for name in permitted.split():
            expected[name] = ("code", 0)
        for name in denied.split():
            expected[name] = ("code", 5)
        for name in "loopback_tcp loopback_udp external_tcp_testnet external_udp_testnet".split():
            expected[name] = ("code", 10013)
        expected.update(
            {
                "reinitialize_own_profile": ("code", 87),
                "host_credential_read": ("code", 1702),
                "dns_resolution": ("code", 11003),
                "child_process": ("code", 367),
                "breakaway_child": ("code", 5),
                "native_suite_complete": ("code", 0),
            }
        )
    elif mode == "memory":
        expected.update({"memory_positive_control": ("code", 0), "memory_limit": ("code", 1455)})
    elif mode == "cpu":
        expected["cpu_ready"] = ("code", 0)
    elif mode in ("hold", "cancel"):
        expected["hold_ready"] = ("code", 0)
    seen = {}
    if record is not None:
        record["probe_observations"] = {}
        record["missing_probe_observations"] = sorted(expected)
    for row in rows:
        c.require(type(row) is dict and row.get("probe") in expected, "unexpected_probe_output")
        name = row["probe"]
        field, wanted = expected[name]
        keys = {"probe", field} | ({"status"} if field == "code" else set())
        c.require(set(row) == keys and name not in seen, "probe_fields")
        if field == "code":
            c.require(
                type(row[field]) is int
                and row["status"] in ("allowed", "denied", "error", "observed"),
                "probe_value",
            )
        if record is not None and name != "pid":
            actual = row[field]
            c.require(
                (type(actual) is int and 0 <= actual < 2**32) or actual == "observed",
                "probe_scalar",
            )
            record["probe_observations"][name] = actual
        if name == "pid":
            c.require(type(row[field]) is int and 0 < row[field] < 2**32, "probe_pid")
        else:
            c.require(row[field] == wanted, "mandatory_probe_failed")
        if record is not None:
            record["missing_probe_observations"].remove(name)
        seen[name] = wanted
    c.require(set(seen) == set(expected), "missing_probe")
    # Only expected constant outcomes, never arbitrary worker-selected diagnostic text.
    return {name: outcome for name, outcome in seen.items() if name != "pid"}


def preparation(root):
    source = git_bytes(c.BASELINE, c.TARGET)
    plan = git_bytes(c.PLAN_COMMIT, c.PLAN_PATH)
    policy = c.load((Path(__file__).parent / "policy.json").read_bytes())
    spec = c.load((Path(__file__).parent / "replacement.json").read_bytes())
    inventory = c.load(plan)["plan"]["validation"]["protected_files"]
    value = {
        "schema": "daf-preparation/v1",
        "attempt": uuid.uuid4().hex,
        "source": {
            "repository": c.REPOSITORY,
            "plan_commit": c.PLAN_COMMIT,
            "plan_path": c.PLAN_PATH,
            "plan_sha256": c.PLAN_DIGEST,
            "baseline": c.BASELINE,
            "path": c.TARGET,
            "blob": c.SOURCE_BLOB,
        },
        "local_spec": spec,
        "producer": c.build_identity(root / "producer.exe", "producer"),
        "verifier": c.build_identity(root / "verifier.exe", "verifier"),
        "policy": policy,
        "inventory": inventory,
    }
    protected = {p: git_bytes(c.BASELINE, p) for p in inventory}
    prepared = c.prepare(value, source, plan, protected)
    return prepared, source


def matrix(root, evidence):
    records = evidence.records
    prepared, source = preparation(root)
    producer = c.request(prepared, source, 1)
    record, raw = Run(root, "producer", "producer", producer, evidence=evidence).finish()
    record["response"], candidate = c.response(raw, 1, prepared.digest)
    c.require(record["child_exit"] == 0 and candidate is not None, "producer_failed")
    evidence.passed(record)
    verifier = c.request(prepared, source, 2, candidate)
    record, raw = Run(root, "verifier", "verifier", verifier, evidence=evidence).finish()
    record["response"], _ = c.response(raw, 2, prepared.digest, candidate)
    c.require(record["child_exit"] == 0 and record["response"]["status"] == "ok", "verifier_failed")
    c.require(
        record["attempt_identity_sha256"] != records[0]["attempt_identity_sha256"]
        and record["package_identity_sha256"] != records[0]["package_identity_sha256"],
        "shared_identity",
    )
    evidence.passed(record)
    record, raw = Run(root, "isolation", "probe", evidence=evidence).finish()
    record["probes"] = probe_result(raw, "sealed", record)
    c.require(record["child_exit"] == 0, "isolation_failed")
    evidence.passed(record)
    print(
        "Production bytes and independent verifier passed; isolation controls passed.", flush=True
    )
    for role, original in ((1, producer), (2, verifier)):
        label = "producer" if role == 1 else "verifier"
        fields = list(c.REQUEST.unpack(original[: c.REQUEST.size]))

        def frame(index, value, payload=original[c.REQUEST.size :], fields=fields):
            changed = fields.copy()
            changed[index] = value
            return c.REQUEST.pack(*changed) + payload

        old = c.block(c.load(prepared.encoded)["local_spec"]["oldBlockBase64"])
        duplicate = source + old
        cases = {
            "version": (frame(1, 2), "frame"),
            "role": (frame(2, 3), "frame"),
            "oversize": (frame(3, 65537), "limit"),
            "truncated": (original[:-1], "frame"),
            "extra": (original + b"x", "frame"),
            "plan": (frame(8, bytes(20)), "binding"),
            "policy": (frame(15, bytes(32)), "binding"),
            "preimage": (frame(11, bytes(32)), "binding"),
            "expected": (frame(14, bytes(32)), "binding"),
            "utf8": (original[: c.REQUEST.size] + b"\xff" + original[c.REQUEST.size + 1 :], "text"),
            "nul": (original[: c.REQUEST.size] + b"\0" + original[c.REQUEST.size + 1 :], "text"),
            "missing": (
                original[: c.REQUEST.size]
                + source.replace(old, b"x" * len(old))
                + original[c.REQUEST.size + len(source) :],
                "occurrence",
            ),
            "duplicate": (
                frame(3, len(duplicate), duplicate + original[c.REQUEST.size + len(source) :]),
                "occurrence",
            ),
            "source": (
                original[: c.REQUEST.size] + b"X" + original[c.REQUEST.size + 1 :],
                "preimage",
            ),
        }
        if role == 2:
            cases["tampered"] = (original[:-1] + b"X", "candidate")
            cases["missing_candidate"] = (
                frame(6, len(candidate) - 1, original[c.REQUEST.size : -1]),
                "candidate",
            )
            cases["extra_candidate"] = (
                frame(6, len(candidate) + 1, original[c.REQUEST.size :] + b"X"),
                "candidate",
            )
        for name, (payload, expected) in cases.items():
            record, raw = Run(root, label + "-" + name, label, payload, evidence=evidence).finish()
            record["response"], _ = c.response(
                raw, role, prepared.digest, candidate if role == 2 else None
            )
            c.require(record["response"]["status"] == expected, "adversarial_input_not_rejected")
            c.require(record["child_exit"] == c.FAILURES.index(expected), "failure_exit")
            evidence.passed(record)
    for name, mode in (
        ("memory", "memory"),
        ("cpu", "cpu"),
        ("wall", "hold"),
        ("cancel", "cancel"),
    ):
        record, raw = Run(root, name, "probe", mode=mode, evidence=evidence).finish()
        record["probes"] = probe_result(raw, mode, record)
        if mode == "memory":
            c.require(record["child_exit"] == 0, "memory_failed")
        elif mode == "cpu":
            c.require(
                record["child_exit"] == 0xC0000044 or record["termination_reason"] == 1,
                "cpu_termination",
            )
        else:
            c.require(
                record["termination_reason"] == (4 if mode == "cancel" else 1), "deadline_or_cancel"
            )
        if mode == "cancel":
            cancellation(record)
        evidence.passed(record)
    for name in ("leak", "overflow", "crash"):
        record, raw = Run(root, name, "probe", mode=name, evidence=evidence).finish()
        try:
            c.response(raw, 1, prepared.digest)
        except c.Refused:
            record["unexpected_output"] = "rejected_without_persistence"
        else:
            raise c.Refused("unexpected_output_accepted")
        if name == "overflow":
            c.require(record["worker_output_rejected"] == 1, "overflow_not_rejected")
        if name == "crash":
            c.require(record["child_exit"] == 99, "crash_control")
        evidence.passed(record)
    # Five distinct attempts per lifecycle control, each persisted, no success-only sampling.
    for index in range(5):
        if index:
            record, raw = Run(
                root, f"cancel-repeat-{index}", "probe", mode="cancel", evidence=evidence
            ).finish()
            record["probes"] = probe_result(raw, "cancel", record)
            cancellation(record)
            evidence.passed(record)
        lifecycle(root, evidence, index, parent_death=False)
        lifecycle(root, evidence, index, parent_death=True)


def cancellation(record):
    c.require(
        record.get("hold_ready") == 1 and record.get("readiness_ms", 10000) < 10000,
        "cancellation_readiness",
    )
    c.require(
        record.get("termination_reason") == 4
        and record.get("terminate_job_called") == 4
        and record.get("terminate_job_succeeded") == 1,
        "cancellation_api",
    )
    c.require(
        record.get("retained_process_handle_signalled") == 1
        and record.get("active_after_wait") == 0
        and record.get("child_exit") == 125,
        "cancellation_process_survived",
    )
    c.require(
        record.get("wall_elapsed_ms", 10000) < 10000
        and record.get("termination_latency_ms", 3001) <= 3000,
        "cancellation_deadline",
    )


def lifecycle(root, evidence, index, *, parent_death):
    name = ("parent-death-" if parent_death else "helper-death-") + str(index)
    if parent_death:
        # Root owns the capture pipes. Killing the intermediate supervisor cannot
        # discard helper/worker observations or replace them with a success claim.
        record = evidence.begin(name, "probe")
        started = time.monotonic()
        parent = subprocess.Popen(
            [sys.executable, "-I", str(Path(__file__).resolve()), str(root), "parent", str(index)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=0x08000000,
        )
        holder = Run.__new__(Run)
        holder.attempt = root / "attempts" / name
        holder.evidence, holder.record = evidence, record
        holder.started, holder.process = started, parent
        holder.out, holder.err = Capture(parent.stdout, c.MAX_OUTPUT), Capture(parent.stderr, 32768)
        holder.ambient = c.sha(b"Synthetic resource shared with all LPACs")
    else:
        holder = Run(root, name, "probe", mode="hold", evidence=evidence)
        record = holder.record
    handles = []
    try:
        child = process_handle(holder.ready())
        handles.append(child)
        complete = bytes(holder.err.data).rsplit(b"\n", 1)[0]
        helper = process_handle(value(observations(complete), "helper_pid"))
        handles.append(helper)
        started = time.monotonic()
        holder.process.kill()
        terminated(handles.pop(0))
        record["retained_child_handle_signalled"] = True
        terminated(handles.pop(0))
        record["retained_helper_handle_signalled"] = True
        record["death_latency_ms"] = round((time.monotonic() - started) * 1000)
    finally:
        for handle in handles:
            close_handle(handle)
        if holder.process.poll() is None:
            holder.process.kill()
        record, raw = holder.finish(killed=not parent_death)
    if parent_death:
        record["supervising_parent_exit"] = record.pop("helper_exit")
        c.require(
            record.get("termination_reason") == 2
            and record.get("terminate_job_called") == 2
            and record.get("terminate_job_succeeded") == 1,
            "parent_death_termination",
        )
        record["probes"] = probe_result(raw, "hold", record)
    else:
        # Deliberately killed helper cannot emit final accounting; retained handles
        # prove death. Missing native final metrics remain explicitly missing.
        c.require(
            record.get("retained_child_handle_signalled") is True
            and record.get("retained_helper_handle_signalled") is True,
            "helper_death",
        )
    evidence.passed(record)


def close_handle(handle):
    k = C.WinDLL("kernel32")
    k.CloseHandle.argtypes = [W.HANDLE]
    k.CloseHandle(handle)


def main():
    c.require(os.name == "nt" and len(sys.argv) in (2, 4), "windows_maintainer_only")
    root = Path(sys.argv[1]).resolve()
    c.require(root.is_relative_to(REPO / "dist"), "owned_output_required")
    if len(sys.argv) == 4:
        c.require(sys.argv[2] == "parent" and sys.argv[3] in tuple(map(str, range(5))), "arguments")
        holder = Run(root, "parent-death-" + sys.argv[3], "probe", mode="hold", forward=True)
        holder.process.wait(timeout=20)
        return holder.process.returncode
    c.require(not (root / "attempts").exists(), "fresh_output_required")
    evidence = Evidence(root)
    try:
        matrix(root, evidence)
        c.require(all(r["status"] == "passed" for r in evidence.records), "incomplete_cases")
        evidence.document["qualified"] = True
    except c.Refused as refusal:
        evidence.failed(str(refusal))
        raise
    except (AssertionError, KeyError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        evidence.failed("host_or_cleanup_failure")
        raise
    finally:
        evidence.persist()
    print(
        json.dumps(
            {"cases": len(evidence.records), "qualified": True, "execution_authority": False}
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except c.Refused as refusal:
        # Refused is constructed only from fixed codes in trusted host source.
        print("STOP: " + str(refusal) + "; no further acceptance cases.", flush=True)
        raise SystemExit(2) from None
    except (AssertionError, KeyError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        print("STOP: mandatory native acceptance failed; no further cases.", flush=True)
        raise SystemExit(2) from None
