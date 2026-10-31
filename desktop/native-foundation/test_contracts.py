"""Portable contract tests; these do not qualify Windows process isolation."""

import base64
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import contracts as c  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = subprocess.check_output(["git", "show", "HEAD:" + c.TARGET], cwd=ROOT)
        cls.spec = c.load((Path(__file__).parent / "replacement.json").read_bytes())
        cls.old, cls.new, cls.candidate = c.specification(cls.spec, cls.source)

    def test_exact_source_and_candidate(self):
        self.assertEqual((len(self.source), len(self.candidate)), (7594, 7771))
        self.assertEqual(c.sha(self.candidate), c.EXPECTED)

    def test_complete_github_plan_and_snapshot(self):
        from daf.planning_snapshot import make_snapshot, validate_snapshot

        raw = subprocess.check_output(["git", "show", "HEAD:" + c.PLAN_PATH], cwd=ROOT)
        self.assertEqual(c.sha(raw), c.PLAN_DIGEST)
        snapshot = make_snapshot(
            {"repository": c.REPOSITORY, "commit_sha": c.PLAN_COMMIT, "path": c.PLAN_PATH}, raw
        )
        self.assertEqual(validate_snapshot(snapshot), snapshot)
        self.assertFalse(snapshot["execution_authority"])

    def test_unknown_spec_field(self):
        with self.assertRaises(c.Refused):
            c.specification({**self.spec, "approved": True}, self.source)

    def test_wrong_spec_version(self):
        with self.assertRaises(c.Refused):
            c.specification({**self.spec, "schema": "daf-local-replacement/v2"}, self.source)

    def test_wrong_path_and_digests(self):
        for field, value in (
            ("path", "../SECURITY.md"),
            ("beforeSha256", "0" * 64),
            ("expectedAfterSha256", "0" * 64),
        ):
            with self.subTest(field=field), self.assertRaises(c.Refused):
                c.specification({**self.spec, field: value}, self.source)

    def test_unknown_manifest_and_version(self):
        with self.assertRaises(c.Refused):
            c.prepare({"schema": "daf-preparation/v2", "approved": True}, b"", b"", {})

    def test_missing_duplicate_and_changed_source(self):
        for source in (
            self.source.replace(self.old, b""),
            self.source + self.old,
            b"X" + self.source[1:],
        ):
            with self.subTest(size=len(source)), self.assertRaises(c.Refused):
                c.specification(self.spec, source)

    def test_utf8_and_nul(self):
        for raw in (b"\0", b"\xff", b"\xc0\x80", b"\xed\xa0\x80", b"\xf4\x90\x80\x80", b"\xc3"):
            with self.subTest(raw=raw), self.assertRaises(c.Refused):
                c.text_bytes(raw, 65536)

    def test_file_and_block_bounds(self):
        for size in (65537, 262145):
            with self.assertRaises(c.Refused):
                c.text_bytes(b"x" * size, 65536)
        with self.assertRaises(c.Refused):
            c.block(base64.b64encode(b"x" * 8193).decode())

    def test_noncanonical_base64(self):
        for value in ("eA==\n", "eB==", "x", 1, ""):
            with self.subTest(value=value), self.assertRaises(c.Refused):
                c.block(value)

    def test_closed_json_parser(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b"\xff", b"{" * 2000):
            with self.subTest(size=len(raw)), self.assertRaises(c.Refused):
                c.load(raw)
        with self.assertRaises(c.Refused):
            c.load(b" " * 262145)

    def test_binary_contract(self):
        valid = {
            "schema": "daf-native-build/v1",
            "adapter": "literal-markdown-v1",
            "role": "producer",
            "sha256": "1" * 64,
            "bytes": 1000,
        }
        c.binary(valid, "producer")
        for field, value in (
            ("role", "verifier"),
            ("bytes", True),
            ("bytes", 1048577),
            ("sha256", "A" * 64),
            ("schema", "v2"),
            ("command", "cmd.exe"),
        ):
            changed = copy.deepcopy(valid)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(c.Refused):
                c.binary(changed, "producer")

    def frame(self, role=1, **changes):
        values = dict(
            magic=b"DAFO21A1",
            version=1,
            role=role,
            status=0,
            size=7771,
            manifest=bytes.fromhex("1" * 64),
            digest=bytes.fromhex(c.EXPECTED),
        )
        values.update(changes)
        return c.RESPONSE.pack(*values.values())

    def test_producer_response_exact_bytes(self):
        result, candidate = c.response(self.frame() + self.candidate, 1, "1" * 64)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(candidate, self.candidate)

    def test_verifier_response_binds_candidate(self):
        result, candidate = c.response(self.frame(role=2), 2, "1" * 64, self.candidate)
        self.assertEqual(result["sha256"], c.EXPECTED)
        self.assertIsNone(candidate)
        with self.assertRaises(c.Refused):
            c.response(self.frame(role=2), 2, "1" * 64, b"X" + self.candidate[1:])

    def test_forged_success_and_diagnostic_output(self):
        for raw in (
            b'{"success":true}',
            b"SYNTHETIC_SECRET",
            self.frame(status=99),
            self.frame(version=2) + self.candidate,
            self.frame(manifest=bytes(32)) + self.candidate,
            self.frame(digest=bytes(32)) + self.candidate,
        ):
            with self.subTest(size=len(raw)), self.assertRaises(c.Refused):
                c.response(raw, 1, "1" * 64)

    def test_extra_missing_and_altered_output(self):
        for candidate in (self.candidate[:-1], self.candidate + b"x", b"X" + self.candidate[1:]):
            with self.subTest(size=len(candidate)), self.assertRaises(c.Refused):
                c.response(self.frame() + candidate, 1, "1" * 64)
        with self.assertRaises(c.Refused):
            c.response(self.frame(role=2) + b"unexpected", 2, "1" * 64, self.candidate)

    def test_failure_has_no_worker_text_or_bindings(self):
        raw = self.frame(status=1, size=0, manifest=bytes(32), digest=bytes(32))
        self.assertEqual(c.response(raw, 1, "1" * 64), ({"status": "frame"}, None))
        for bad in (raw + b"secret", self.frame(status=1)):
            with self.assertRaises(c.Refused):
                c.response(bad, 1, "1" * 64)

    def test_manifest_immutable_bytes(self):
        prepared = c.Preparation(c.canonical({"test": 1}))
        original = prepared.digest
        decoded = json.loads(prepared.encoded)
        decoded["test"] = 2
        self.assertEqual(prepared.digest, original)


if __name__ == "__main__":
    unittest.main()
