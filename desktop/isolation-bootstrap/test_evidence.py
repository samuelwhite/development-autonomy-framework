"""Portable checks for fail-closed diagnostic evidence handling; no worker launch."""

import json
import tempfile
import unittest
from pathlib import Path

import run


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        owned = Path(__file__).resolve().parents[2] / "dist" / "bootstrap-evidence-tests"
        owned.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=owned)
        assert Path(self.temp.name).resolve().is_relative_to(owned.resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.attempt = self.root / "attempt"
        self.attempt.mkdir()
        for folder in (self.root, self.attempt):
            (folder / "ambient-shared.txt").write_bytes(b"synthetic fixture")
        (self.attempt / "child.jsonl").write_text("")
        (self.attempt / "native.log").write_text("")

    def test_changed_bytes_stop_even_without_success_log(self):
        (self.attempt / "ambient-shared.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "BLOCKING ambient write"):
            run.ambient_guard(self.root, self.attempt)

    def test_native_success_stops_even_if_bytes_restored(self):
        (self.attempt / "native.log").write_text(
            json.dumps({"native": "native_ambient_write", "allowed": True})
        )
        with self.assertRaisesRegex(RuntimeError, "BLOCKING ambient write"):
            run.ambient_guard(self.root, self.attempt)

    def test_child_failure_signal_stops(self):
        (self.attempt / "child.jsonl").write_text(
            json.dumps({"probe": "BLOCKING_ambient_write", "status": "failure"})
        )
        with self.assertRaisesRegex(RuntimeError, "BLOCKING ambient write"):
            run.ambient_guard(self.root, self.attempt)

    def test_missing_completion_is_not_a_pass(self):
        with self.assertRaises(RuntimeError):
            run.value([], "probe", "native_suite_complete", "code")

    def test_duplicate_completion_is_refused(self):
        row = {"probe": "native_suite_complete", "code": 0}
        with self.assertRaises(RuntimeError):
            run.value([row, row], "probe", "native_suite_complete", "code")

    def test_malformed_json_is_refused(self):
        (self.attempt / "native.log").write_text('{"native":')
        with self.assertRaises(json.JSONDecodeError):
            run.rows(self.attempt / "native.log")


if __name__ == "__main__":
    unittest.main()
