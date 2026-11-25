"""Portable A6 fixtures and hostile evidence tests; never launch native tooling."""

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import a6_observations as d
import a6_qualify as runner
import instrument_a6 as instrument
import instrument_harness as original_instrument
from a6_cases import NAMES, specification
from test_a3 import changed
from test_a5 import fixture as prior_fixture


def fixture(case="A6-12"):
    sequence, number, kind, count = specification(case)
    record = prior_fixture()
    record.update(case=case, sequence=sequence)
    rows = record["observations"]
    values = {r["native"]: r["value"] for r in rows if "value" in r}
    for key in list(values):
        if key.startswith("a5_") or re.match(r"a3_s[01]_h\d+_", key):
            del values[key]
        elif key.startswith("a3_fixture_") and not key.startswith("a3_fixture_final_"):
            if key not in ("a3_fixture_table_verified", "a3_fixture_witness_complete"):
                del values[key]
    values.update(
        {
            "a3_failure": 116,
            "a3_inheritance_count": count,
            "a6_case": number,
            "a6_sequence": sequence,
            "a6_kind": kind,
            "a6_normal_inheritance_count": 3,
            "a6_original_handle": {12: 0, 13: 400, 14: 100}[number],
            "a6_inherited_handle": 500,
            "a6_inherited_flags": 1,
            "a6_fixture_list_installed": 1,
            "a6_qpc_frequency": 10000000,
            "a6_tick_unit_ms": 1,
            "a6_qpc_queries_ok": 1,
            "a6_inspection_qpc_ticks": 250000,
            "a6_termination_qpc_ticks": 20000,
            "a6_expected_refusal_verified": 1,
            "a6_controlled_stop": 1,
        }
    )
    specific = {
        12: {
            "semaphore_initial_count": 0,
            "semaphore_maximum_count": 1,
            "semaphore_access": 0x100002,
            "semaphore_control_restored": 1,
            "semaphore_after_child": 258,
        },
        13: {
            "separate_access": 0x80000000,
            "separate_read_marker": 1,
            "separate_file_same": 1,
            "separate_object_same": 0,
            "separate_object_error": 1656,
        },
        14: {
            "wrong_pipe_role": 0,
            "wrong_pipe_object_same": 0,
            "wrong_pipe_object_error": 1656,
            "wrong_pipe_empty": 1,
        },
    }[number]
    values.update({"a6_" + key: value for key, value in specific.items()})
    inventory = (
        [(500, 0), (104, 2), (108, 4)] if number == 14 else [(100, 1), (104, 2), (108, 4), (500, 0)]
    )
    for i, (raw, _) in enumerate(inventory):
        values[f"a6_inherit_{i}"] = raw
    for n in range(2):
        for field in ("count_before", "handles_captured", "entries", "count_after"):
            values[f"a3_s{n}_" + field] = count
        for i, (raw, mask) in enumerate(inventory):
            for key, value in {
                "raw": raw,
                "pipes": mask,
                "hostile": 0,
                "copy_error": 0,
                "checked": 255,
            }.items():
                values[f"a3_s{n}_h{i}_" + key] = value
            w = {
                "raw": raw,
                "pipes": mask,
                "hostile": 0,
                "copy_error": 0,
                "checked": 511,
                "intended": int(raw == 500),
                "type_status": 0,
                "kind": kind if raw == 500 else 7,
            }
            if w["kind"] != 6:
                w["file_type"] = 1 if w["kind"] == 1 else 3
            if raw == 500:
                if number == 12:
                    w["semaphore_wait"] = 258
                elif number == 13:
                    w.update(
                        {
                            "file_id_ok": 1,
                            "file_id_error": 0,
                            "regular_32": 1,
                            "original_object_same": 0,
                            "original_object_error": 1656,
                            "volume": 777,
                            "file_low": 888,
                            "file_high": 0,
                        }
                    )
                else:
                    w.update(
                        {
                            "original_object_same": 0,
                            "original_object_error": 1656,
                            "peek_ok": 1,
                            "available": 0,
                        }
                    )
            values.update({f"a3_fixture_s{n}_h{i}_" + key: value for key, value in w.items()})
    record["observations"] = [
        {"native": k, "value": v} for k, v in values.items() if k != "restore_profile_acl"
    ]
    record["observations"] += [{"native": "restore_profile_acl", "value": 0} for _ in range(7)]
    record["observations"] += [r for r in rows if "value" not in r]
    return record


def save_prior(root, case, prior):
    record = fixture(case)
    record["inspection"] = d.validate(record)
    result = runner.c.canonical(record)
    complete = runner.c.canonical(
        {
            "case": case,
            "build_manifest": "build",
            "records": [record],
            "retries": 0,
            "qualified": False,
            "prior_independent_receipts": prior,
        }
    )
    attempt = root / f"{specification(case)[0]:02d}-{case}-probe"
    attempt.mkdir()
    (attempt / "result.json").write_bytes(result)
    (root / f"{case}-completion.json").write_bytes(complete)
    receipt = {
        "schema": "daf-a6-independent/v1",
        "case": case,
        "independently_verified": True,
        "build_manifest": "build",
        "completion_sha256": runner.c.sha(complete),
        "result_sha256": runner.c.sha(result),
        "qualified": False,
        "fixture_bytes_unchanged": True,
        "owned_registry_storage_independently_absent": True,
        "native_processes_launched_by_readback": 0,
        "verifier_sha256": runner.c.sha(Path(__file__).with_name("a6_verify.py").read_bytes()),
        "cleanup_readback": record["independent_cleanup"],
        "inspection": record["inspection"],
        "fixture_file_identities": {
            name: {"volume": 777, "file_low": 888 + i, "file_high": 0}
            for i, name in enumerate(("read", "write"))
        },
    }
    path = root / f"{case}-independent.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path, receipt


class A6Contracts(unittest.TestCase):
    def test_three_correct_controls_never_grant_authority(self):
        for case in NAMES:
            result = d.validate(fixture(case))
            self.assertFalse(result["qualified"])
            self.assertFalse(result["child_resumed"])
            self.assertEqual(result["policy_refusal_code"], 116)
            self.assertEqual(result["object_kind"], specification(case)[2])
            self.assertEqual(result["handle_count"], specification(case)[3])

    def test_every_required_row_is_mandatory(self):
        for case in NAMES:
            original = fixture(case)
            for i, row in enumerate(original["observations"]):
                with self.subTest(case=case, key=row["native"]):
                    record = copy.deepcopy(original)
                    del record["observations"][i]
                    with self.assertRaises(d.InvalidObservation):
                        d.validate(record)

    def test_every_entry_needs_complete_comparisons_and_correct_type(self):
        for case in NAMES:
            for n in range(2):
                for i in range(specification(case)[3]):
                    for prefix, field, value in (
                        ("", "checked", 254),
                        ("", "hostile", 1),
                        ("", "copy_error", 6),
                        ("fixture_", "checked", 255),
                        ("fixture_", "kind", 0),
                        ("fixture_", "type_status", 5),
                        ("fixture_", "intended", 2),
                    ):
                        with (
                            self.subTest(case=case, n=n, i=i, field=field),
                            self.assertRaises(d.InvalidObservation),
                        ):
                            d.validate(
                                changed(fixture(case), f"a3_{prefix}s{n}_h{i}_{field}", value)
                            )

    def test_count_only_or_known_hostile_refusal_is_wrong_for_a6(self):
        for case in NAMES:
            for value in (0, 115, 201):
                with self.subTest(case=case, code=value), self.assertRaises(d.InvalidObservation):
                    d.validate(changed(fixture(case), "a3_failure", value))

    def test_separate_file_identity_is_not_kernel_object_identity(self):
        for key, value in (
            ("a6_separate_object_same", 1),
            ("a6_separate_file_same", 0),
            ("a3_fixture_s0_h3_original_object_same", 1),
            ("a3_fixture_s1_h3_original_object_error", 6),
            ("a3_fixture_s0_h3_file_low", 889),
            ("a3_fixture_s1_h3_intended", 0),
        ):
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture("A6-13"), key, value))

    def test_wrong_pipe_cannot_pass_with_correct_count(self):
        self.assertEqual(d.validate(fixture("A6-14"))["handle_count"], 3)
        for key, value in (
            ("a6_wrong_pipe_object_same", 1),
            ("a6_wrong_pipe_role", 1),
            ("a3_s0_h0_pipes", 1),
            ("a3_s1_h1_pipes", 4),
            ("a3_fixture_s0_h0_original_object_error", 6),
            ("a3_fixture_s1_h0_file_type", 1),
            ("a3_s1_entries", 4),
        ):
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture("A6-14"), key, value))

    def test_semaphore_control_type_state_and_restoration_are_required(self):
        for key, value in (
            ("a6_semaphore_maximum_count", 2),
            ("a6_semaphore_after_child", 0),
            ("a6_semaphore_control_restored", 0),
            ("a3_fixture_s0_h3_kind", 7),
            ("a3_fixture_s1_h3_semaphore_wait", 0),
        ):
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture(), key, value))

    def test_bounds_suspension_strict_policy_and_cleanup(self):
        for key, value in {
            "a3_s0_policy_flags": 1,
            "a3_s1_suspend_count": 0,
            "a3_child_resumed": 1,
            "a3_active_processes": 1,
            "a3_inspection_elapsed_ms": 5000,
            "a3_termination_elapsed_ms": 3001,
            "a6_inspection_qpc_ticks": 50000000,
            "a6_qpc_queries_ok": 0,
            "a3_s1_handle_end": 234,
            "a3_fixture_final_creation": 1234,
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
            with self.assertRaises(d.InvalidObservation):
                d.validate(record)

    def test_duplicate_and_unknown_records(self):
        for key in ("a6_case", "a6_extra", "a3_extra", "child_resumed", "gate_refusal_x"):
            record = fixture()
            record["observations"].append({"native": key, "value": 1})
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(record)

    def test_unauthorized_case_order_and_role_cannot_launch(self):
        with patch.object(
            runner.subprocess, "Popen", side_effect=AssertionError("native launch")
        ) as launch:
            for sequence, case, role in (
                (1, "A5-03", "probe"),
                (1, "A6-13", "probe"),
                (1, "A6-12", "producer"),
                (4, "A6-15", "probe"),
            ):
                with self.subTest(case=case), self.assertRaises(runner.c.Refused):
                    runner.run_case(None, None, None, sequence, case, role, None)
            launch.assert_not_called()

    def test_sequential_receipts_and_immutable_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prior = []
            for i, case in enumerate(NAMES):
                self.assertEqual(runner.prerequisite(root, "build", case), prior)
                if i < 2:
                    with self.assertRaises(FileNotFoundError):
                        runner.prerequisite(root, "build", NAMES[i + 1])
                path, _ = save_prior(root, case, prior)
                prior.append({"case": case, "sha256": runner.c.sha(path.read_bytes())})
            stop = runner.stop(root, "A6-13", {"stage": "synthetic portable failure"})
            self.assertEqual(list(stop["results"].values()), ["PASS", "FAIL", "NOT RUN"])
            for case in NAMES:
                with self.assertRaises(runner.c.Refused):
                    runner.prerequisite(root, "build", case)
            with self.assertRaises(FileExistsError):
                runner.stop(root, "A6-13", {})

    def test_tampered_receipt_blocks_next_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, receipt = save_prior(root, "A6-12", [])
            for key, value in (
                ("independently_verified", False),
                ("qualified", True),
                ("case", "A6-13"),
                ("completion_sha256", "bad"),
                ("result_sha256", "bad"),
                ("verifier_sha256", "bad"),
                ("build_manifest", "bad"),
                ("fixture_bytes_unchanged", False),
                ("cleanup_readback", None),
                ("fixture_file_identities", {}),
                ("inspection", {}),
            ):
                path.write_text(json.dumps({**receipt, key: value}), encoding="utf-8")
                with self.subTest(key=key), self.assertRaises(runner.c.Refused):
                    runner.prerequisite(root, "build", "A6-13")

    def test_hooks_preserve_accepted_bytes_and_fixture_cannot_resume(self):
        raw = (runner.FOUNDATION / "harness.cpp").read_bytes()
        generated = instrument.instrument(raw)
        for _, insertion in original_instrument.INSERTIONS:
            added = (
                insertion.replace(b"a3::beforeResume", b"a6::beforeResume")
                .replace(b"a3::FeasibilityComplete", b"a6::ControlComplete")
                .replace(b"a3_controlled_stop", b"a6_controlled_stop")
            )
            self.assertEqual(generated.count(added), 1)
            generated = generated.replace(added, b"")
        self.assertEqual(generated, raw)
        root = Path(__file__).parent
        control = (root / "a6-fixture-inspection.h").read_text(encoding="utf-8")
        self.assertIn("a3::inspect(s)", control)
        self.assertIn("[[noreturn]] inline void beforeResume", control)
        self.assertIn("throw ControlComplete{}", control)
        for forbidden in ("ResumeThread(", "DUPLICATE_CLOSE_SOURCE", "SetProcessMitigationPolicy"):
            self.assertNotIn(forbidden, control)
        self.assertNotIn("a6", (root / "gate-host.cpp").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
