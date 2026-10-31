"""Portable adversarial A3 contracts. Never create a native diagnostic process."""

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import a3_observations as d
import a3_qualify as runner
import instrument_harness as ih


def fixture():
    values = {
        "host_elevated": 0,
        "host_appcontainer": 0,
        "appcontainer": 1,
        "final_elevated": 0,
        "CreateRestrictedToken_flags": 9,
        "job_at_creation": 1,
        "job_limit_flags": 8458,
        "job_process_limit": 1,
        "job_memory_bytes": 134217728,
        "job_cpu_100ns": 20000000,
        "capability_count": 1,
        "prelaunch_image_verified": 1,
        "launched_image_independently_verified": 1,
        "hostile_handles_inheritable": 5,
        "hostile_positive_controls": 1,
        "a1_control_effects_verified_and_restored": 1,
        "a3_attribute_mask": 31,
        "a3_attribute_count": 5,
        "a3_inheritance_count": 3,
        "a3_capture_flags": 132,
        "a3_context_flags": 0,
        "a3_inspection_deadline_ms": 5000,
        "a3_termination_deadline_ms": 3000,
        "a3_inspector_finished": 1,
        "a3_inspector_wait": 0,
        "a3_deadline_expired": 0,
        "a3_terminate_job_ok": 1,
        "a3_terminate_job_error": 0,
        "a3_process_wait": 0,
        "a3_exit_query_ok": 1,
        "a3_child_exit": 123,
        "a3_accounting_ok": 1,
        "a3_active_processes": 0,
        "a3_memory_query_ok": 1,
        "a3_child_resumed": 0,
        "a3_inspection_passed": 1,
        "a3_controlled_stop": 1,
        "a3_inventories_consistent": 1,
        "a3_hostile_event_after_child": 258,
        "restore_registry_acl": 0,
        "delete_explicitly_created_registry_storage": 0,
        "delete_synthetic_registry_key": 0,
        "delete_owned_profile_hresult": 0,
        "delete_synthetic_credential": 1,
        "a3_expected_pid": 90,
        "a3_expected_tid": 91,
        "a3_expected_creation": 1000,
        "a3_created_pid": 90,
        "a3_created_tid": 91,
        "child_pid": 90,
        "helper_pid": 92,
        "a3_inspection_elapsed_ms": 25,
        "a3_termination_elapsed_ms": 2,
        "a3_user_cpu_100ns": 0,
        "a3_peak_memory_bytes": 65536,
        "a3_last_stage": 1,
        "a3_pipe_0": 100,
        "a3_pipe_1": 104,
        "a3_pipe_2": 108,
    }
    for prefix in ("a3_s0_", "a3_s1_", "a3_final_"):
        for key, value in {
            "pid": 90,
            "tid": 91,
            "thread_owner": 90,
            "creation": 1000,
            "times_error": 0,
            "process_wait": 258,
        }.items():
            values[prefix + key] = value
        if prefix == "a3_final_":
            continue
        for key, value in {
            "count_before_ok": 1,
            "count_before": 3,
            "capture_status": 0,
            "handle_query_status": 0,
            "thread_query_status": 0,
            "handles_captured": 3,
            "threads_captured": 1,
            "handle_marker_status": 0,
            "thread_marker_status": 0,
            "thread_walk_status": 0,
            "thread_pid": 90,
            "thread_tid": 91,
            "suspend_count": 1,
            "thread_exit": 259,
            "context_bytes": 0,
            "thread_end": 259,
            "handle_end": 259,
            "entries": 3,
            "count_after_ok": 1,
            "count_after": 3,
            "handle_marker_free": 0,
            "thread_marker_free": 0,
            "snapshot_free": 0,
            "policy_ok": 1,
            "policy_error": 0,
            "policy_flags": 3,
            "policy_raise": 1,
            "policy_permanent": 1,
        }.items():
            values[prefix + key] = value
        for i, (raw, mask) in enumerate(((100, 1), (104, 2), (108, 4))):
            for key, value in {
                "raw": raw,
                "pipes": mask,
                "copy_error": 0,
                "checked": 255,
                "hostile": 0,
            }.items():
                values[f"{prefix}h{i}_{key}"] = value
    for i, kind in enumerate((1, 1, 2, 3, 4)):
        for key, value in {
            "begin": 1,
            "info_ok": 1,
            "info_error": 0,
            "flags": 1,
            "duplicate_ok": 1,
            "duplicate_error": 0,
            "type_status": 0,
            "type": kind,
            "known_reference": 1,
            "intended_identity": 1,
            "operation_attempted": 1,
            "operation_ok": 1,
            "operation_error": 0,
            "outcome": 3,
            "complete": 1,
            "raw": 400 + 4 * i,
        }.items():
            values[f"a1_control_h{i}_{key}"] = value
    values.update(
        {
            "a1_control_h0_read_marker": 1,
            "a1_control_h0_operation_bytes": 32,
            "a1_control_h1_operation_bytes": 1,
            "a1_control_h2_operation_bytes": 1,
            "a1_control_h2_mapping_flush_ok": 1,
            "a1_control_h2_mapping_unmap_ok": 1,
            "a1_control_h2_mapping_flush_error": 0,
            "a1_control_h4_duplicated_read_identity": 1,
            "a1_control_h4_duplicated_read_marker": 1,
            "a1_control_h4_duplicated_read_error": 0,
        }
    )
    rows = [{"native": key, "value": value} for key, value in values.items()]
    rows += [{"native": "restore_profile_acl", "value": 0} for _ in range(7)]
    rows += [
        {"native": "native_ambient_write", "allowed": False, "error": 5},
        {"native": "native_explicit_dual_write", "allowed": True, "error": 0},
        {"native": "requested_attempt_sid", "sid": "fresh", "attributes": 0},
        {"native": "final_child_restricted_sids", "sid": "fresh", "attributes": 0},
    ]
    return {
        "observations": rows,
        "cleanup": "confirmed",
        "helper_exit": 0,
        "elapsed_ms": 100,
        "synthetic_resources_unchanged": True,
        "stdout": {"bytes": 0, "overflow": False},
        "stderr": {"overflow": False},
        "independent_cleanup": {
            "profile_absent": True,
            "synthetic_key_absent": True,
            "synthetic_credential_absent": True,
            "owned_storage_absent": True,
            "processes": [
                {"pid": 90, "terminated": True, "open_error": 87},
                {"pid": 92, "terminated": True, "wait": 0, "exit": 0},
            ],
        },
    }


def changed(record, key, value):
    result = copy.deepcopy(record)
    row = next(r for r in result["observations"] if r["native"] == key and "value" in r)
    row["value"] = value
    return result


class A3Contracts(unittest.TestCase):
    def test_complete_feasibility_is_not_qualification(self):
        result = d.validate(fixture())
        self.assertTrue(result["feasibility_demonstrated"])
        self.assertFalse(result["qualified"])
        self.assertFalse(result["child_resumed"])

    def test_every_required_observation_cannot_disappear(self):
        original = fixture()
        for i, row in enumerate(original["observations"]):
            with self.subTest(row=row["native"]):
                record = copy.deepcopy(original)
                del record["observations"][i]
                with self.assertRaises(d.InvalidObservation):
                    d.validate(record)

    def test_duplicate_and_oversized_inventories(self):
        record = fixture()
        for row in record["observations"]:
            if row["native"].startswith("a3_"):
                with self.subTest(row=row["native"]):
                    duplicated = copy.deepcopy(record)
                    duplicated["observations"].append(row.copy())
                    with self.assertRaises(d.InvalidObservation):
                        d.validate(duplicated)
        for count in (0, 2, 4, 17, 2**32):
            for field in ("count_before", "handles_captured", "entries", "count_after"):
                with (
                    self.subTest(count=count, field=field),
                    self.assertRaises(d.InvalidObservation),
                ):
                    d.validate(changed(record, "a3_s0_" + field, count))

    def test_unknown_hostile_and_aliased_objects(self):
        record = fixture()
        for round_no in range(2):
            for i in range(3):
                for mask in (1, 2, 4, 8, 16, 31):
                    with (
                        self.subTest(round=round_no, i=i, hostile=mask),
                        self.assertRaises(d.InvalidObservation),
                    ):
                        d.validate(changed(record, f"a3_s{round_no}_h{i}_hostile", mask))
        for key, value in (
            ("a3_s0_h0_pipes", 0),
            ("a3_s0_h0_pipes", 3),
            ("a3_s0_h0_raw", 104),
            ("a3_s1_h0_raw", 400),
            ("a3_s1_h0_checked", 254),
            ("a3_s0_h0_copy_error", 6),
        ):
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(record, key, value))

    def test_api_refusal_truncation_and_policy(self):
        record = fixture()
        bad = {
            "capture_status": 50,
            "handle_query_status": 5,
            "thread_query_status": 50,
            "handle_marker_status": 8,
            "thread_walk_status": 6,
            "thread_end": 0,
            "handle_end": 234,
            "snapshot_free": 50,
            "policy_ok": 0,
            "policy_error": 5,
            "policy_flags": 1,
            "policy_raise": 0,
            "policy_permanent": 0,
        }
        for round_no in range(2):
            for key, value in bad.items():
                with self.subTest(round=round_no, key=key), self.assertRaises(d.InvalidObservation):
                    d.validate(changed(record, f"a3_s{round_no}_" + key, value))

    def test_deadlines_process_threads_and_cleanup(self):
        bad = {
            "a3_inspection_elapsed_ms": 5000,
            "a3_deadline_expired": 1,
            "a3_inspector_finished": 0,
            "a3_inspector_wait": 258,
            "a3_termination_elapsed_ms": 3001,
            "a3_process_wait": 258,
            "a3_active_processes": 1,
            "a3_s0_suspend_count": 0,
            "a3_s0_threads_captured": 2,
            "a3_s0_thread_tid": 92,
            "a3_s0_creation": 1001,
            "a3_final_process_wait": 0,
            "a3_s1_context_bytes": 100,
            "a3_child_resumed": 1,
            "restore_registry_acl": 5,
            "delete_owned_profile_hresult": 5,
        }
        for key, value in bad.items():
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture(), key, value))
        for key, value in (
            ("cleanup", "unconfirmed"),
            ("helper_exit", 1),
            ("elapsed_ms", 30000),
            ("parent_deadline_exceeded", True),
            ("synthetic_resources_unchanged", False),
        ):
            record = fixture()
            record[key] = value
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(record)

    def test_unexpected_records_never_become_success(self):
        for key in (
            "a3_failure",
            "a3_s0_h3_raw",
            "child_resumed",
            "host_failure",
            "gate_refusal_x",
        ):
            record = fixture()
            record["observations"].append({"native": key, "value": 1})
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(record)

    def test_independent_cleanup_cannot_be_missing_or_uncertain(self):
        for key in (
            "profile_absent",
            "synthetic_key_absent",
            "synthetic_credential_absent",
            "owned_storage_absent",
            "processes",
        ):
            record = fixture()
            del record["independent_cleanup"][key]
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(record)
        for changes in ({"wait": 258}, {"exit": 259}, {"pid": 93}, {"terminated": False}):
            record = fixture()
            record["independent_cleanup"]["processes"][1].update(changes)
            with self.subTest(changes=changes), self.assertRaises(d.InvalidObservation):
                d.validate(record)

    def test_other_cases_cannot_reach_process_creation(self):
        with patch.object(
            runner.subprocess, "Popen", side_effect=AssertionError("native launch")
        ) as launch:
            for case in ("handles", "case-02", "positive", "wrong-launched-image", "leak", "hold"):
                with self.subTest(case=case), self.assertRaises(runner.c.Refused):
                    runner.run_case(None, None, None, 1, case, "probe", None)
            with self.assertRaises(runner.c.Refused):
                runner.run_case(None, None, None, 2, "case-01", "probe", None)
            launch.assert_not_called()

    def test_generated_host_has_only_two_insertions(self):
        original = (runner.FOUNDATION / "harness.cpp").read_bytes()
        generated = ih.instrument(original)
        restored = generated
        for _, insertion in ih.INSERTIONS:
            self.assertEqual(restored.count(insertion), 1)
            restored = restored.replace(insertion, b"")
        self.assertEqual(restored, original)
        with self.assertRaises(ValueError):
            ih.instrument(original + b"\n")

    def test_child_has_no_hostile_slot_or_snapshot_api(self):
        source = Path(__file__).with_name("handle-probe.cpp").read_text()
        for forbidden in (
            "DAF_GATE_",
            "GetHandleInformation",
            "DuplicateHandle",
            "ReadFile",
            "Pss",
            "SetProcessMitigation",
        ):
            self.assertNotIn(forbidden, source)
        supervisor = Path(__file__).with_name("suspended-inspection.h").read_text()
        self.assertIn("WaitForSingleObject(inspector.native_handle(), DeadlineMs)", supervisor)
        self.assertIn("throw FeasibilityComplete{}", supervisor)
        self.assertNotIn("ResumeThread(", supervisor)
        self.assertNotIn("DUPLICATE_CLOSE_SOURCE", supervisor)


if __name__ == "__main__":
    unittest.main()
