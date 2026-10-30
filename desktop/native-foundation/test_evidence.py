"""Persistence fault injection only; synthetic observations never qualify Windows."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import acceptance as a
import contracts as c
from case_manifest import BAD_INPUTS, CASES, VERIFIER_EXTRA
from evidence import Evidence, EvidenceFailure, FileIO, read_qualified


def synthetic_records(run_id):
    records = []
    for index, (name, role) in enumerate(CASES):
        record = {
            "run_id": run_id,
            "case_id": f"{run_id}:{index:02}:{name}",
            "case": name,
            "role": role,
            "status": "passed",
            "cleanup": "confirmed",
            "attempt_identity_sha256": c.sha(f"attempt-{index}".encode()),
            "package_identity_sha256": c.sha(f"package-{index}".encode()),
            "final_token_checked": True,
            "image_checked": True,
            "ambient_write_denied": True,
            "positive_write_observed": True,
            "host_elevated": 0,
            "host_appcontainer": 0,
            "appcontainer": 1,
            "final_elevated": 0,
            "CreateRestrictedToken_flags": 9,
            "job_at_creation": 1,
            "image_identity_checked": 1,
            "job_limit_flags": 8458,
            "job_process_limit": 1,
            "job_memory_bytes": 134217728,
            "job_cpu_100ns": 20000000,
            "capability_count": 1,
            "child_resumed": 1,
            "invalid_or_duplicate_observations": [],
            "stdout_overflow": False,
            "stderr_overflow": False,
            "parent_deadline_expired": False,
            "child_pid": index + 1,
            "helper_pid": index + 101,
            "creation_time_100ns": index + 1001,
            "stdout": {"complete": True, "sha256": c.sha(b"synthetic")},
            "host_stderr": {"complete": True, "sha256": c.sha(b"synthetic")},
            "helper_exit": 0,
            "active_after_wait": 0,
            "retained_process_handle_signalled": 1,
            "child_exit": 0,
            "termination_reason": 0,
            "termination_latency_ms": 15,
            "job_total_user_time_100ns": 0,
            "peak_process_memory_bytes": 1000,
            "wall_elapsed_ms": 31,
        }
        mode = {"isolation": "sealed", "wall": "hold"}.get(name, name)
        if name.startswith("cancel"):
            mode = "cancel"
            record.update(
                hold_ready=1,
                readiness_ms=15,
                terminate_job_called=4,
                terminate_job_succeeded=1,
                termination_reason=4,
                child_exit=125,
                wall_elapsed_ms=31,
            )
        if "-death-" in name:
            record.update(
                hold_ready=1,
                readiness_ms=15,
                retained_child_handle_signalled=True,
                retained_helper_handle_signalled=True,
                death_latency_ms=20,
            )
        if name.startswith("parent-death-"):
            mode = "hold"
            record.update(
                supervising_parent_exit=1,
                termination_reason=2,
                terminate_job_called=2,
                terminate_job_succeeded=1,
            )
            del record["helper_exit"]
        if name == "wall":
            record["termination_reason"] = 1
        if name == "cpu":
            record["child_exit"] = 0xC0000044
        expected = {
            key: value for key, (_, value) in a.expected_probes(mode).items() if key != "pid"
        }
        record.update(probes=expected, probe_observations=expected, missing_probe_observations=[])
        if name in ("producer", "verifier"):
            record["response"] = {
                "status": "ok",
                "bytes": 7771,
                "sha256": c.EXPECTED,
                "manifest": c.sha(b"synthetic"),
            }
        elif name.startswith(("producer-", "verifier-")):
            status = dict(BAD_INPUTS + VERIFIER_EXTRA)[name.split("-", 1)[1]]
            record["response"] = {"status": status}
            record["child_exit"] = c.FAILURES.index(status)
        if name in ("leak", "overflow", "crash"):
            record["unexpected_output"] = "rejected_without_persistence"
            record["worker_output_rejected"] = 1
        if name == "crash":
            record["child_exit"] = 99
        records.append(record)
    return records


class FaultIO(FileIO):
    def __init__(self):
        self.evidence = None
        self.faults = {}

    def hit(self):
        if self.evidence and self.evidence.stage in self.faults:
            error = self.faults.pop(self.evidence.stage)
            if error == "mismatch":
                return b'{"valid_but_wrong":true}'
            raise error
        return None

    def create(self, path):
        self.hit()
        return super().create(path)

    def write(self, stream, data):
        if self.evidence and self.evidence.stage in self.faults:
            stream.write(data[:11])  # Retained partial artifact; never accepted.
        self.hit()
        return super().write(stream, data)

    def flush(self, stream):
        self.hit()
        return super().flush(stream)

    def sync(self, stream):
        self.hit()
        return super().sync(stream)

    def read(self, path):
        altered = self.hit()
        return altered if altered is not None else super().read(path)

    def replace(self, source, destination):
        self.hit()
        return super().replace(source, destination)

    def remove(self, path):
        self.hit()
        return super().remove(path)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def new(self, name="run"):
        root = self.root / name
        root.mkdir()
        (root / "build-manifest.json").write_bytes(b'{"synthetic":"identity"}')
        io = FaultIO()
        evidence = Evidence(root, io=io)
        io.evidence = evidence
        return evidence, io

    def ready(self, evidence):
        evidence.document["results"] = synthetic_records(evidence.document["run_id"])

    def assert_unqualified(self, evidence):
        with self.assertRaises((c.Refused, OSError)):
            read_qualified(evidence.root, a.validate_final_case)

    def fault(self, phase, *, fallback_failure=False):
        evidence, io = self.new()
        before = (evidence.root / "results.json").read_bytes()
        prior = copy.deepcopy(evidence.last_valid)
        error = PermissionError(13, "PRIVATE PATH MUST NOT APPEAR")
        error.winerror = 32
        io.faults[phase] = error
        if fallback_failure:
            io.faults["failure_write"] = OSError(28, "PRIVATE PATH SECOND ERROR")
        with self.assertRaises(EvidenceFailure) as caught:
            evidence.begin("producer", "producer")
        report = caught.exception.report
        self.assertEqual(
            report["error"], {"kind": "filesystem", "errno": 13, "winerror": 32, "code": None}
        )
        self.assertEqual(report["stage"], phase)
        self.assertEqual(report["evidence_retained"], not fallback_failure)
        self.assertNotIn("PRIVATE", json.dumps(report))
        checkpoint = (
            evidence.folder
            / f"checkpoint-{evidence.document['run_id']}-{prior['sequence']:06}.json"
        )
        self.assertEqual(checkpoint.read_bytes(), before)
        self.assertEqual((evidence.root / "results.json").read_bytes(), before)
        self.assertFalse(evidence.document["qualified"])
        self.assert_unqualified(evidence)
        return evidence, report

    def test_temporary_create_failure(self):
        self.fault("checkpoint_temporary_create")

    def test_interrupted_partial_write(self):
        evidence, _ = self.fault("checkpoint_temporary_write")
        pending = next(evidence.folder.glob("*.pending"))
        self.assertEqual(len(pending.read_bytes()), 11)

    def test_flush_failure(self):
        self.fault("checkpoint_temporary_flush")

    def test_fsync_failure(self):
        self.fault("checkpoint_temporary_fsync")

    def test_checkpoint_atomic_replacement_failure(self):
        self.fault("checkpoint_replace")

    def test_locked_or_inaccessible_results_destination(self):
        self.fault("results_replace")

    def test_failure_during_failure_retention(self):
        evidence, report = self.fault("results_replace", fallback_failure=True)
        self.assertEqual(report["failure_record_error"]["errno"], 28)
        self.assertTrue(list(evidence.folder.glob("failure-*.json")))
        self.assert_unqualified(evidence)

    def test_existing_pending_cannot_block_failure_record(self):
        evidence, io = self.new()
        historical = evidence.root / "results.pending"
        historical.write_bytes(b"untouched historical bytes")
        io.faults["results_replace"] = OSError(13, "private")
        with self.assertRaises(EvidenceFailure) as caught:
            evidence.begin("producer", "producer")
        self.assertTrue(caught.exception.report["evidence_retained"])
        self.assertEqual(historical.read_bytes(), b"untouched historical bytes")
        self.assert_unqualified(evidence)

    def test_historical_root_is_never_resumed(self):
        evidence, _ = self.new()
        before = (evidence.root / "results.json").read_bytes()
        (evidence.root / "results.pending").write_bytes(b"original pending")
        with self.assertRaises(c.Refused):
            Evidence(evidence.root)
        self.assertEqual((evidence.root / "results.json").read_bytes(), before)
        self.assertEqual((evidence.root / "results.pending").read_bytes(), b"original pending")

    def test_second_writer_cannot_claim_same_directory(self):
        evidence, _ = self.new()
        with self.assertRaises(c.Refused):
            Evidence(evidence.root)

    def test_case_begin_enforces_fixed_order_and_unconfirmed_state(self):
        evidence, _ = self.new()
        with self.assertRaises(c.Refused):
            evidence.begin("cancel", "probe")
        record = evidence.begin("producer", "producer")
        self.assertEqual(record["status"], "unconfirmed")
        with self.assertRaises(c.Refused):
            evidence.begin("producer", "producer")

    def test_missing_duplicate_unconfirmed_failed_and_foreign_cases(self):
        for kind in (
            "missing",
            "duplicate",
            "unconfirmed",
            "failed",
            "foreign",
            "role",
            "shared_identity",
        ):
            with self.subTest(kind=kind):
                evidence, _ = self.new(kind)
                self.ready(evidence)
                rows = evidence.records
                if kind == "missing":
                    rows.pop()
                elif kind == "duplicate":
                    rows[-1] = rows[-2].copy()
                elif kind in ("unconfirmed", "failed"):
                    rows[-1]["status"] = kind
                elif kind == "foreign":
                    rows[-1]["run_id"] = "0" * 32
                elif kind == "role":
                    rows[-1]["role"] = "producer"
                else:
                    rows[-1]["attempt_identity_sha256"] = rows[-2]["attempt_identity_sha256"]
                with self.assertRaises(EvidenceFailure):
                    evidence.qualify(a.validate_final_case)
                self.assert_unqualified(evidence)

    def test_missing_process_cleanup_and_probe_observations(self):
        for field in (
            "cleanup",
            "retained_child_handle_signalled",
            "terminate_job_succeeded",
            "probe_observations",
        ):
            with self.subTest(field=field):
                evidence, _ = self.new(field)
                self.ready(evidence)
                del evidence.records[-1][field]
                with self.assertRaises(EvidenceFailure):
                    evidence.qualify(a.validate_final_case)
                self.assert_unqualified(evidence)

    def test_readback_mismatch_after_replace_keeps_old_checkpoint(self):
        evidence, io = self.new()
        previous = evidence.last_valid.copy()
        io.faults["results_readback"] = "mismatch"
        with self.assertRaises(EvidenceFailure) as caught:
            evidence.begin("producer", "producer")
        self.assertTrue(caught.exception.report["evidence_retained"])
        checkpoint = (
            evidence.folder
            / f"checkpoint-{evidence.document['run_id']}-{previous['sequence']:06}.json"
        )
        self.assertEqual(c.sha(checkpoint.read_bytes()), previous["sha256"])
        self.assert_unqualified(evidence)

    def test_interrupted_final_qualification_never_passes(self):
        for stage in (
            "results_replace",
            "results_readback",
            "completion_replace",
            "completion_readback",
            "active_remove",
        ):
            with self.subTest(stage=stage):
                evidence, io = self.new(stage)
                self.ready(evidence)
                io.faults[stage] = KeyboardInterrupt()
                with self.assertRaises(KeyboardInterrupt):
                    evidence.qualify(a.validate_final_case)
                self.assertTrue((evidence.folder / "run.active").exists())
                self.assert_unqualified(evidence)
                with self.assertRaises(c.Refused):
                    Evidence(evidence.root)

    def test_readback_failure_of_final_qualified_result(self):
        evidence, io = self.new()
        self.ready(evidence)
        io.faults["results_readback"] = "mismatch"
        with self.assertRaises(EvidenceFailure):
            evidence.qualify(a.validate_final_case)
        self.assert_unqualified(evidence)

    def test_corrupt_truncated_duplicate_keys_and_conflicting_receipt(self):
        for kind in ("corrupt", "truncated", "duplicate_key", "receipt", "checkpoint"):
            with self.subTest(kind=kind):
                evidence, _ = self.new(kind)
                self.ready(evidence)
                evidence.qualify(a.validate_final_case)
                read_qualified(evidence.root, a.validate_final_case)
                path = evidence.root / "results.json"
                if kind == "receipt":
                    path = evidence.folder / "completion.json"
                    path.write_bytes(b'{"run_id":"wrong"}')
                elif kind == "checkpoint":
                    path = (
                        evidence.folder
                        / f"checkpoint-{evidence.document['run_id']}-{evidence.sequence:06}.json"
                    )
                    path.write_bytes(b"{}")
                else:
                    data = {
                        "corrupt": b"not-json",
                        "truncated": path.read_bytes()[:100],
                        "duplicate_key": b'{"qualified":false,"qualified":true}',
                    }[kind]
                    path.write_bytes(data)
                self.assert_unqualified(evidence)

    def test_successful_independent_run_does_not_repair_failed_run(self):
        failed, io = self.new("failed")
        io.faults["results_replace"] = OSError(13, "private")
        with self.assertRaises(EvidenceFailure):
            failed.begin("producer", "producer")
        original = (failed.root / "results.json").read_bytes()
        successful, _ = self.new("successful")
        self.ready(successful)
        successful.qualify(a.validate_final_case)
        document, receipt = read_qualified(successful.root, a.validate_final_case)
        self.assertTrue(document["qualified"])
        self.assertEqual(len(document["results"]), 55)
        self.assertTrue(receipt["readback_verified"])
        self.assertEqual(receipt["retries"], 0)
        self.assertNotEqual(failed.document["run_id"], document["run_id"])
        self.assertEqual((failed.root / "results.json").read_bytes(), original)
        self.assert_unqualified(failed)


if __name__ == "__main__":
    unittest.main()
