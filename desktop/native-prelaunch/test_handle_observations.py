"""Portable adversarial evidence tests. These never launch native code."""

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import handle_observations as d
import qualify


def fixture(pipe=False):
    host = {
        "a1_attribute_mask": 31,
        "a1_attribute_count": 5,
        "a1_inheritance_count": 3,
        "hostile_handles_inheritable": 5,
        "a1_suspended_handle_audit_complete": 1,
        "a1_control_effects_verified_and_restored": 1,
        "a1_hostile_event_after_child": 258,
        "child_pid": 900,
        "a1_suspended_child_pid": 900,
        "a1_standard_0": 100,
        "a1_standard_1": 104,
        "a1_standard_2": 108,
    }
    values = {
        "schema": 2,
        "pid": 900,
        "stdin_raw": 100,
        "stdout_raw": 104,
        "stderr_raw": 108,
        "stdin_pipe": 1,
        "stdout_pipe": 1,
        "stderr_pipe": 1,
        "bindings_complete": 1,
        "probe_complete": 1,
    }
    for i, kind in enumerate((1, 1, 2, 3, 4)):
        raw = 400 + i * 4
        control = {
            "begin": 1,
            "raw": raw,
            "info_ok": 1,
            "info_error": 0,
            "flags": 1,
            "before_duplicate": 1,
            "duplicate_ok": 1,
            "duplicate_error": 0,
            "before_metadata": 1,
            "type_status": 0,
            "type": kind,
            "standard_mask": 0,
            "known_reference": 1,
            "intended_identity": 1,
            "before_operation": 1,
            "operation_attempted": 1,
            "operation_ok": 1,
            "operation_error": 0,
            "outcome": 3,
            "complete": 1,
        }
        host.update({f"a1_control_h{i}_{key}": v for key, v in control.items()})
        audit = {"raw": raw, "valid": 0, "error": 6, "hostile_mask": 0, "standard_mask": 0}
        host.update({f"a1_audit_h{i}_{key}": v for key, v in audit.items()})
        child = {
            "binding": raw,
            "raw": raw,
            "begin": 1,
            "info_ok": 0,
            "info_error": 6,
            "flags": 0,
            "before_duplicate": 1,
            "duplicate_ok": 0,
            "duplicate_error": 6,
            "operation_attempted": 0,
            "operation_ok": 0,
            "operation_error": 0,
            "operation_bytes": 0,
            "outcome": 1,
            "complete": 1,
        }
        if pipe:
            child.update(
                {
                    "info_ok": 1,
                    "info_error": 0,
                    "duplicate_ok": 1,
                    "duplicate_error": 0,
                    "before_metadata": 1,
                    "type_status": 0,
                    "type": 1,
                    "file_type": 3,
                    "file_type_error": 0,
                    "standard_mask": 1,
                    "known_reference": 0,
                    "intended_identity": 0,
                    "outcome": 2,
                }
            )
        values.update({f"h{i}_{key}": v for key, v in child.items()})
    host.update(
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
    return values, [{"native": key, "value": value} for key, value in host.items()]


class EvidenceTests(unittest.TestCase):
    def test_complete_identity_findings_are_not_io_denial_claims(self):
        for pipe in (False, True):
            with self.subTest(pipe=pipe):
                values, host = fixture(pipe)
                result = d.validate(values, host)
                self.assertEqual(len(result), 5)
                self.assertTrue(all(not r["io_denial_claim"] for r in result))
                self.assertTrue(all(not r["resource_operation_attempted"] for r in result))

    def test_each_missing_child_observation_fails(self):
        for pipe in (False, True):
            values, host = fixture(pipe)
            required = set(values)
            for key in required:
                with self.subTest(pipe=pipe, key=key):
                    altered = dict(values)
                    del altered[key]
                    with self.assertRaises(d.InvalidObservation):
                        d.validate(altered, host)

    def test_each_missing_host_observation_fails(self):
        values, host = fixture()
        for index, row in enumerate(host):
            with self.subTest(key=row["native"]):
                with self.assertRaises(d.InvalidObservation):
                    d.validate(values, host[:index] + host[index + 1 :])

    def test_real_access_denied_expected_object_and_ambiguity_are_not_passes(self):
        for resource in range(5):
            for outcome in (0, 3, 4, 5, 6):
                with self.subTest(resource=resource, outcome=outcome):
                    values, host = fixture()
                    values[f"h{resource}_outcome"] = outcome
                    with self.assertRaises(d.InvalidObservation):
                        d.validate(values, host)

    def test_any_host_detected_inherited_object_is_fatal(self):
        for resource in range(5):
            for hostile in range(5):
                values, host = fixture()
                next(r for r in host if r["native"] == f"a1_audit_h{resource}_hostile_mask")[
                    "value"
                ] = 1 << hostile
                with self.subTest(resource=resource, hostile=hostile):
                    with self.assertRaises(d.InvalidObservation):
                        d.validate(values, host)

    def test_controls_must_actually_access_all_five_resources(self):
        for resource in range(5):
            for field in (
                "operation_attempted",
                "operation_ok",
                "intended_identity",
                "known_reference",
                "complete",
            ):
                values, host = fixture()
                next(r for r in host if r["native"] == f"a1_control_h{resource}_{field}")[
                    "value"
                ] = 0
                with self.subTest(resource=resource, field=field):
                    with self.assertRaises(d.InvalidObservation):
                        d.validate(values, host)

    def test_unknown_pipe_wrong_type_and_operation_suppression_fail(self):
        for key, value in {
            "h0_standard_mask": 0,
            "h0_type": 2,
            "h0_file_type": 1,
            "h0_intended_identity": 1,
            "h0_operation_attempted": 1,
            "h0_before_operation": 1,
        }.items():
            values, host = fixture(True)
            values[key] = value
            with self.subTest(key=key):
                with self.assertRaises(d.InvalidObservation):
                    d.validate(values, host)

    def test_wrong_bindings_and_synthetic_event_modification_fail(self):
        values, host = fixture()
        for key in ("h0_raw", "h0_binding", "stdin_raw", "pid", "schema"):
            altered = dict(values)
            altered[key] += 4
            with self.subTest(key=key):
                with self.assertRaises(d.InvalidObservation):
                    d.validate(altered, host)
        altered = copy.deepcopy(host)
        next(r for r in altered if r["native"] == "a1_hostile_event_after_child")["value"] = 0
        with self.assertRaises(d.InvalidObservation):
            d.validate(values, altered)

    def test_bounded_numeric_progress_parsing(self):
        values, _ = fixture()
        raw = b"".join(
            json.dumps({"probe": k, "value": v}).encode() + b"\n" for k, v in values.items()
        )
        self.assertEqual(d.parse(raw), values)
        self.assertEqual(
            d.parse(b'{"probe":"h0_before_duplicate","value":1}\n'), {"h0_before_duplicate": 1}
        )
        for raw in (
            b"x" * 65625,
            b"x" * 193,
            b"{",
            b"{}",
            b"[]",
            b'{"probe":"pid","value":true}',
            b'{"probe":"pid","value":-1}',
            b'{"probe":"pid","value":18446744073709551616}',
            b'{"probe":"pid","value":1,"value":2}',
            b'{"probe":"private_path","value":1}',
            b'{"probe":"pid","value":1}\n' * 2,
        ):
            with self.subTest(raw=raw[:80]):
                with self.assertRaises(d.InvalidObservation):
                    d.parse(raw)

    def test_duplicates_and_noninteger_host_evidence_rejected(self):
        values, host = fixture()
        for rows in (host + [host[0]], [{**host[0], "value": True}] + host[1:]):
            with self.assertRaises(d.InvalidObservation):
                d.validate(values, rows)

    def test_native_other_cases_cannot_reach_launch(self):
        self.assertEqual(qualify.CASES, (("handles", "probe", None),))
        self.assertEqual(len(qualify.HISTORICAL_CASES), 20)
        with patch.object(qualify.subprocess, "Popen") as launch:
            for case, role, refusal in qualify.HISTORICAL_CASES[1:]:
                with self.assertRaises(qualify.c.Refused):
                    qualify.run_case(
                        Path("unused"), Path("unused"), Path("unused"), 1, case, role, refusal
                    )
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
