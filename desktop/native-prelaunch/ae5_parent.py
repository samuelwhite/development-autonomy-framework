"""Diagnostic parent orchestration. Public native entry is unconditionally closed.

The supervisor only inspects memory and process handles. Blocking termination
calls have separate one-shot lanes; IPC, fsync and cleanup have no supervisor
locks. This provides independence from helper stalls, not a real-time OS claim.
"""

import os
import threading
from pathlib import Path

from ae5_contract import (
    ACK,
    HELPER_MS,
    MAGIC,
    MAX_CONTROL,
    MAX_FRAME,
    MAX_RECORDS,
    MAX_STDERR,
    OUTER_MS,
    Decision,
    Ledger,
    decode,
    handoff,
    require,
)

NATIVE_RELEASE = False


class SetupGuard:
    """Outer-Job watchdog already armed before the helper creation API is entered."""

    def __init__(self, backend, started, clock):
        self.backend, self.started, self.clock = backend, started, clock
        self.handed_over = threading.Event()
        self.stopped = False
        self.request = None
        self.result = {"returned": False, "ok": False, "error": None}

    def terminate(self):
        try:
            ok, error = self.backend.terminate("outer")
            self.result = {"returned": True, "ok": bool(ok), "error": error}
        except Exception as error:
            self.result = {"returned": True, "ok": False, "error": type(error).__name__}

    def step(self):
        now = self.clock()
        if now >= self.started + HELPER_MS and not self.stopped:
            self.stopped = True
            self.request = threading.Thread(target=self.terminate, daemon=True)
            self.request.start()
        return now < self.started + OUTER_MS

    def supervise(self):
        while not self.handed_over.is_set() and self.step():
            self.handed_over.wait(0.005)

    def transfer(self):
        require(
            not self.stopped and self.clock() < self.started + HELPER_MS, "expired_setup_custody"
        )
        self.handed_over.set()


def native_entry(package=None):
    # Source-only release; checked before imports, claims, preparation or IO.
    if NATIVE_RELEASE is not True:
        raise PermissionError("A-E5 native budget is unreleased; compile-only preflight")
    from ae51_tc0 import execute_tc0

    return execute_tc0(package)


def append_exclusive(root, sequence, raw):
    """Root must already be the private, independently checked fresh attempt."""
    require(type(root) is Path or isinstance(root, Path), "ledger_root")
    path = root / f"ledger-{sequence:03d}.json"
    with path.open("xb") as stream:
        require(stream.write(raw) == len(raw), "ledger_short_write")
        stream.flush()
        os.fsync(stream.fileno())
    return path.read_bytes()


class Custodian:
    """Backend is an explicit fake in portable tests, dormant Win32 adapter otherwise."""

    def __init__(self, backend, helper_identity, started, exercise, append, clock):
        self.backend, self.clock, self.exercise = backend, clock, exercise
        self.decision = Decision(started, helper_identity)
        self.ledger = Ledger(exercise, append)
        self.sequence = 0
        self.communication = True
        self.observed = None
        self.termination_calls = {}
        self.lanes = {}
        self.safety_done = threading.Event()
        self.protocol_lock = threading.Lock()  # Safety never acquires it.
        self.stderr = bytearray()
        self.stderr_complete = False
        self.stderr_overflow = False
        self.control_bytes = 0
        self.control_capture = bytearray()
        self.ack_capture = bytearray()
        self.control_overflow = False
        self.started_lanes = False
        self.safety_query_error = None
        self.control_complete = False
        self.cleanup_ack_written = False
        self.timeline = []

    def start(self):
        if self.started_lanes or self.decision.state != "HELD":
            self.stop("duplicate_supervision_start")
            raise ValueError("duplicate_supervision_start")
        self.started_lanes = True
        lanes = (
            threading.Thread(target=self.supervise, daemon=True),
            threading.Thread(
                target=self.read_frames,
                args=(self.backend.read_control, self.backend.write_control),
                daemon=True,
            ),
            threading.Thread(
                target=self.capture_stderr, args=(self.backend.read_stderr,), daemon=True
            ),
        )
        for lane in lanes:
            lane.start()
        return lanes

    def capture_stderr(self, read):
        try:
            while True:
                raw = read(4096)
                require(type(raw) is bytes and len(raw) <= 4096, "stderr_read_bound")
                if not raw:
                    self.stderr_complete = True
                    return
                remaining = MAX_STDERR - len(self.stderr)
                self.stderr.extend(raw[:remaining])
                if len(raw) > remaining:
                    self.stderr_overflow = True
                    self.stop("stderr_overflow")
                    return
        except Exception:
            self.stop("stderr_capture_failed")

    def stop(self, reason):
        self.decision.stop(reason, self.clock())

    def message(self, raw):
        """Single IPC worker, separate from safety. Every failure revokes permission."""
        try:
            with self.protocol_lock:
                require(self.decision.state != "STOP", "stop_is_irreversible")
                frame = decode(raw)
                require(
                    frame["exercise"] == self.exercise and frame["seq"] == self.sequence + 1,
                    "frame_binding_or_sequence",
                )
                require(
                    self.sequence < MAX_RECORDS
                    and self.clock() < self.decision.started + HELPER_MS,
                    "handoff_absolute_deadline",
                )
                data, kind = frame["data"], frame["kind"]
                if kind == "intent":
                    require(self.decision.state == "HELD", "resource_after_custody")
                    # Kernel corroboration precedes durable intent and acknowledgement.
                    resource = self.backend.resource_intent(data)
                    intent = self.ledger.intent(resource)
                    self.backend.pending_intent = intent
                elif kind == "commit":
                    require(self.decision.state == "HELD", "commit_after_custody")
                    outcome = self.backend.resource_commit(data)
                    self.ledger.commit(self.backend.pending_intent, outcome)
                    require(self.ledger.ready(), "failed_resource_operation")
                elif kind == "custody":
                    require(self.ledger.ready(), "incomplete_resource_ledger")
                    observed = self.backend.acquire(handoff(data))
                    self.decision.establish(observed, self.clock())
                    self.observed = observed
                    deadline = self.decision.arm(self.clock())
                    self.timeline.append({"event": "custody_verified", "ms": self.clock()})
                    self.sequence += 1
                    return self.ack(deadline)
                else:
                    # Cleanup permission is distinct from inspection success.
                    require(data == {"child_exit": True}, "cleanup_shape")
                    require(self.backend.child_exited(), "cleanup_before_child_exit")
                    require(self.decision.state == "INSPECTING", "cleanup_state")
                    self.decision.cleanup_phase(self.clock())
                    self.backend.release_recovery_handles()
                    self.timeline.append({"event": "cleanup_ack_ready", "ms": self.clock()})
                self.sequence += 1
                return self.ack(self.decision.started + HELPER_MS)
        except BaseException:
            self.stop("invalid_evidence_or_handoff")
            raise

    def ack(self, deadline):
        require(self.decision.state != "STOP" and self.clock() < deadline, "late_ack")
        return ACK.pack(
            MAGIC,
            self.sequence,
            deadline,
            self.backend.parent_pid,
            self.backend.parent_creation,
            self.exercise.encode("ascii"),
        )

    def lost_communication(self):
        self.communication = False
        self.stop("communication_lost")

    def _terminate(self, target):
        # Separate slots have one writer each; supervisor never joins a blocked lane.
        self.termination_calls[target] = {
            "target": target,
            "returned": False,
            "ok": False,
            "error": 0,
        }
        try:
            ok, error = self.backend.terminate(target)
            self.termination_calls[target] = {
                "target": target,
                "returned": True,
                "ok": bool(ok),
                "error": error,
            }
        except Exception:
            self.termination_calls[target] = {
                "target": target,
                "returned": True,
                "ok": False,
                "error": 1,
            }

    def safety_step(self):
        now = self.clock()
        try:
            alive = self.backend.helper_alive()
        except Exception as error:
            self.safety_query_error = "helper_wait:" + type(error).__name__
            alive = False
        self.decision.tick(now, alive, self.communication)
        if self.decision.state == "STOP":
            targets = ("child", "outer")
            if self.decision.reason == "helper_exit":
                try:
                    # A signalled retained process object cannot become live again.
                    # TerminateProcess on that object would return error 5. Keep
                    # outer-Job termination; never infer tree quiescence here.
                    if self.backend.child_exited() is True:
                        targets = ("outer",)
                except Exception as error:
                    self.safety_query_error = "child_wait:" + type(error).__name__
                    # Unknown exit still requests both termination lanes.
            for target in targets:
                if target not in self.lanes:
                    lane = threading.Thread(target=self._terminate, args=(target,), daemon=True)
                    self.lanes[target] = lane
                    lane.start()
        if now >= self.decision.started + OUTER_MS:
            self.safety_done.set()
        return self.decision.state

    def supervise(self):
        self.safety_step()
        if getattr(self.backend, "setup_guard", None) is not None:
            try:
                self.backend.setup_guard.transfer()
            except Exception:
                self.stop("setup_watchdog_expired")
        while not self.safety_done.is_set():
            self.safety_step()
            self.safety_done.wait(0.005)

    def read_frames(self, read, write):
        """Dedicated bounded IPC lane. No progress is required by supervise()."""
        try:
            initial = ACK.pack(
                MAGIC,
                0,
                self.decision.started + HELPER_MS,
                self.backend.parent_pid,
                self.backend.parent_creation,
                self.exercise.encode("ascii"),
            )
            self.write_ack(write, initial)
            for _ in range(MAX_RECORDS):
                header = read(4)
                require(type(header) is bytes and len(header) <= 4, "control_header_bound")
                if header == b"" and self.cleanup_ack_written:
                    # Child is already signalled. EOF is not proof of helper exit;
                    # the independent 30/35-second watchdog remains armed.
                    self.control_complete = True
                    return
                self.control_capture.extend(header[: MAX_CONTROL - len(self.control_capture)])
                require(len(header) == 4, "control_eof")
                length = int.from_bytes(header, "little")
                require(0 < length <= MAX_FRAME, "control_frame_size")
                self.control_bytes += 4 + length
                self.control_overflow = self.control_bytes > MAX_CONTROL
                require(self.control_bytes <= MAX_CONTROL, "aggregate_control_output_bound")
                payload = read(length)
                require(type(payload) is bytes and len(payload) <= length, "control_payload_bound")
                self.control_capture.extend(payload)
                require(len(payload) == length, "control_short_read")
                reply = self.message(payload)
                # Check again after all potentially blocking work; helper also checks.
                require(self.decision.state != "STOP", "revoked_before_ack_write")
                self.write_ack(write, reply)
            raise ValueError("control_frame_count")
        except Exception:
            self.lost_communication()

    def write_ack(self, write, raw):
        require(
            len(self.ack_capture) + len(raw) <= (MAX_RECORDS + 1) * ACK.size, "ack_capture_bound"
        )
        cleanup_ack = self.decision.state == "DRAINING"
        count = write(raw)
        require(type(count) is int and 0 <= count <= len(raw), "ack_write_count")
        self.ack_capture.extend(raw[:count])
        require(count == len(raw), "ack_short_write")
        if cleanup_ack:
            self.cleanup_ack_written = True
        self.timeline.append(
            {"event": "ack_written", "ms": self.clock(), "sequence": ACK.unpack(raw)[1]}
        )


if __name__ == "__main__":
    native_entry()
