"""Portable A5 evidence and sequencing tests. No native fixture is launched."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import a5_observations as d
import a5_qualify as runner
import instrument_a5 as instrument
import instrument_harness as original_instrument
from a5_cases import NAMES, specification
from test_a3 import changed
from test_a4 import fixture as a4_fixture


def fixture(case="A5-03"):
    sequence, number, reference, alias = specification(case)
    record = a4_fixture()
    record.update(
        case=case,
        sequence=sequence,
        status="passed",
        helper_identity={"pid": 92, "query_ok": True, "error": 0, "creation": 2000},
    )
    rows = record["observations"]
    values = {
        r["native"]: r["value"] for r in rows if "value" in r and not r["native"].startswith("a4_")
    }
    for key in list(values):
        if key.startswith("a3_fixture_file_") or key in (
            "a3_fixture_volume",
            "a3_fixture_file_low",
            "a3_fixture_file_high",
        ):
            del values[key]
    original = 400 + reference * 4
    inherited = 500 if alias else original
    values.update(
        {
            "a5_case": number,
            "a5_sequence": sequence,
            "a5_reference_index": reference,
            "a5_alias": int(alias),
            "a5_controlled_stop": 1,
            "a5_expected_refusal_verified": 1,
            "a5_write_file_access": 0xC0000000,
            "a5_mapping_protection": 4,
            "a5_event_manual_reset": 1,
            "a5_event_initial_state": 0,
            "a5_process_access": 0x1040,
            "a5_tick_unit_ms": 1,
            "a5_qpc_queries_ok": 1,
            "a5_qpc_frequency": 10000000,
            "a5_inspection_qpc_ticks": 250000,
            "a5_termination_qpc_ticks": 20000,
            "a5_normal_inheritance_count": 3,
            "a5_original_flags": 1,
            "a5_inherited_flags": 1,
            "a5_parent_same_object": 1,
            "a5_original_in_list": int(not alias),
            "a5_fixture_list_installed": 1,
            "a5_original_handle": original,
            "a5_inherited_handle": inherited,
            "a3_fixture_type_status": 0,
            "a3_fixture_type": reference,
            "a1_control_h4_process_pid": 92,
            "a1_control_h4_process_creation": 2000,
        }
    )
    for i in (0, 1):
        for field, value in {
            "volume": 777,
            "file_low": 888 + i,
            "file_high": 0,
            "regular_32_bytes": 1,
            "file_type": 1,
            "id_ok": 1,
            "id_error": 0,
        }.items():
            values[f"a1_control_h{i}_" + field] = value
    if reference <= 2:
        for key, value in {"volume": 777, "file_low": 889, "file_high": 0}.items():
            values["a5_original_" + key] = value
            if reference == 1:
                values["a3_fixture_" + key] = value
    specific = {
        1: {"file_id_ok": 1, "file_id_error": 0, "file_regular_32": 1},
        2: {
            "map_ok": 1,
            "map_error": 0,
            "map_query_bytes": 48,
            "map_type": 0x40000,
            "map_state": 0x1000,
            "map_protection": 2,
            "map_name_ok": 1,
            "map_name_error": 0,
            "map_backing_match": 1,
            "map_unmap_ok": 1,
            "map_unmap_error": 0,
            "map_region_bytes": 4096,
        },
        3: {"event_wait": 258},
        4: {
            "process_pid": 92,
            "process_pid_error": 0,
            "process_times_ok": 1,
            "process_times_error": 0,
            "process_creation": 2000,
            "process_exit_ok": 1,
            "process_exit": 259,
        },
    }[reference]
    values.update({"a3_fixture_" + key: value for key, value in specific.items()})
    for i, raw in enumerate((100, 104, 108, inherited)):
        values[f"a5_inherit_{i}"] = raw
    for n in range(2):
        values[f"a3_s{n}_h3_raw"] = inherited
        values[f"a3_s{n}_h3_hostile"] = 1 << reference
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
        "schema": "daf-a5-independent/v1",
        "case": case,
        "independently_verified": True,
        "build_manifest": "build",
        "completion_sha256": runner.c.sha(complete),
        "result_sha256": runner.c.sha(result),
        "qualified": False,
        "fixture_bytes_unchanged": True,
        "owned_registry_storage_independently_absent": True,
        "native_processes_launched_by_readback": 0,
        "verifier_sha256": runner.c.sha(Path(__file__).with_name("a5_verify.py").read_bytes()),
        "cleanup_readback": record["independent_cleanup"],
        "inspection": record["inspection"],
        "fixture_file_identities": {
            name: {"volume": 777, "file_low": 888 + i, "file_high": 0}
            for i, name in enumerate(("read", "write"))
        },
    }
    path = root / f"{case}-independent.json"
    path.write_text(json.dumps(receipt))
    return path, receipt


class A5Contracts(unittest.TestCase):
    def test_all_eight_are_refusal_controls_never_qualification(self):
        for case in NAMES:
            with self.subTest(case=case):
                result = d.validate(fixture(case))
                self.assertFalse(result["qualified"])
                self.assertFalse(result["child_resumed"])
                self.assertTrue(result["detector_breadth_control"])
                self.assertEqual(result["policy_refusal_code"], 201)
                self.assertEqual(result["alias"], specification(case)[3])
                for inventory in result["individual_comparisons"]:
                    self.assertEqual(len(inventory), 4)
                    for comparisons in inventory.values():
                        self.assertEqual(len(comparisons), 8)
                        self.assertEqual(sum(comparisons.values()), 1)

    def test_every_required_observation_is_mandatory(self):
        for case in NAMES:
            original = fixture(case)
            for i, row in enumerate(original["observations"]):
                with self.subTest(case=case, row=row["native"]):
                    record = copy.deepcopy(original)
                    del record["observations"][i]
                    with self.assertRaises(d.InvalidObservation):
                        d.validate(record)

    def test_all_comparisons_and_exact_intended_object_are_required(self):
        for case in NAMES:
            for n in range(2):
                for i in range(4):
                    for field, value in (
                        ("checked", 254),
                        ("copy_error", 6),
                        ("hostile", 31),
                        ("pipes", 7),
                        ("raw", 999),
                    ):
                        with self.subTest(case=case, n=n, i=i, field=field):
                            with self.assertRaises(d.InvalidObservation):
                                d.validate(changed(fixture(case), f"a3_s{n}_h{i}_{field}", value))

    def test_count_only_type_only_or_wrong_policy_refusal_is_not_success(self):
        for case in NAMES:
            for key, value in {
                "a3_failure": 115,
                "a3_fixture_object_same": 0,
                "a3_fixture_object_error": 5,
                "a3_fixture_type": 5,
                "a3_fixture_type_status": 6,
                "a3_fixture_witness_complete": 0,
                "a3_s0_handles_captured": 3,
                "a3_s1_entries": 5,
            }.items():
                with self.subTest(case=case, key=key), self.assertRaises(d.InvalidObservation):
                    d.validate(changed(fixture(case), key, value))

    def test_alias_original_absence_and_distinct_numeric_value(self):
        for case in NAMES[4:]:
            original = 400 + specification(case)[2] * 4
            for key, value in (
                ("a5_original_in_list", 1),
                ("a5_inherited_handle", original),
                ("a3_s0_h3_raw", original),
                ("a3_s1_h0_raw", original),
            ):
                with self.subTest(case=case, key=key), self.assertRaises(d.InvalidObservation):
                    d.validate(changed(fixture(case), key, value))

    def test_object_specific_witness_cannot_be_wrong_or_ambiguous(self):
        bad = {
            "A5-03": {"a3_fixture_file_low": 888, "a3_fixture_file_regular_32": 0},
            "A5-04": {
                "a3_fixture_map_backing_match": 0,
                "a3_fixture_map_protection": 4,
                "a3_fixture_map_type": 0x20000,
                "a3_fixture_map_region_bytes": 65537,
                "a3_fixture_map_unmap_ok": 0,
            },
            "A5-05": {"a3_fixture_event_wait": 0},
            "A5-06": {
                "a3_fixture_process_pid": 90,
                "a3_fixture_process_creation": 1000,
                "a3_fixture_process_exit": 0,
            },
        }
        for case, observations in bad.items():
            for key, value in observations.items():
                with self.subTest(case=case, key=key), self.assertRaises(d.InvalidObservation):
                    d.validate(changed(fixture(case), key, value))

    def test_external_helper_identity_is_mandatory(self):
        for case in NAMES:
            for key, value in (("pid", 90), ("creation", 1000), ("query_ok", False), ("error", 5)):
                record = fixture(case)
                record["helper_identity"][key] = value
                with self.subTest(case=case, key=key), self.assertRaises(d.InvalidObservation):
                    d.validate(record)

    def test_timings_strict_policy_suspension_and_cleanup_fail_closed(self):
        bad = {
            "a5_qpc_frequency": 0,
            "a5_qpc_queries_ok": 0,
            "a5_inspection_qpc_ticks": 50000000,
            "a5_termination_qpc_ticks": 30000000,
            "a3_inspection_elapsed_ms": 5000,
            "a3_termination_elapsed_ms": 3001,
            "a3_s0_suspend_count": 0,
            "a3_s1_policy_flags": 1,
            "a3_s1_policy_permanent": 0,
            "a3_child_resumed": 1,
            "a3_fixture_final_creation": 1001,
            "a3_active_processes": 1,
            "a3_child_exit": 259,
            "a3_hostile_event_after_child": 0,
            "delete_owned_profile_hresult": 5,
        }
        for key, value in bad.items():
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture(), key, value))
        for key, value in (
            ("cleanup", "unconfirmed"),
            ("helper_exit", 1),
            ("synthetic_resources_unchanged", False),
            ("parent_deadline_exceeded", True),
        ):
            record = fixture()
            record[key] = value
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(record)
        record = fixture()
        record["independent_cleanup"]["processes"][1]["wait"] = 258
        with self.assertRaises(d.InvalidObservation):
            d.validate(record)

    def test_unexpected_duplicate_or_noninteger_rows_fail(self):
        for key, value in (
            ("a5_extra", 1),
            ("a3_extra", 1),
            ("a5_case", 3),
            ("child_resumed", 0),
            ("host_failure", 0),
            ("gate_refusal_x", 0),
        ):
            record = fixture()
            record["observations"].append({"native": key, "value": value})
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(record)
        with self.assertRaises(d.InvalidObservation):
            d.validate(changed(fixture(), "a5_alias", False))

    def test_unauthorized_cases_order_or_role_never_launch(self):
        with patch.object(
            runner.subprocess, "Popen", side_effect=AssertionError("native launch")
        ) as launch:
            for sequence, case, role in (
                (1, "A4-01", "probe"),
                (1, "A5-04", "probe"),
                (1, "A5-03", "producer"),
                (9, "A5-12", "probe"),
                (1, "stall", "probe"),
            ):
                with self.subTest(case=case), self.assertRaises(runner.c.Refused):
                    runner.run_case(None, None, None, sequence, case, role, None)
            launch.assert_not_called()

    def test_all_prior_receipts_are_required_in_exact_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prior = []
            for i, case in enumerate(NAMES):
                self.assertEqual(runner.prerequisite(root, "build", case), prior)
                if i < 7:
                    with self.assertRaises(FileNotFoundError):
                        runner.prerequisite(root, "build", NAMES[i + 1])
                path, _ = save_prior(root, case, prior)
                prior.append({"case": case, "sha256": runner.c.sha(path.read_bytes())})
            (root / "A5-03-independent.json").unlink()
            with self.assertRaises(FileNotFoundError):
                runner.prerequisite(root, "build", "A5-11")

    def test_tampered_independent_receipt_blocks_next_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, receipt = save_prior(root, "A5-03", [])
            for key, value in (
                ("case", "A5-04"),
                ("independently_verified", False),
                ("qualified", True),
                ("build_manifest", "other"),
                ("completion_sha256", "bad"),
                ("result_sha256", "bad"),
                ("verifier_sha256", "bad"),
                ("fixture_bytes_unchanged", False),
                ("owned_registry_storage_independently_absent", False),
                ("native_processes_launched_by_readback", 1),
                ("cleanup_readback", None),
                ("fixture_file_identities", {}),
                ("inspection", {}),
            ):
                path.write_text(json.dumps({**receipt, key: value}))
                with self.subTest(key=key), self.assertRaises(runner.c.Refused):
                    runner.prerequisite(root, "build", "A5-04")

    def test_failure_stops_every_later_case_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = runner.stop(root, "A5-04", {"stage": "unexpected"})
            self.assertEqual(list(value["results"].values()), ["PASS", "FAIL", *(["NOT RUN"] * 6)])
            for case in NAMES:
                with self.assertRaises(runner.c.Refused):
                    runner.prerequisite(root, "build", case)
            with self.assertRaises(FileExistsError):
                runner.stop(root, "A5-04", {})

    def test_hooks_remove_to_exact_accepted_harness(self):
        raw = (runner.FOUNDATION / "harness.cpp").read_bytes()
        generated = instrument.instrument(raw)
        for _, insertion in original_instrument.INSERTIONS:
            added = (
                insertion.replace(b"a3::beforeResume", b"a5::beforeResume")
                .replace(b"a3::FeasibilityComplete", b"a5::ControlComplete")
                .replace(b"a3_controlled_stop", b"a5_controlled_stop")
            )
            self.assertEqual(generated.count(added), 1)
            generated = generated.replace(added, b"")
        self.assertEqual(generated, raw)
        with self.assertRaises(ValueError):
            instrument.instrument(raw + b"\n")

    def test_normal_policy_and_fixture_separation(self):
        root = Path(__file__).parent
        candidate = (root / "gate-host.cpp").read_text()
        self.assertIn('a3::emit("inheritance_count", 3)', candidate)
        self.assertNotIn("fixtureHandles", candidate)
        inspector = (root / "suspended-inspection.h").read_text()
        self.assertIn("found.values.size() == 3", inspector)
        self.assertIn("s.require(mask == 0, 201)", inspector)
        self.assertNotIn("a5::", inspector)
        control = (root / "fixture-inspection.h").read_text()
        self.assertIn("a3::inspect(s)", control)
        self.assertIn("[[noreturn]] inline void beforeResume", control)
        self.assertIn("throw ControlComplete{}", control)
        witness = (root / "fixture-object-witness.h").read_text()
        for forbidden in ("ResumeThread(", "DUPLICATE_CLOSE_SOURCE", "SetProcessMitigationPolicy"):
            self.assertNotIn(forbidden, control + witness)
        for forbidden in ("WriteFile(", "SetEvent(", "ResetEvent("):
            self.assertNotIn(forbidden, witness)
        self.assertNotIn("native-prelaunch", (root.parent / "build.cjs").read_text())


if __name__ == "__main__":
    unittest.main()
