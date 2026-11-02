"""In-memory test vectors only: no claims, receipts, native gates or binaries created."""

import copy
import unittest
from pathlib import Path

import ae5_parent as parent
import ae5_resources as resources
import ae5_windows as windows
import ae51_contract as c
import ae51_evidence as evidence
import ae51_snapshot as snapshot
import ae51_tc0 as entry
from ae5_contract import ACK, MAGIC, Ledger, canonical
from test_a3 import fixture as original_fixture
from test_ae5 import observations
from test_ae5 import parent as fake_parent


def bound():
    return {
        "case": "TC-0",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "manifest": "c" * 64,
        "exercise": "d" * 32,
        "files": {
            name: {"bytes": 1, "sha256": "e" * 64}
            for name in (
                "ae5-fixture-host.exe",
                "handle-probe.exe",
                "ae5-fixture-host.cpp",
                "ae5-fixture-harness.h",
                "producer.exe",
                "verifier.exe",
            )
        },
    }


def vector():
    """Synthetic observation model, never persisted or submitted to a native collector."""
    binding = bound()
    offer = {
        "pid": 90,
        "tid": 91,
        "creation": 1000,
        "helper_creation": 100,
        "process": 8,
        "thread": 12,
        "job": 16,
        "references": list(range(200, 208)),
        "pipe_values": [100, 104, 108],
    }
    witness = {
        "capture_flags": 132,
        "context_flags": 0,
        "identity": {"pid": 90, "creation": 1000},
        "thread": {"pid": 90, "tid": 91, "suspend": 1, "exit": 259, "context_bytes": 0},
        "count_before": 3,
        "count_after": 3,
        "strict_flags": 3,
        "temporary_handles_closed": True,
        "handles": [
            {"value": value, "checked": 255, "hostile": 0, "pipes": mask}
            for value, mask in zip((100, 104, 108), (1, 2, 4), strict=True)
        ],
    }
    ledger = Ledger(binding["exercise"], lambda _seq, raw: raw)
    messages = []

    def wire(kind, data):
        messages.append(
            {
                "v": 1,
                "exercise": binding["exercise"],
                "seq": len(messages) + 1,
                "kind": kind,
                "data": data,
            }
        )

    for index, kind in enumerate(
        ["profile", "credential", "desktop", "registry", "registry"] + ["acl"] * 15
    ):
        resource = {
            "kind": kind,
            "name": f"synthetic-{index}",
            "identity": {"absent": True},
            "original": "",
            "created": False,
        }
        wire("intent", {"kind": kind, "name": resource["name"]})
        token = ledger.intent(resource)
        outcome = {"ok": True, "created": kind != "acl", "identity": {"owned": True}}
        wire("commit", {"ok": True, "created": outcome["created"]})
        ledger.commit(token, outcome)
    wire("custody", offer)
    wire("cleanup", {"child_exit": True})
    control = b"".join(
        len(canonical(row)).to_bytes(4, "little") + canonical(row) for row in messages
    )
    acks = b"".join(
        ACK.pack(
            MAGIC, index, 7000 if index == 41 else 31000, 80, 800, binding["exercise"].encode()
        )
        for index in range(43)
    )
    timeline = [
        {
            "event": "ack_written",
            "sequence": index,
            "ms": 1500 + index if index < 41 else 2001 + index - 41,
        }
        for index in range(43)
    ]
    timeline.append({"event": "custody_verified", "ms": 2000})
    custody = observations()
    custody.update(
        helper={"pid": 92, "creation": 100}, child={"pid": 90, "creation": 1000}, thread_pid=90
    )
    live = {
        "helper": {"identity": custody["helper"], "wait": "signalled", "exit": 0},
        "child": {"identity": custody["child"], "wait": "signalled", "exit": 123},
        "active": 0,
        "total": 2,
        "cleanup": True,
    }
    record = {
        "schema": "daf-ae51-observation/v1",
        "case": "TC-0",
        "binding": c.binding(binding),
        "qualified": False,
        "execution_authority": False,
        "resumes": 0,
        "parent": {"pid": 80, "creation": 800},
        "started": 1000,
        "helper_elapsed_ms": 1100,
        "elapsed_ms": 1200,
        "custody": custody,
        "snapshot": witness,
        "custody_verified_ms": 2000,
        "inspection_deadline": 7000,
        "timeline": timeline,
        "ledger": ledger.records,
        "readback": live,
        "control_complete": True,
        "stderr_complete": True,
        "control_overflow": False,
        "stderr_overflow": False,
        "stop_reason": "helper_exit",
        "termination_requests": {},
        "failure": None,
    }
    stderr = b"".join(canonical(row) + b"\n" for row in original_fixture()["observations"])
    record["captures"] = {
        name: {"bytes": len(raw), "sha256": c.digest(raw)}
        for name, raw in (("control", control), ("stderr", stderr), ("acks", acks))
    }
    return record, binding, control, stderr, acks, live


class TC0Preflight(unittest.TestCase):
    def test_bool_exit_or_context_is_not_an_observation(self):
        model = vector()
        model[5]["helper"]["exit"] = False
        with self.assertRaises(ValueError):
            evidence.verify_observations(*model)
        model = vector()
        model[0]["snapshot"]["context_flags"] = False
        with self.assertRaises(ValueError):
            evidence.verify_observations(*model)

    def test_wrong_granted_rights_are_refused(self):
        model = vector()
        model[0]["custody"]["rights"]["thread"] |= 2
        with self.assertRaises(ValueError):
            evidence.verify_observations(*model)

    def test_late_persistence_and_duplicate_completion_stay_stopped(self):
        pending = c.Finalization()
        pending.stop()  # Outer deadline wins while fsync is blocked in another lane.
        with self.assertRaises(ValueError):
            pending.finish(34000, 35000)
        self.assertEqual(pending.state, "STOP")
        late = c.Finalization()
        with self.assertRaises(ValueError):
            late.finish(35000, 35000)
        complete = c.Finalization()
        complete.finish(34000, 35000)
        with self.assertRaises(ValueError):
            complete.finish(34001, 35000)
        self.assertEqual(complete.state, "STOP")

    def test_all_frozen_source_gate_values_are_closed(self):
        self.assertEqual(
            c.source_gates(Path(__file__).parent),
            {"python": False, "windows": False, "cpp": False, "recovery": False, "decision": None},
        )

    def test_consumed_partial_or_stop_cannot_restart(self):
        c.unused_attempt(False, False, False)
        for state in (
            (True, False, False),
            (False, True, False),
            (False, False, True),
            (False, 0, False),
        ):
            with self.subTest(state=state), self.assertRaises(ValueError):
                c.unused_attempt(*state)

    def test_full_shape_foreign_claim_and_stale_receipt_are_rejected(self):
        # Deliberately invalid input vectors, not issued claims/receipts.
        invalid_claim = {
            "schema": "daf-ae51-consumed-claim/v1",
            "case": "TC-0",
            "binding": "0" * 64,
            "approval_sha256": "1" * 64,
            "attempt": 1,
            "retries": 0,
            "mode": "native",
        }
        with self.assertRaisesRegex(ValueError, "claim_binding"):
            c.claim(invalid_claim, bound(), "1" * 64)
        invalid_receipt = {
            "schema": "daf-ae51-independent-receipt/v1",
            "case": "TC-0",
            "binding": "0" * 64,
            "claim_sha256": "1" * 64,
            "evidence_sha256": "2" * 64,
            "readback_sha256": "3" * 64,
            "status": "TC0_EXPECTED_OBSERVATIONS",
            "qualified": False,
            "execution_authority": False,
            "additional_processes_launched": 0,
        }
        with self.assertRaisesRegex(ValueError, "stale_or_foreign_receipt"):
            c.receipt(invalid_receipt, bound(), "1" * 64, "2" * 64, "3" * 64)

    def test_preflight_approval_and_out_of_window_decisions_refused(self):
        for decision in ("PREFLIGHT_ACCEPTED", "COMPILE_PASS", "AUTHORISE_TC1"):
            value = {
                "schema": "daf-ae51-product-approval/v1",
                "case": "TC-0",
                "binding": c.binding(bound()),
                "decision": decision,
                "decision_id": "portable-invalid-input",
                "attempts": 1,
                "retries": 0,
                "not_before": 100,
                "expires": 200,
            }
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                c.approval(value, bound(), 150)
        value["decision"] = "AUTHORISE_TC0_ONCE"
        for now in (99, 200):
            with self.subTest(now=now), self.assertRaises(ValueError):
                c.approval(value, bound(), now)

    def test_public_entry_and_collector_refuse_before_any_effect(self):
        with self.assertRaises(PermissionError):
            parent.native_entry(Path("never-created-package.json"))
        with self.assertRaises(ValueError):
            entry.execute_tc0(Path("never-created-package.json"))
        with self.assertRaises(ValueError):
            entry.collect_tc0(None, None, None, None, None, None)
        self.assertFalse(parent.NATIVE_RELEASE)
        self.assertFalse(windows.NATIVE_RELEASE)
        self.assertFalse(resources.RECOVERY_RELEASE)
        self.assertIsNone(c.PRODUCT_DECISION_ID)

    def test_single_command_has_no_activation_switch(self):
        source = Path(entry.__file__).read_text()
        self.assertNotIn("os.environ", source)
        self.assertNotIn("importlib", source)
        self.assertNotIn("--activate", source)
        self.assertIn("return ae5_parent.native_entry", source)

    def test_positive_complete_observation_model_is_not_receipt(self):
        result = evidence.verify_observations(*vector())
        self.assertEqual(set(result), {"observations_sha256", "qualified", "execution_authority"})
        self.assertFalse(result["qualified"])

    def test_identity_or_case_binding_changes_are_refused(self):
        for field, value in (("case", "TC-1"), ("source_commit", "z" * 40), ("manifest", "0")):
            model = bound()
            model[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.binding(model)
        model = list(vector())
        model[1]["files"]["handle-probe.exe"]["sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            evidence.verify_observations(*model)

    def test_claim_shapes_and_replay_bindings(self):
        # Invalid claim inputs only. No valid native claim is constructed or written.
        for value in ({}, {"case": "TC-0"}, {"schema": "daf-ae51-consumed-claim/v1", "attempt": 2}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.claim(value, bound(), "0" * 64)

    def test_receipts_cannot_be_inferred_from_successful_validation(self):
        for value in (
            {},
            {"status": "TC0_EXPECTED_OBSERVATIONS"},
            {"schema": "daf-ae51-independent-receipt/v1", "binding": "stale"},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.receipt(value, bound(), "0" * 64, "1" * 64, "2" * 64)

    def test_early_late_and_foreign_ack_refused(self):
        args = (
            ACK.pack(MAGIC, 1, 7000, 80, 800, b"d" * 32),
            "d" * 32,
            {"pid": 80, "creation": 800},
            1,
            2000,
            2001,
            7000,
        )
        c.acknowledgement(*args)
        for index, value in ((5, 1999), (5, 7000), (3, 2), (1, "e" * 32), (6, 7001)):
            changed = list(args)
            changed[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                c.acknowledgement(*changed)

    def test_closed_snapshot_suspension_and_identity(self):
        model = vector()
        offer = evidence.frames(model[2])[-2]["data"]
        snapshot.validate_snapshot(model[0]["snapshot"], offer)
        for field, value in (("suspend", 0), ("tid", 999), ("context_bytes", 123), ("exit", 0)):
            changed = copy.deepcopy(model[0]["snapshot"])
            changed["thread"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                snapshot.validate_snapshot(changed, offer)

    def test_unknown_hostile_alias_or_partial_inventory_refused(self):
        for field, value in (
            ("hostile", 1),
            ("pipes", 0),
            ("pipes", 3),
            ("checked", 127),
            ("value", 999),
        ):
            model = vector()
            model[0]["snapshot"]["handles"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                evidence.verify_observations(*model)
        model = vector()
        model[0]["snapshot"]["handles"].pop()
        with self.assertRaises(ValueError):
            evidence.verify_observations(*model)

    def test_actual_custody_and_temporary_closure_required(self):
        for field in (
            "inner_query_closed",
            "helper_transfer_closed",
            "outer_owner_only",
            "noninheritable",
        ):
            model = vector()
            model[0]["custody"][field] = False
            with self.subTest(field=field), self.assertRaises(ValueError):
                evidence.verify_observations(*model)

    def test_ambiguous_exit_cleanup_or_tree_never_passes(self):
        for key, field, value in (
            ("child", "wait", "unknown"),
            ("helper", "exit", 123),
            ("child", "exit", None),
        ):
            model = vector()
            model[5][key][field] = value
            with self.subTest(key=key, field=field), self.assertRaises(ValueError):
                evidence.verify_observations(*model)
        for field, value in (("cleanup", False), ("active", 1)):
            model = vector()
            model[5][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                evidence.verify_observations(*model)

    def test_incomplete_raw_evidence_refused(self):
        for index in (2, 3, 4):
            model = list(vector())
            model[index] = model[index][:-1]
            with self.subTest(index=index), self.assertRaises(ValueError):
                evidence.verify_observations(*model)

    def test_missing_or_interrupted_ledger_refused(self):
        model = vector()
        model[0]["ledger"].pop()
        with self.assertRaises(ValueError):
            evidence.verify_observations(*model)

    def test_duplicate_or_delayed_acks_refused(self):
        for value in (1999, 7000):
            model = vector()
            model[0]["timeline"][41]["ms"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                evidence.verify_observations(*model)
        model = vector()
        model[0]["timeline"].append(model[0]["timeline"][0])
        with self.assertRaises(ValueError):
            evidence.verify_observations(*model)

    def test_stall_deadline_and_stop_are_not_success(self):
        for field, value in (
            ("elapsed_ms", 35000),
            ("helper_elapsed_ms", 30000),
            ("stop_reason", "inspection_deadline"),
            ("failure", "OSError"),
        ):
            model = vector()
            model[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                evidence.verify_observations(*model)

    def test_expected_eof_after_cleanup_is_not_exit_proof(self):
        runner, backend = fake_parent()
        runner.cleanup_ack_written = True
        runner.read_frames(lambda _length: b"", lambda raw: len(raw))
        self.assertTrue(runner.control_complete)
        self.assertTrue(backend.helper_alive())
        self.assertIsNone(runner.decision.reason)

    def test_early_eof_or_partial_eof_causes_stop(self):
        for raw, cleaned in ((b"", False), (b"x", True)):
            runner, _ = fake_parent()
            runner.cleanup_ack_written = cleaned
            runner.read_frames(lambda _length, raw=raw: raw, lambda value: len(value))
            self.assertEqual(runner.decision.state, "STOP")
            self.assertFalse(runner.control_complete)

    def test_native_snapshot_gate_precedes_api_calls(self):
        with self.assertRaises(ValueError):
            snapshot.observe_suspended(None, {})

    def test_json_duplicates_and_bool_identities_refused(self):
        with self.assertRaises(ValueError):
            c.load(b'{"case":"TC-0","case":"TC-1"}')
        model = bound()
        model["files"]["handle-probe.exe"]["bytes"] = True
        with self.assertRaises(ValueError):
            c.binding(model)


if __name__ == "__main__":
    unittest.main()
