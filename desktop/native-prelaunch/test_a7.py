"""Portable A7 adversarial contracts; never build or launch a native fixture."""

import copy
import hashlib
import itertools
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import a7_build_review as build_review
import a7_observations as d
import a7_qualify as runner
import instrument_a7 as instrument
from a7_cases import NAMES, specification
from test_a3 import changed as change_existing
from test_a6 import fixture as prior_fixture


def changed(record, key, value):
    if any(r["native"] == key for r in record["observations"]):
        return change_existing(record, key, value)
    result = copy.deepcopy(record)
    result["observations"].append({"native": key, "value": value})
    return result


def fixture(case="A7-C0"):
    sequence, number, mutation, count = specification(case)
    record = prior_fixture()
    record.update(case=case, sequence=sequence)
    rows = record["observations"]
    for row in rows:
        if row["native"] in ("native_ambient_write", "native_explicit_dual_write"):
            row["bytes_written"] = int(row["allowed"])
    # Add the remaining pinned harness row shapes with synthetic scalar values.
    # No host paths, real SIDs or historical execution values enter this fixture.
    for item in d.COMMON_SHAPE:
        present = sum(
            r["native"] == item["native"] and set(r) == {"native", *item["fields"]} for r in rows
        )
        for _ in range(item["count"] - present):
            rows.append(
                {
                    "native": item["native"],
                    **{
                        key: 0 if kind == "int" else False if kind == "bool" else "synthetic"
                        for key, kind in item["fields"].items()
                    },
                }
            )
    values = {r["native"]: r["value"] for r in rows if "value" in r}
    for key in list(values):
        if (
            key.startswith(("a6_", "a3_fixture_"))
            or re.match(r"a3_s0_h3_", key)
            or (not mutation and re.match(r"a3_s1_h3_", key))
            or (mutation and key.startswith("a3_final_"))
            or key in ("a3_failure", "a3_inventories_consistent")
        ):
            del values[key]
    values.update(
        {
            "a3_inheritance_count": 3,
            "a3_inspection_passed": int(not mutation),
            "a3_last_stage": 2 if mutation else 1,
        }
    )
    values["a3_failure" if mutation else "a3_inventories_consistent"] = 120 if mutation else 1
    for n in (0, 1):
        for field in ("count_before", "handles_captured", "entries", "count_after"):
            values[f"a3_s{n}_{field}"] = count if n else 3
    if mutation:
        values["a3_s1_h3_hostile"] = 8
    a7 = {
        "case": number,
        "sequence": sequence,
        "controlled_stop": 1,
        "expected_result_verified": 1,
        "qpc_frequency": 10000000,
        "tick_unit_ms": 1,
        "qpc_queries_ok": 1,
        "inspection_qpc_ticks": 250000,
        "termination_qpc_ticks": 20000,
        "boundary_calls": 1,
        "boundary_begin_qpc": 1000,
        "boundary_end_qpc": 2000,
        "post_end_qpc": 3000,
        "boundary_complete": 1,
        "boundary_before_ok": 1,
        "boundary_before_value": 3,
        "boundary_after_ok": 1,
        "boundary_after_value": count,
        "event_before": 258,
        "inward_attempts": int(mutation),
        "target": 500 if mutation else 0,
        "requested_access": 0x100000 if mutation else 0,
        "requested_inherit": 0,
        "requested_options": 0,
        "shared_passed": int(not mutation),
        "shared_inventory_complete": int(not mutation),
        "shared_failure": 120 if mutation else 0,
        "post_count_ok": 1,
        "post_count_value": count,
        "witness_complete": 1,
        "rows_bounded": 1,
    }
    if mutation:
        a7.update(inward_begin_qpc=1200, inward_end_qpc=1400, inward_ok=1, inward_error=0)
    for prefix in ("boundary_", "post_"):
        for key in ("pid", "tid", "thread_owner", "creation", "times_error", "process_wait"):
            a7[prefix + key] = values["a3_s0_" + key]

    def witness(prefix, raw, mask, event):
        fields = {
            "raw": raw,
            "copy_ok": 1,
            "copy_error": 0,
            "checked": 255,
            "hostile": 8 if event else 0,
            "pipes": mask,
            "type_status": 0,
            "type_bytes": 112,
            "kind": 3 if event else 7,
        }
        if event:
            fields.update(basic_status=0, basic_bytes=56, access=0x100000, event_wait=258)
        else:
            fields["file_type"] = 3
        a7.update({prefix + k: v for k, v in fields.items()})

    if mutation:
        witness("boundary_w_", 500, 0, True)
    for i, (raw, mask) in enumerate(
        [(100, 1), (104, 2), (108, 4), *([(500, 0)] if mutation else [])]
    ):
        witness(f"post_h{i}_", raw, mask, raw == 500)
    state_count = sum(k.startswith(("a3_s0_", "a3_s1_", "a3_final_")) for k in values) + 3
    external = {
        "case",
        "sequence",
        "controlled_stop",
        "expected_result_verified",
        "qpc_frequency",
        "tick_unit_ms",
        "qpc_queries_ok",
        "inspection_qpc_ticks",
        "termination_qpc_ticks",
        "rows_bounded",
    }
    a7["published_rows"] = state_count + len(set(a7) - external)
    values.update({"a7_" + k: v for k, v in a7.items()})
    record["observations"] = [
        {"native": k, "value": v} for k, v in values.items() if k != "restore_profile_acl"
    ]
    record["observations"] += [{"native": "restore_profile_acl", "value": 0} for _ in range(7)]
    record["observations"] += [r for r in rows if "value" not in r]
    return record


def save_prior(root):
    record = fixture()
    record["inspection"] = d.validate(record)
    result = runner.c.canonical(record)
    complete = runner.c.canonical(
        {
            "case": "A7-C0",
            "build_manifest": "build",
            "records": [record],
            "retries": 0,
            "qualified": False,
            "prior_independent_receipts": [],
        }
    )
    attempt = root / "01-A7-C0-probe"
    attempt.mkdir()
    (attempt / "result.json").write_bytes(result)
    (root / "A7-C0-completion.json").write_bytes(complete)
    receipt = {
        "schema": "daf-a7-independent/v1",
        "case": "A7-C0",
        "independently_verified": True,
        "build_manifest": "build",
        "completion_sha256": runner.c.sha(complete),
        "result_sha256": runner.c.sha(result),
        "qualified": False,
        "fixture_bytes_unchanged": True,
        "owned_registry_storage_independently_absent": True,
        "native_processes_launched_by_readback": 0,
        "verifier_sha256": runner.c.sha(Path(__file__).with_name("a7_verify.py").read_bytes()),
        "cleanup_readback": record["independent_cleanup"],
        "inspection": record["inspection"],
        "fixture_file_identities": {
            name: {"volume": 777, "file_low": 888 + i, "file_high": 0}
            for i, name in enumerate(("read", "write"))
        },
    }
    path = root / "A7-C0-independent.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path, receipt


class A7Contracts(unittest.TestCase):
    def test_actual_dependency_and_preprocessed_source_review_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory).resolve()
            baseline = Path(__file__).with_name("suspended-inspection.h").read_bytes()
            (build / "a7-inspector-baseline.h").write_bytes(baseline)
            generated = build / "a7-suspended-inspection.generated.h"
            generated.write_bytes(instrument.inspector(baseline))
            for leaf, header in (
                ("a7-fixture-host.i", generated),
                ("a7-preprocess-baseline.i", build / "a7-inspector-baseline.h"),
            ):
                (build / leaf).write_text(
                    f"#line 1 {json.dumps(str(header))}\n" + header.read_text(), encoding="utf-8"
                )
            dependencies = {
                "Data": {
                    "Source": str(Path(__file__).with_name("a7-fixture-host.cpp").resolve()),
                    "Includes": [str(generated.resolve())],
                }
            }
            path = build / "a7-fixture-host.dependencies.json"
            path.write_text(json.dumps(dependencies), encoding="utf-8")
            self.assertTrue(build_review.review(build)["preprocessed_inverse_exact"])
            for source, includes in (
                ("wrong.cpp", [str(generated)]),
                (dependencies["Data"]["Source"], []),
                (
                    dependencies["Data"]["Source"],
                    [str(generated), "C:/other/suspended-inspection.h"],
                ),
                (dependencies["Data"]["Source"], [str(generated)] * 2),
            ):
                path.write_text(
                    json.dumps({"Data": {"Source": source, "Includes": includes}}), encoding="utf-8"
                )
                with self.assertRaises(ValueError):
                    build_review.review(build)

    def test_all_success_evidence_fits_unchanged_capture_bound(self):
        for case, count, maximum in (("A7-C0", 419, 29141), ("A7-15", 448, 30970)):
            rows = fixture(case)["observations"]
            self.assertEqual(len(rows), count)
            self.assertEqual(d.evidence_bound(rows), maximum)
            self.assertLess(maximum, 32768)
            d.validate(fixture(case))

    def test_positive_controls_preserve_success_meanings_and_no_authority(self):
        for case in NAMES:
            result = d.validate(fixture(case))
            self.assertFalse(
                result["qualified"] or result["execution_authority"] or result["child_resumed"]
            )
            self.assertEqual(result["candidate_passed"], case == "A7-C0")
            self.assertEqual(result["inventoryComplete"], case == "A7-C0")
            self.assertEqual(result["added"], [500] if case == "A7-15" else [])
            self.assertEqual(result["removed"], [])

    def test_every_required_diagnostic_observation_is_mandatory(self):
        for case in NAMES:
            original = fixture(case)
            for i, row in enumerate(original["observations"]):
                if row["native"].startswith(("a3_", "a7_")):
                    record = copy.deepcopy(original)
                    del record["observations"][i]
                    with (
                        self.subTest(case=case, key=row["native"]),
                        self.assertRaises(d.InvalidObservation),
                    ):
                        d.validate(record)

    def test_sham_cannot_inject_or_force_refusal(self):
        for key, value in {
            "a7_inward_attempts": 1,
            "a7_target": 500,
            "a3_failure": 120,
            "a7_shared_passed": 0,
            "a7_shared_inventory_complete": 0,
            "a7_boundary_after_value": 4,
        }.items():
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture(), key, value))

    def test_mutation_requires_exact_actual_120_not_fixture_assertion(self):
        for key, value in {
            "a3_failure": 201,
            "a7_shared_passed": 1,
            "a7_shared_inventory_complete": 1,
            "a3_inventories_consistent": 1,
            "a7_inward_attempts": 0,
            "a7_boundary_before_value": 4,
            "a7_boundary_after_value": 3,
            "a7_target": 104,
            "a7_requested_access": 0x100002,
            "a7_requested_inherit": 1,
            "a7_requested_options": 1,
            "a7_inward_ok": 0,
            "a7_boundary_calls": 2,
            "a7_inward_begin_qpc": 2100,
        }.items():
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture("A7-15"), key, value))
        for refusal in (0, 115, 116, 121, 199, 201):
            with self.subTest(refusal=refusal), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture("A7-15"), "a3_failure", refusal))

    def test_every_object_comparison_and_type_access_witness_is_required(self):
        for case in NAMES:
            original = fixture(case)
            for row in original["observations"]:
                key = row["native"]
                if re.match(r"a3_s[01]_h\d+_(checked|pipes|hostile)", key) or (
                    key.startswith(("a7_boundary_w_", "a7_post_h"))
                ):
                    with self.subTest(case=case, key=key), self.assertRaises(d.InvalidObservation):
                        d.validate(changed(original, key, 2**64 - 1))

    def test_partial_same_count_wrong_object_and_restore_records_do_not_qualify(self):
        for key, value in {
            "a3_s1_entries": 3,
            "a3_s0_entries": 4,
            "a3_s1_h3_raw": 104,
            "a3_s1_h3_hostile": 0,
            "a3_s1_h0_raw": 900,
            "a3_s1_handle_end": 234,
            "a3_s1_capture_status": 5,
            "a3_s0_count_after": 4,
        }.items():
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(fixture("A7-15"), key, value))

    def test_enumeration_order_does_not_change_set_difference(self):
        original = fixture("A7-15")
        for order in itertools.permutations(range(4)):
            record = copy.deepcopy(original)
            for row in record["observations"]:
                for prefix in ("a3_s1_h", "a7_post_h"):
                    if re.match(re.escape(prefix) + r"[0-3]_", row["native"]):
                        at = len(prefix)
                        row["native"] = (
                            prefix + str(order[int(row["native"][at])]) + row["native"][at + 1 :]
                        )
            self.assertEqual(d.validate(record)["added"], [500])

    def test_bounds_suspension_strict_policy_supervision_and_cleanup(self):
        for case in NAMES:
            for key, value in {
                "a3_s0_policy_flags": 1,
                "a3_s1_suspend_count": 0,
                "a3_child_resumed": 1,
                "a3_deadline_expired": 1,
                "a3_inspection_elapsed_ms": 5000,
                "a3_termination_elapsed_ms": 3001,
                "a3_active_processes": 1,
                "a7_published_rows": 385,
                "a7_rows_bounded": 0,
                "a7_post_pid": 999,
            }.items():
                with self.subTest(case=case, key=key), self.assertRaises(d.InvalidObservation):
                    d.validate(changed(fixture(case), key, value))
            record = fixture(case)
            record["independent_cleanup"]["profile_absent"] = False
            with self.assertRaises(d.InvalidObservation):
                d.validate(record)

    def test_unknown_duplicate_and_extra_row_fields_fail(self):
        for case in NAMES:
            for row in ({"native": "a7_unknown", "value": 1}, {"native": "a7_case", "value": 0}):
                record = fixture(case)
                record["observations"].append(row)
                with self.assertRaises(d.InvalidObservation):
                    d.validate(record)
            record = fixture(case)
            next(r for r in record["observations"] if r["native"] == "a7_case")["unexpected"] = True
            with self.assertRaises(d.InvalidObservation):
                d.validate(record)

    def test_unsuccessful_mutation_is_inconclusive_not_containment_pass(self):
        record = changed(fixture("A7-15"), "a7_inward_ok", 0)
        record = changed(record, "a7_target", 0)
        record["helper_exit"] = 1
        self.assertEqual(d.nonpass_classification(record), "INCONCLUSIVE")
        self.assertEqual(
            d.nonpass_classification(changed(fixture("A7-15"), "a3_failure", 201)), "FAIL"
        )
        self.assertEqual(
            d.nonpass_classification(changed(record, "a3_deadline_expired", 1)), "FAIL"
        )

    def test_receipt_chain_and_immutable_stop_enforce_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                runner.prerequisite(root, "build", "A7-15")
            path, receipt = save_prior(root)
            self.assertEqual(
                runner.prerequisite(root, "build", "A7-15"),
                [{"case": "A7-C0", "sha256": runner.c.sha(path.read_bytes())}],
            )
            receipt["result_sha256"] = "altered"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(runner.c.Refused):
                runner.prerequisite(root, "build", "A7-15")
            stopped = runner.stop(root, "A7-C0", {"stage": "test"})
            self.assertEqual(stopped["results"], {"A7-C0": "FAIL", "A7-15": "NOT RUN"})
            with self.assertRaises(runner.c.Refused):
                runner.prerequisite(root, "build", "A7-C0")
            with self.assertRaises((runner.c.Refused, FileExistsError)):
                runner.stop(root, "A7-C0", {})

    def test_unauthorized_case_role_and_order_fail_before_launch(self):
        with patch.object(
            runner.subprocess, "Popen", side_effect=AssertionError("no native launch")
        ) as launch:
            for sequence, case, role in (
                (1, "other", "probe"),
                (2, "A7-C0", "probe"),
                (1, "A7-C0", "producer"),
            ):
                with self.assertRaises(runner.c.Refused):
                    runner.run_case(Path("x"), Path("x"), Path("x"), sequence, case, role, None)
            launch.assert_not_called()

    def test_full_header_inverse_unique_boundary_and_preprocessed_tokens(self):
        raw = Path(__file__).with_name("suspended-inspection.h").read_bytes()
        generated = instrument.inspector(raw).replace(b"\r\n", b"\n")
        inverse = generated.replace(instrument.BOUNDARY, instrument.ANCHOR)
        self.assertEqual(hashlib.sha256(inverse).hexdigest(), instrument.INSPECTOR_SHA)
        self.assertEqual(
            build_review.inverse_tokens(build_review.tokens(generated.decode())),
            build_review.tokens(raw.decode()),
        )
        for corrupt in (
            raw + b"\n",
            raw.replace(b"a == b, 120", b"true, 120"),
            raw.replace(instrument.ANCHOR, b""),
        ):
            with self.assertRaises(ValueError):
                instrument.inspector(corrupt)
        for corrupt in (
            generated.replace(b"a == b, 120", b"true, 120"),
            generated.replace(
                b"a7::boundary(first);", b"a7::boundary(first); a7::boundary(first);"
            ),
        ):
            try:
                recovered = build_review.inverse_tokens(build_review.tokens(corrupt.decode()))
            except ValueError:
                continue
            self.assertNotEqual(recovered, build_review.tokens(raw.decode()))

    def test_fixture_is_separate_and_shared_policy_not_rewritten(self):
        directory = Path(__file__).parent
        source = (directory / "a7-fixture-mutation.h").read_text(encoding="utf-8")
        self.assertEqual(source.count("&target, SYNCHRONIZE, FALSE, 0)"), 1)
        self.assertNotIn("DUPLICATE_CLOSE_SOURCE", source)
        self.assertNotIn("EVENT_MODIFY_STATE", source)
        self.assertNotIn("ResumeThread", source)
        self.assertNotIn("require(false, 120)", source)
        host = (directory / "a7-fixture-host.cpp").read_text(encoding="utf-8")
        self.assertNotIn("fixtureHandles", host)
        self.assertIn('a3::emit("inheritance_count", 3)', host)
        self.assertIn(
            "[[noreturn]]", (directory / "a7-fixture-inspection.h").read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
