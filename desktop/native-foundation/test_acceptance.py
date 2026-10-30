"""Portable evidence-retention tests, not simulated Windows access decisions."""

import json
import tempfile
import unittest
from pathlib import Path

import acceptance as a
import contracts as c
from evidence import Evidence, EvidenceFailure, StreamHash, observed


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "build-manifest.json").write_bytes(b'{"test":"identity"}')

    def test_failed_case_persisted_before_assertion(self):
        evidence = Evidence(self.root)
        record = evidence.begin("producer", "producer")
        observed(
            record,
            [
                {"native": "termination_reason", "value": 1},
                {"native": "wall_elapsed_ms", "value": 10016},
                {"native": "termination_latency_ms", "value": 16},
            ],
        )
        record["cleanup"] = "confirmed"
        try:
            a.cancellation(record)
        except c.Refused as error:
            with self.assertRaises(EvidenceFailure):
                evidence.failed(str(error))
        saved = json.loads(next((self.root / "evidence").glob("failure-*.json")).read_bytes())[
            "snapshot"
        ]
        self.assertFalse(saved["qualified"])
        failed = saved["results"][0]
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["termination_reason"], 1)
        self.assertEqual(failed["termination_latency_ms"], 16)
        self.assertEqual(failed["cleanup"], "confirmed")
        self.assertIn("hold_ready", failed["missing_observations"])
        self.assertIn("build_manifest_sha256", saved)
        self.assertIn("runner_source_sha256", saved)

    def test_unconfirmed_case_survives_interruption(self):
        evidence = Evidence(self.root)
        evidence.begin("producer", "producer")
        saved = json.loads((self.root / "results.json").read_bytes())
        self.assertEqual(saved["results"][0]["status"], "unconfirmed")
        self.assertEqual(saved["results"][0]["cleanup"], "unconfirmed")
        self.assertFalse(saved["qualified"])

    def test_cleanup_cannot_be_assumed(self):
        evidence = Evidence(self.root)
        record = evidence.begin("producer", "producer")
        with self.assertRaises(c.Refused):
            evidence.passed(record, a.validate_final_case)

    def test_unknown_observation_text_is_not_persisted(self):
        evidence = Evidence(self.root)
        record = evidence.begin("producer", "producer")
        observed(
            record,
            [
                {"native": "SYNTHETIC_SECRET", "value": 1},
                {"native": "child_exit", "value": "SYNTHETIC_SECRET"},
            ],
        )
        with self.assertRaises(EvidenceFailure):
            evidence.failed("host_records_invalid")
        saved = next((self.root / "evidence").glob("failure-*.json")).read_bytes()
        self.assertNotIn(b"SYNTHETIC_SECRET", saved)
        self.assertIn("child_exit", record["invalid_or_duplicate_observations"])

    def test_raw_stream_hash_without_persisting_raw_output(self):
        stream = StreamHash()
        stream.update(b"SYNTHETIC_")
        stream.update(b"SECRET")
        summary = stream.result(False)
        self.assertEqual(summary["sha256"], c.sha(b"SYNTHETIC_SECRET"))
        self.assertEqual(summary["bytes"], 16)
        self.assertFalse(summary["complete"])
        self.assertNotIn("SYNTHETIC_SECRET", json.dumps(summary))

    def test_cancellation_requires_api_reason_and_handle(self):
        valid = {
            "hold_ready": 1,
            "readiness_ms": 15,
            "termination_reason": 4,
            "terminate_job_called": 4,
            "terminate_job_succeeded": 1,
            "retained_process_handle_signalled": 1,
            "active_after_wait": 0,
            "child_exit": 125,
            "wall_elapsed_ms": 31,
            "termination_latency_ms": 16,
        }
        a.cancellation(valid)
        for key in valid:
            with self.subTest(missing=key), self.assertRaises(c.Refused):
                a.cancellation({k: v for k, v in valid.items() if k != key})
        for key, value in (
            ("termination_reason", 1),
            ("terminate_job_called", 1),
            ("hold_ready", 0),
            ("terminate_job_succeeded", 0),
            ("retained_process_handle_signalled", 0),
            ("active_after_wait", 1),
            ("wall_elapsed_ms", 10000),
        ):
            with self.subTest(key=key), self.assertRaises(c.Refused):
                a.cancellation({**valid, key: value})


if __name__ == "__main__":
    unittest.main()
