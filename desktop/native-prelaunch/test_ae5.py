"""Controlled fakes only. No native claims, WinDLL construction or executable launch."""

import copy
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import ae5_contract as c
import ae5_parent as p
import ae5_verify as v
import ae5_windows as w
import instrument_ae5 as g
from ae5_resources import recovery_plan

EXERCISE = "1" * 32
HELPER = {"pid": 10, "creation": 100}
CHILD = {"pid": 20, "creation": 200}
OFFER = {
    "process": 12,
    "thread": 16,
    "job": 24,
    "pid": 20,
    "tid": 21,
    "creation": 200,
    "helper_creation": 100,
    "references": list(range(1000, 1008)),
    "pipe_values": [2000, 2001, 2002],
}
RESOURCE = {
    "kind": "profile",
    "name": "synthetic-owned-profile",
    "identity": {"absent": True},
    "original": "",
    "created": False,
}


def observations():
    return {
        "helper": dict(HELPER),
        "child": dict(CHILD),
        "inner": dict(c.INNER),
        "outer": dict(c.OUTER),
        "members": {
            "helper_outer": True,
            "child_outer": True,
            "child_inner": True,
            "helper_inner": False,
        },
        "thread_pid": 20,
        "inner_query_closed": True,
        "noninheritable": True,
        "outer_owner_only": True,
        "rights": dict(c.RIGHTS),
        "helper_transfer_closed": True,
    }


class Fake:
    parent_pid, parent_creation = 5, 50

    def __init__(self):
        self.now, self.alive, self.exited = 1000, True, True
        self.calls, self.observed = [], observations()
        self.block = None
        self.error = False
        self.released = False

    def acquire(self, data):
        if data != OFFER:
            raise ValueError("fake_retained_object_mismatch")
        return copy.deepcopy(self.observed)

    def resource_intent(self, _data):
        if self.block:
            self.block[0].set()
            self.block[1].wait(2)
        return copy.deepcopy(RESOURCE)

    def resource_commit(self, _data):
        return {"ok": True, "created": True, "identity": {"owned": True}}

    def helper_alive(self):
        return self.alive

    def child_exited(self):
        return self.exited

    def release_recovery_handles(self):
        self.released = True

    def terminate(self, target):
        self.calls.append(target)
        if self.error:
            raise OSError("synthetic termination failure")
        return True, 0


def parent(append=None):
    backend = Fake()
    runner = p.Custodian(
        backend, HELPER, 1000, EXERCISE, append or (lambda _seq, raw: raw), lambda: backend.now
    )
    return runner, backend


def message(runner, kind, data, **changes):
    value = {"v": 1, "exercise": EXERCISE, "seq": runner.sequence + 1, "kind": kind, "data": data}
    return c.canonical({**value, **changes})


def prepare(runner):
    runner.message(message(runner, "intent", {}))
    runner.message(message(runner, "commit", {}))


def evidence():
    r, _ = parent()
    prepare(r)
    return {
        "schema": "daf-ae5-observation/v1",
        "case": "TC-0",
        "mode": "simulated",
        "exercise": EXERCISE,
        "source": "a" * 64,
        "build": "b" * 64,
        "helper": {"identity": HELPER, "wait": "signalled", "exit": 0, "forced": False},
        "child": {"identity": CHILD, "wait": "signalled", "exit": 123, "forced": False},
        "termination": {"requested": True, "confirmed": True, "elapsed_ms": 100, "api_results": []},
        "tree": {
            "confirmed": True,
            "active": 0,
            "method": "outer_query",
            "parent_death_witness": None,
        },
        "cleanup": {"confirmed": True, "remaining": [], "identity_verified": True},
        "elapsed_ms": 200,
        "resumes": 0,
        "ledger": r.ledger.records,
        "execution_authority": False,
        "qualified": False,
    }


class CustodyTests(unittest.TestCase):
    def test_stderr_drains_independently_and_preserves_overflow_prefix(self):
        r, _ = parent()
        chunks = iter([b"x" * 4096] * 9)
        r.capture_stderr(lambda _n: next(chunks))
        self.assertEqual(bytes(r.stderr), b"x" * c.MAX_STDERR)
        self.assertTrue(r.stderr_overflow)
        self.assertFalse(r.stderr_complete)
        self.assertEqual(r.decision.reason, "stderr_overflow")
        r, _ = parent()
        chunks = iter([b"original partial evidence", b""])
        r.capture_stderr(lambda _n: next(chunks))
        self.assertEqual(bytes(r.stderr), b"original partial evidence")
        self.assertTrue(r.stderr_complete)
        self.assertFalse(r.stderr_overflow)

    def test_control_aggregate_bound_precedes_payload_allocation(self):
        r, _ = parent()
        r.control_bytes = c.MAX_CONTROL - 3
        reads = []

        def read(length):
            reads.append(length)
            return (100).to_bytes(4, "little")

        r.read_frames(read, len)
        self.assertEqual(reads, [4])
        self.assertEqual(r.decision.state, "STOP")
        self.assertEqual(bytes(r.control_capture), (100).to_bytes(4, "little"))
        self.assertTrue(r.control_overflow)

    def test_truncated_frame_and_ack_preserve_original_bytes(self):
        r, _ = parent()
        chunks = iter([(20).to_bytes(4, "little"), b"truncated"])
        r.read_frames(lambda _n: next(chunks), len)
        self.assertEqual(bytes(r.control_capture), (20).to_bytes(4, "little") + b"truncated")
        self.assertEqual(len(r.ack_capture), 64)
        self.assertEqual(r.decision.state, "STOP")
        r, _ = parent()
        with self.assertRaises(ValueError):
            r.write_ack(lambda _raw: 2, b"original")
        self.assertEqual(bytes(r.ack_capture), b"or")

    def test_setup_supervision_does_not_reset_on_handoff(self):
        backend = Fake()
        guard = p.SetupGuard(backend, 1000, lambda: backend.now)
        self.assertTrue(guard.step())
        backend.now = 31000
        self.assertTrue(guard.step())
        guard.request.join(1)
        self.assertEqual(backend.calls, ["outer"])
        with self.assertRaises(ValueError):
            guard.transfer()
        backend.now = 36000
        self.assertFalse(guard.step())
        self.assertEqual(backend.calls, ["outer"])

    def test_public_and_backend_gates_fail_before_effects(self):
        # Portable negative control only closes source gates; never enables one.
        with patch.object(p, "NATIVE_RELEASE", False), patch.object(w, "NATIVE_RELEASE", False):
            with self.assertRaises(PermissionError):
                p.native_entry("missing")
            with self.assertRaisesRegex(ValueError, "unreleased"):
                w.WindowsCustody.create_helper(object(), "missing")
        self.assertTrue(p.NATIVE_RELEASE)
        self.assertTrue(w.NATIVE_RELEASE)

    def test_positive_custody_ack_binding_and_no_resume_state(self):
        r, b = parent()
        prepare(r)
        packet = r.message(message(r, "custody", OFFER))
        self.assertEqual(c.ACK.unpack(packet), (c.MAGIC, 3, 6000, 5, 50, EXERCISE.encode()))
        self.assertEqual(r.decision.state, "INSPECTING")
        r.message(message(r, "cleanup", {"child_exit": True}))
        self.assertEqual(r.decision.state, "DRAINING")
        self.assertTrue(b.released)
        r.decision.inspection_result(True, b.now)
        self.assertEqual(r.decision.state, "STOP")

    def test_each_identity_and_job_predicate_refuses(self):
        mutations = [
            ("helper", {"pid": 10, "creation": 101}),
            ("child", {"pid": 10, "creation": 200}),
            ("thread_pid", 99),
            ("inner_query_closed", False),
            ("noninheritable", False),
            ("outer_owner_only", False),
            ("helper_transfer_closed", False),
            ("rights", {**c.RIGHTS, "child": 0x1FFFFF}),
            ("inner", {**c.INNER, "flags": c.INNER["flags"] | 0x800}),
            ("inner", {**c.INNER, "processes": 2}),
            ("outer", {**c.OUTER, "processes": 3}),
            ("members", {**observations()["members"], "child_outer": False}),
            ("members", {**observations()["members"], "helper_inner": True}),
            ("inner", {**c.INNER, "processes": True}),
        ]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                r, b = parent()
                prepare(r)
                b.observed[key] = value
                with self.assertRaises(ValueError):
                    r.message(message(r, "custody", OFFER))
                self.assertEqual(r.decision.state, "STOP")

    def test_remote_slot_alias_and_creation_confusion(self):
        for key in OFFER:
            r, _ = parent()
            prepare(r)
            value = OFFER[key]
            wrong = {
                **OFFER,
                key: [value[0] + 1, *value[1:]] if isinstance(value, list) else value + 1,
            }
            with self.assertRaises(ValueError):
                r.message(message(r, "custody", wrong))
            self.assertEqual(r.decision.state, "STOP")
        with self.assertRaises(ValueError):
            c.handoff({**OFFER, "thread": OFFER["process"]})

    def test_malformed_frames_and_replay_stop(self):
        for raw in (
            b"",
            b"x" * (c.MAX_FRAME + 1),
            b'{"v":1,"v":1}',
            b"\xff",
            c.canonical({"v": 1}),
            message(parent()[0], "custody", OFFER, exercise="2" * 32),
            message(parent()[0], "custody", OFFER, seq=True),
            message(parent()[0], "custody", OFFER, seq=2),
        ):
            r, _ = parent()
            with self.assertRaises((ValueError, UnicodeError)):
                r.message(raw)
            self.assertEqual(r.decision.state, "STOP")

    def test_delayed_ack_and_handoff_time_use_original_budget(self):
        r, b = parent()
        prepare(r)
        b.now = 23000
        with self.assertRaises(ValueError):
            r.message(message(r, "custody", OFFER))
        self.assertEqual(r.decision.state, "STOP")
        r, b = parent()
        prepare(r)
        r.message(message(r, "custody", OFFER))
        b.now = 6000
        with self.assertRaises(ValueError):
            r.ack(6000)
        r.safety_step()
        self.assertEqual(r.decision.reason, "inspection_deadline")

    def test_duplicate_transitions_cannot_rearm(self):
        r, _ = parent()
        prepare(r)
        r.message(message(r, "custody", OFFER))
        with self.assertRaises(ValueError):
            r.message(message(r, "custody", OFFER))
        reason = r.decision.reason
        r.decision.inspection_result(True, 1100)
        self.assertEqual(r.decision.reason, reason)
        self.assertEqual(r.decision.state, "STOP")

    def test_helper_death_and_communication_loss_terminate_once(self):
        for failure in ("helper", "communication"):
            r, b = parent()
            if failure == "helper":
                b.alive = False
                b.exited = False  # Helper death while the owned child is still live.
            else:
                r.lost_communication()
            for _ in range(3):
                r.safety_step()
            for lane in r.lanes.values():
                lane.join(1)
            self.assertCountEqual(b.calls, ["child", "outer"])
            self.assertEqual(r.decision.state, "STOP")

    def test_parent_death_last_handle_model_and_leaked_handle_negative(self):
        # Synthetic observations only; test the actual independent schema.
        value = evidence()
        value["case"] = "TC-6"
        value["tree"].update(
            method="complete_retained_membership",
            parent_death_witness={
                "parent": {"pid": 5, "creation": 50},
                "parent_wait": "signalled",
                "members": [HELPER, CHILD],
                "outer_handles": 0,
                "inner_handles": 0,
            },
        )
        self.assertEqual(v.verify(value)["status"], "complete_observations")
        for key, wrong in (
            ("outer_handles", 1),
            ("inner_handles", 1),
            ("parent_wait", "unknown"),
            ("members", [HELPER]),
        ):
            altered = copy.deepcopy(value)
            altered["tree"]["parent_death_witness"][key] = wrong
            with self.assertRaises(ValueError):
                v.verify(altered)
        source = Path(w.__file__).read_text()
        self.assertIn("0x2000D", source)
        self.assertNotIn("AssignProcessToJobObject", source)
        self.assertNotIn("ResumeThread", source)

    def test_blocking_ipc_and_persistence_do_not_hold_safety_lock(self):
        for blocked in ("ipc", "persistence"):
            entered, release = threading.Event(), threading.Event()

            def append(_seq, raw, entered=entered, release=release):
                entered.set()
                release.wait(2)
                return raw

            r, b = parent(append if blocked == "persistence" else None)
            if blocked == "ipc":
                b.block = entered, release
            errors = []

            def work(r=r, errors=errors):
                try:
                    r.message(message(r, "intent", {}))
                except ValueError as error:
                    errors.append(str(error))

            worker = threading.Thread(target=work)
            worker.start()
            self.assertTrue(entered.wait(1))
            b.now = 31000
            r.safety_step()
            self.assertEqual(r.decision.state, "STOP")
            release.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertTrue(errors)

    def test_blocked_child_termination_cannot_block_outer_lane_or_deadline(self):
        r, b = parent()
        entered, release, outer = threading.Event(), threading.Event(), threading.Event()

        def terminate(target):
            if target == "child":
                entered.set()
                release.wait(2)
            else:
                outer.set()
            return True, 0

        b.terminate = terminate  # Controlled fake; never a native adapter.
        r.stop("synthetic_abort")
        r.safety_step()
        self.assertTrue(entered.wait(1))
        self.assertTrue(outer.wait(1))
        b.now = 36000
        r.safety_step()
        self.assertTrue(r.safety_done.is_set())
        self.assertFalse(r.termination_calls["child"]["returned"])
        release.set()
        for lane in r.lanes.values():
            lane.join(1)

    def test_termination_failure_never_becomes_confirmation(self):
        r, b = parent()
        b.error = True
        r.stop("failure")
        r.safety_step()
        for lane in r.lanes.values():
            lane.join(1)
        self.assertTrue(all(not item["ok"] for item in r.termination_calls.values()))
        value = evidence()
        value["termination"]["confirmed"] = False
        value["cleanup"]["confirmed"] = False
        self.assertEqual(v.verify(value)["status"], "UNRESOLVED")

    def test_cleanup_before_exit_or_after_revocation_refused(self):
        for expired in (False, True):
            r, b = parent()
            prepare(r)
            r.message(message(r, "custody", OFFER))
            b.exited = expired
            if expired:
                b.now = 6000
            with self.assertRaises(ValueError):
                r.message(message(r, "cleanup", {"child_exit": True}))
            self.assertFalse(b.released)
            self.assertEqual(r.decision.state, "STOP")


class LedgerTests(unittest.TestCase):
    def test_durable_intent_and_commit_with_exact_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = c.Ledger(EXERCISE, lambda seq, raw: p.append_exclusive(root, seq, raw))
            intent = ledger.intent(RESOURCE)
            self.assertFalse(ledger.ready())
            self.assertFalse(v.ledger_prefix(ledger.records, EXERCISE)["complete"])
            ledger.commit(intent, {"ok": True, "created": True, "identity": {"owned": True}})
            self.assertTrue(ledger.ready())
            self.assertEqual(len(recovery_plan(ledger.records, EXERCISE)), 1)
            with self.assertRaises(FileExistsError):
                p.append_exclusive(root, 1, b"overwrite")

    def test_interrupted_intent_or_commit_is_not_recoverable_success(self):
        for fail_at in (1, 2):
            persisted = []

            def append(seq, raw, persisted=persisted, fail_at=fail_at):
                persisted.append(raw)
                if seq == fail_at:
                    raise OSError("synthetic fsync interruption")
                return raw

            ledger = c.Ledger(EXERCISE, append)
            with self.assertRaises(OSError):
                intent = ledger.intent(RESOURCE)
                ledger.commit(intent, {"ok": True, "created": True, "identity": {}})
            self.assertFalse(ledger.ready())
            self.assertTrue(ledger.broken)
            with self.assertRaises(ValueError):
                recovery_plan(ledger.records, EXERCISE)

    def test_bad_chain_or_failed_commit_cannot_be_promoted(self):
        r, _ = parent()
        prepare(r)
        rows = copy.deepcopy(r.ledger.records)
        rows[-1]["previous"] = "a" * 64
        with self.assertRaises(ValueError):
            v.ledger_prefix(rows, EXERCISE)
        rows = copy.deepcopy(r.ledger.records)
        rows[-1]["outcome"]["ok"] = False
        self.assertFalse(v.ledger_prefix(rows, EXERCISE)["complete"])
        with self.assertRaises(ValueError):
            recovery_plan(rows, EXERCISE)

    def test_unknown_exit_cleanup_and_live_readback_fail_closed(self):
        value = evidence()
        self.assertEqual(v.verify(value)["status"], "complete_observations")
        value["mode"] = "native"
        with self.assertRaisesRegex(ValueError, "live_readback"):
            v.verify(value)
        value = evidence()
        value["child"].update(wait="unknown", exit=None)
        with self.assertRaises(ValueError):
            v.verify(value)
        value["termination"]["confirmed"] = False
        value["tree"].update(confirmed=False, active=None, method="unknown")
        value["cleanup"]["confirmed"] = False
        self.assertEqual(v.verify(value)["status"], "UNRESOLVED")

    def test_request_is_not_confirmation_and_deadlines_are_not_reset(self):
        for mutate in (
            lambda x: x["termination"].update(elapsed_ms=3001),
            lambda x: x["cleanup"].update(remaining=["owned-profile"]),
            lambda x: x["tree"].update(active=1),
            lambda x: x.update(resumes=1),
            lambda x: x.update(qualified=True),
        ):
            value = evidence()
            mutate(value)
            with self.assertRaises(ValueError):
                v.verify(value)
        value = evidence()
        value["elapsed_ms"] = 35000
        self.assertEqual(v.verify(value)["status"], "UNRESOLVED")


class SourceTests(unittest.TestCase):
    def test_complete_generated_inverses_and_tamper_refusal(self):
        source = Path(g.__file__).parent
        for path, edits, digest in (
            (source.parent / "native-foundation/harness.cpp", g.changes(), g.ACCEPTED),
            (source / "a8-fixture-host.cpp", g.launcher_changes(), g.LAUNCHER_SHA),
        ):
            raw = path.read_bytes()
            generated = g.transform(raw, edits, digest)
            self.assertEqual(g.inverse(generated, edits), g.canonical(raw))
            with self.assertRaises(ValueError):
                g.transform(raw + b"\n// unreviewed", edits, digest)
            with self.assertRaises(ValueError):
                g.inverse(generated.replace(edits[0][1], b"bad", 1), edits)
        self.assertNotIn(
            b"ResumeThread(",
            g.transform(
                (source.parent / "native-foundation/harness.cpp").read_bytes(),
                g.changes(),
                g.ACCEPTED,
            ),
        )

    def test_shared_inspector_and_historical_launcher_hashes(self):
        from instrument_a7 import INSPECTOR_SHA

        source = Path(g.__file__).parent
        self.assertEqual(
            hashlib.sha256(
                g.canonical((source / "suspended-inspection.h").read_bytes())
            ).hexdigest(),
            INSPECTOR_SHA,
        )
        header = (source / "ae5-custody.h").read_text()
        self.assertIn("inline volatile const LONG NativeRelease = 1;", header)
        self.assertIn("sizeof(Ack) == 64", header)


if __name__ == "__main__":
    unittest.main()
