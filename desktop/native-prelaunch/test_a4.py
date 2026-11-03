"""Portable A4 adversarial controls. No fixture process is launched here."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import a4_observations as d
import a4_qualify as runner
import instrument_fixture as instrument
import instrument_harness as original_instrument
from test_a3 import changed
from test_a3 import fixture as a3_fixture


def fixture(sequence=1):
    record = a3_fixture()
    record.update(case=f"A4-0{sequence}", sequence=sequence, role="probe")
    values = {r["native"]: r["value"] for r in record["observations"] if "value" in r}
    del values["a3_controlled_stop"]
    inherited = 400 if sequence == 1 else 460
    values.update(
        {
            "a3_inheritance_count": 4,
            "a3_inspection_passed": 0,
            "a3_failure": 201,
            "a4_controlled_stop": 1,
            "a4_expected_refusal_verified": 1,
            "a4_case": sequence,
            "a4_normal_inheritance_count": 3,
            "a4_original_flags": 1,
            "a4_inherited_flags": 1,
            "a4_parent_same_object": 1,
            "a4_original_in_list": int(sequence == 1),
            "a4_fixture_list_installed": 1,
            "a4_original_handle": 400,
            "a4_inherited_handle": inherited,
            "a3_fixture_table_verified": 1,
            "a3_fixture_copy_error": 0,
            "a3_fixture_object_same": 1,
            "a3_fixture_object_error": 0,
            "a3_fixture_file_id_ok": 1,
            "a3_fixture_file_id_error": 0,
            "a3_fixture_witness_complete": 1,
            "a1_control_h0_regular_32_bytes": 1,
            "a1_control_h0_file_type": 1,
            "a1_control_h0_id_ok": 1,
            "a1_control_h0_id_error": 0,
        }
    )
    for i, raw in enumerate((100, 104, 108, inherited)):
        values[f"a4_inherit_{i}"] = raw
    for field, value in (("volume", 777), ("file_low", 888), ("file_high", 0)):
        for prefix in ("a4_original_", "a1_control_h0_", "a3_fixture_"):
            values[prefix + field] = value
    for key in ("pid", "tid", "thread_owner", "creation", "times_error", "process_wait"):
        values["a3_fixture_final_" + key] = values["a3_final_" + key]
    for n in range(2):
        prefix = f"a3_s{n}_"
        for key in ("count_before", "handles_captured", "entries", "count_after"):
            values[prefix + key] = 4
        for key, value in {
            "raw": inherited,
            "pipes": 0,
            "hostile": 1,
            "copy_error": 0,
            "checked": 255,
        }.items():
            values[prefix + "h3_" + key] = value
    non_numeric = [r for r in record["observations"] if "value" not in r]
    record["observations"] = [
        {"native": k, "value": v} for k, v in values.items() if k != "restore_profile_acl"
    ]
    record["observations"] += [
        {"native": "restore_profile_acl", "value": 0} for _ in range(7)
    ] + non_numeric
    return record


class A4Contracts(unittest.TestCase):
    def test_direct_and_alias_are_refusals_not_acceptance(self):
        for sequence in (1, 2):
            result = d.validate(fixture(sequence))
            self.assertTrue(result["initial_detector_sensitivity"])
            self.assertFalse(result["qualified"])
            self.assertFalse(result["child_resumed"])
            self.assertEqual(result["policy_refusal_code"], 201)
            self.assertEqual(result["original_handle"] == result["inherited_handle"], sequence == 1)

    def test_every_required_observation_is_mandatory(self):
        for sequence in (1, 2):
            original = fixture(sequence)
            for i, row in enumerate(original["observations"]):
                with self.subTest(sequence=sequence, row=row["native"]):
                    record = copy.deepcopy(original)
                    del record["observations"][i]
                    with self.assertRaises(d.InvalidObservation):
                        d.validate(record)

    def test_count_only_or_setup_failure_is_not_success(self):
        for key, value in {
            "a3_failure": 115,
            "a3_s0_h3_hostile": 0,
            "a3_s1_h3_hostile": 0,
            "a4_fixture_list_installed": 0,
            "a4_parent_same_object": 0,
            "a3_fixture_object_same": 0,
            "a3_fixture_copy_error": 6,
            "a3_fixture_witness_complete": 0,
            "a4_inherited_flags": 0,
            "a3_s0_h3_checked": 254,
            "a3_s0_h3_pipes": 1,
            "a3_s1_h2_hostile": 2,
            "a3_inspection_passed": 1,
        }.items():
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture(), key, value))

    def test_alias_original_slot_and_object_identity(self):
        for key, value in {
            "a4_inherited_handle": 400,
            "a4_original_in_list": 1,
            "a4_inherit_3": 400,
            "a3_s0_h3_raw": 400,
            "a3_s1_h3_raw": 400,
            "a3_fixture_volume": 778,
            "a3_fixture_file_low": 889,
            "a4_original_file_high": 1,
            "a3_fixture_object_error": 6,
            "a3_fixture_file_id_ok": 0,
            "a1_control_h0_raw": 404,
        }.items():
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture(2), key, value))

    def test_incomplete_duplicate_oversized_or_unknown_inventory(self):
        for sequence in (1, 2):
            for round_no in range(2):
                for key, value in {
                    "count_before": 3,
                    "handles_captured": 17,
                    "entries": 5,
                    "count_after": 3,
                    "handle_end": 234,
                    "h3_raw": 100,
                    "h2_hostile": 16,
                    "h1_pipes": 0,
                    "h3_copy_error": 5,
                    "h3_checked": 127,
                }.items():
                    with (
                        self.subTest(sequence=sequence, round=round_no, key=key),
                        self.assertRaises(d.InvalidObservation),
                    ):
                        d.validate(changed(fixture(sequence), f"a3_s{round_no}_" + key, value))
            record = fixture(sequence)
            record["observations"].append({"native": "a3_s0_h4_raw", "value": 800})
            with self.assertRaises(d.InvalidObservation):
                d.validate(record)

    def test_no_resume_deadline_policy_thread_or_cleanup_exceptions(self):
        for key, value in {
            "a3_child_resumed": 1,
            "a3_inspection_elapsed_ms": 5000,
            "a3_deadline_expired": 1,
            "a3_termination_elapsed_ms": 3001,
            "a3_process_wait": 258,
            "a3_active_processes": 1,
            "a3_s0_capture_status": 50,
            "a3_s1_policy_flags": 1,
            "a3_s0_policy_error": 5,
            "a3_s1_suspend_count": 0,
            "a3_s1_threads_captured": 2,
            "a3_fixture_final_creation": 1001,
            "delete_owned_profile_hresult": 5,
        }.items():
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture(), key, value))
        for key, value in (
            ("cleanup", "unconfirmed"),
            ("helper_exit", 1),
            ("synthetic_resources_unchanged", False),
        ):
            record = fixture()
            record[key] = value
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(record)
        record = fixture()
        record["independent_cleanup"]["processes"][1]["wait"] = 258
        with self.assertRaises(d.InvalidObservation):
            d.validate(record)

    def test_unexpected_or_duplicate_records_fail(self):
        for key in ("a3_failure", "a4_unknown", "child_resumed", "host_failure", "gate_refusal_x"):
            record = fixture()
            record["observations"].append({"native": key, "value": 1})
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(record)

    def test_other_native_cases_cannot_launch(self):
        with patch.object(
            runner.subprocess, "Popen", side_effect=AssertionError("native launch")
        ) as launch:
            for sequence, case in (
                (1, "A4-02"),
                (2, "A4-01"),
                (3, "A4-03"),
                (1, "case-01"),
                (1, "stall"),
            ):
                with self.subTest(case=case), self.assertRaises(runner.c.Refused):
                    runner.run_case(None, None, None, sequence, case, "probe", None)
            launch.assert_not_called()

    def test_second_case_requires_matching_independent_first_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                runner.prerequisite(root, "build")
            record = fixture()
            record["status"] = "passed"
            result = runner.c.canonical(record)
            complete = runner.c.canonical(
                {"build_manifest": "build", "records": [record], "retries": 0}
            )
            (root / "01-A4-01-probe").mkdir()
            (root / "01-A4-01-probe/result.json").write_bytes(result)
            (root / "A4-01-completion.json").write_bytes(complete)
            receipt = {
                "schema": "daf-a4-independent/v1",
                "case": "A4-01",
                "independently_verified": True,
                "build_manifest": "build",
                "completion_sha256": runner.c.sha(complete),
                "result_sha256": runner.c.sha(result),
                "qualified": False,
                "fixture_bytes_unchanged": True,
                "owned_registry_storage_independently_absent": True,
                "native_processes_launched_by_readback": 0,
                "verifier_sha256": runner.c.sha(
                    Path(__file__).with_name("a4_verify.py").read_bytes()
                ),
                "cleanup_readback": record["independent_cleanup"],
                "inspection": d.validate(record),
                "fixture_file_identity": {"volume": 777, "file_low": 888, "file_high": 0},
            }
            path = root / "A4-01-independent.json"
            path.write_text(json.dumps(receipt))
            self.assertEqual(runner.prerequisite(root, "build"), runner.c.sha(path.read_bytes()))
            for key, value in (
                ("case", "A4-02"),
                ("independently_verified", False),
                ("build_manifest", "other"),
                ("completion_sha256", "bad"),
                ("result_sha256", "bad"),
                ("verifier_sha256", "bad"),
                ("fixture_bytes_unchanged", False),
                ("owned_registry_storage_independently_absent", False),
                ("native_processes_launched_by_readback", 1),
                ("cleanup_readback", None),
                ("fixture_file_identity", {}),
                ("inspection", {}),
            ):
                path.write_text(json.dumps({**receipt, key: value}))
                with self.subTest(key=key), self.assertRaises(runner.c.Refused):
                    runner.prerequisite(root, "build")

    def test_fixture_hooks_preserve_all_accepted_source_bytes(self):
        raw = (runner.FOUNDATION / "harness.cpp").read_bytes()
        generated = instrument.instrument(raw)
        for _, insertion in original_instrument.INSERTIONS:
            replaced = (
                insertion.replace(b"a3::beforeResume", b"a4::beforeResume")
                .replace(b"a3::FeasibilityComplete", b"a4::ControlComplete")
                .replace(b"a3_controlled_stop", b"a4_controlled_stop")
            )
            self.assertEqual(generated.count(replaced), 1)
            generated = generated.replace(replaced, b"")
        self.assertEqual(generated, raw)
        with self.assertRaises(ValueError):
            instrument.instrument(raw + b"\n")

    def test_separate_fixture_cannot_relax_candidate_policy_or_resume(self):
        root = Path(__file__).parent
        candidate = (root / "gate-host.cpp").read_text()
        self.assertIn('a3::emit("inheritance_count", 3)', candidate)
        self.assertNotIn("fixtureHandles", candidate)
        inspector = (root / "suspended-inspection.h").read_text()
        self.assertIn("found.values.size() == 3", inspector)
        self.assertIn("s.require(mask == 0, 201)", inspector)
        self.assertNotIn("a4::", inspector)
        control = (root / "fixture-inspection.h").read_text()
        self.assertIn("a3::inspect(s)", control)
        self.assertIn("[[noreturn]] inline void beforeResume", control)
        self.assertIn("throw ControlComplete{}", control)
        for forbidden in ("ResumeThread(", "DUPLICATE_CLOSE_SOURCE", "SetProcessMitigationPolicy"):
            self.assertNotIn(forbidden, control)
        package = (root.parent / "build.cjs").read_text()
        self.assertNotIn("native-prelaunch", package)
        self.assertNotIn("fixture-host", package)


if __name__ == "__main__":
    unittest.main()
