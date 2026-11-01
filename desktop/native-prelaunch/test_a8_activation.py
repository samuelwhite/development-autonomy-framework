"""Shared A8 entry sequence with explicit fakes only; no native claims or launch."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import a8_qualify as runner
import a8_verify as verifier
from test_a8 import collected, fixture


class FakeExecution:
    """Synthetic effects; no process API and no native-mode override."""

    mode = "simulated"

    def __init__(self, root):
        self.repo = root
        (root / "dist").mkdir()
        self.build, self.workers, self.output = [
            root / "dist" / p for p in ("build", "workers", "out")
        ]
        self.build.mkdir()
        self.workers.mkdir()
        self.source = root / "synthetic-source.txt"
        self.source.write_bytes(b"frozen synthetic source")
        self.source_hash = runner.c.sha(self.source.read_bytes())
        self.build_hash = "b" * 64
        self.checks = 0
        self.calls = []
        self.change_on_recheck = False
        self.failure = False

    def check(self, build, workers):
        self.checks += 1
        runner.c.require((build, workers) == (self.build, self.workers), "fake_paths")
        if self.change_on_recheck and self.checks == 2:
            self.source.write_bytes(b"changed during claiming")
        runner.c.require(runner.c.sha(self.source.read_bytes()) == self.source_hash, "fake_source")
        return self.build_hash, self.source_hash

    def collect(self, staged, output, build, workers, case):
        self.calls.append(case)  # Models a runner invocation, never a process launch.
        if self.failure:
            raise OSError("synthetic failure before process creation")
        staged.update(collected(fixture(case)))

    def enter(self, case):
        return runner.exercise_entry(case, self.build, self.workers, self.output, self)

    def readback(self, case):
        return verifier.verify(self.output, case, lambda: fixture(case)["independent_cleanup"])


class A8Activation(unittest.TestCase):
    def test_same_entry_sequence_c0_receipt_then_s1_and_distinct_process_count_meaning(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeExecution(Path(directory).resolve())
            for case in runner.NAMES:
                result = fake.enter(case)
                self.assertEqual(result["status"], "expected_control_observed", result)
                receipt = fake.readback(case)
                self.assertEqual(receipt["schema"], "daf-a8-independent/v2")
                self.assertEqual(receipt["independent_readback_processes_launched"], 0)
                self.assertNotIn("native_processes_launched", receipt)
                self.assertEqual(result["exercise"], receipt["exercise"])
                self.assertEqual(receipt["mode"], "simulated")
                self.assertFalse(receipt["execution_authority"])
                self.assertFalse(receipt["qualified"])
                self.assertEqual(fake.calls[-1], case)
            self.assertEqual(fake.calls, list(runner.NAMES))
            # Two simulated runner calls; readback launched zero additional processes.
            self.assertEqual(len(fake.calls), 2)
            self.assertEqual(
                list((fake.repo / "dist").glob("m21b-a8-A8-*-execution-claimed.json")), []
            )

    def test_native_release_is_closed_before_effects_or_claims_without_gate_patching(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for case in runner.NAMES:
                with self.assertRaises(PermissionError):
                    runner.native_entry(case, root, root, root)
                with self.assertRaises(PermissionError):
                    runner.require_native_release(case)
            for case in ("A8-C1", "A8-S0", "A7-C0", "../A8-C0", "", None):
                with self.assertRaises(runner.c.Refused):
                    runner.native_entry(case, root, root, root)
            self.assertEqual(list(root.iterdir()), [])
            self.assertIs(runner.NATIVE_BUDGET_RELEASED, False)

    def test_case_source_and_path_failures_before_any_claim_or_fake_invocation(self):
        for kind in ("case", "source", "relative", "alias", "nested", "build", "mode"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                fake = FakeExecution(Path(directory).resolve())
                case = "A8-C0"
                if kind == "case":
                    case = "A8-S2"
                elif kind == "source":
                    fake.source.write_bytes(b"unexpected source")
                elif kind == "relative":
                    fake.output = Path("relative")
                elif kind == "alias":
                    fake.output = fake.build
                elif kind == "nested":
                    fake.output = fake.build / "nested"
                elif kind == "build":
                    fake.build_hash = "unbound"
                elif kind == "mode":
                    fake.mode = "native"
                with self.assertRaises((runner.c.Refused, PermissionError)):
                    fake.enter(case)
                self.assertEqual(fake.calls, [])
                self.assertEqual(list((fake.repo / "dist").glob("*-claimed.json")), [])

    def test_source_change_after_claim_stops_before_collector_and_cannot_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeExecution(Path(directory).resolve())
            fake.change_on_recheck = True
            with self.assertRaises(runner.c.Refused):
                fake.enter("A8-C0")
            self.assertEqual(fake.calls, [])
            self.assertTrue((fake.output / "STOP.json").exists())
            fake.source.write_bytes(b"frozen synthetic source")
            for case in runner.NAMES:
                with self.assertRaises(runner.c.Refused):
                    fake.enter(case)

    def test_s1_missing_receipt_or_other_exercise_build_source_never_invokes_collector(self):
        for kind in ("no_c0", "no_receipt", "other_output", "build", "source", "global_claim"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                fake = FakeExecution(Path(directory).resolve())
                if kind != "no_c0":
                    fake.enter("A8-C0")
                    if kind != "no_receipt":
                        fake.readback("A8-C0")
                if kind == "other_output":
                    fake.output = fake.output.with_name("other")
                elif kind == "build":
                    fake.build_hash = "c" * 64
                elif kind == "source":
                    fake.source.write_bytes(b"another frozen source")
                    fake.source_hash = runner.c.sha(fake.source.read_bytes())
                elif kind == "global_claim":
                    (fake.repo / "dist/m21b-a8-simulated-A8-C0-execution-claimed.json").unlink()
                with self.assertRaises((runner.c.Refused, FileNotFoundError)):
                    fake.enter("A8-S1")
                self.assertNotIn("A8-S1", fake.calls)

    def test_failed_forged_or_legacy_receipts_and_changed_raw_evidence_are_refused(self):
        for kind in ("verified", "count", "legacy", "mode", "exercise", "result", "raw", "started"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                fake = FakeExecution(Path(directory).resolve())
                fake.enter("A8-C0")
                fake.readback("A8-C0")
                path = fake.output / "A8-C0-independent.json"
                value = json.loads(path.read_bytes())
                if kind == "verified":
                    value["independently_verified"] = False
                elif kind == "count":
                    value["independent_readback_processes_launched"] = 1
                elif kind == "legacy":
                    value["schema"] = "daf-a8-independent/v1"
                    value["native_processes_launched"] = value.pop(
                        "independent_readback_processes_launched"
                    )
                elif kind == "mode":
                    value["mode"] = "native"
                elif kind == "exercise":
                    value["exercise"]["output"] = "dist/other"
                elif kind == "result":
                    value["result_sha256"] = "0" * 64
                elif kind == "raw":
                    (fake.output / "A8-C0-stderr.jsonl").write_bytes(b"changed")
                elif kind == "started":
                    (fake.output / "A8-C0-started.json").write_text("{}")
                path.write_text(json.dumps(value))
                with self.assertRaises(runner.c.Refused):
                    fake.enter("A8-S1")
                self.assertEqual(fake.calls, ["A8-C0"])
                self.assertTrue((fake.output / "STOP.json").exists())

    def test_duplicate_case_global_claim_and_failed_readback_stop_are_irreversible(self):
        for kind in ("duplicate", "global", "cleanup", "collector"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                fake = FakeExecution(Path(directory).resolve())
                fake.failure = kind == "collector"
                fake.enter("A8-C0")
                if kind == "cleanup":
                    cleanup = copy.deepcopy(fixture()["independent_cleanup"])
                    cleanup["profile_absent"] = False
                    with self.assertRaises(ValueError):
                        verifier.verify(fake.output, "A8-C0", lambda value=cleanup: value)
                elif kind != "collector":
                    fake.readback("A8-C0")
                if kind == "global":
                    runner.publish(
                        fake.repo / "dist/m21b-a8-simulated-A8-S1-execution-claimed.json", {}
                    )
                cases = ("A8-C0",) if kind == "duplicate" else runner.NAMES
                for case in cases:
                    with self.assertRaises(runner.c.Refused):
                        fake.enter(case)
                self.assertEqual(fake.calls, ["A8-C0"])
                if kind in ("cleanup", "collector"):
                    before = (fake.output / "STOP.json").read_bytes()
                    runner.stop(fake.output, "A8-S1", {}, "simulated")
                    self.assertEqual(before, (fake.output / "STOP.json").read_bytes())

    def test_complete_frozen_source_inventory_and_bytes_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve()
            build = repo / "dist/build"
            files = {}
            for folder in ("native-prelaunch", "native-foundation"):
                source = repo / "desktop" / folder / "synthetic.py"
                frozen = build / "source" / folder / "synthetic.py"
                for path in (source, frozen):
                    path.parent.mkdir(parents=True)
                    path.write_bytes(b"exact source")
                files[f"source/{folder}/synthetic.py"] = {
                    "bytes": 12,
                    "sha256": runner.c.sha(b"exact source"),
                }
            manifest = {"files": files}
            runner.verify_frozen_sources(build, repo, manifest)
            for kind in ("missing", "extra", "identity", "changed"):
                wrong = copy.deepcopy(manifest)
                key = next(iter(files))
                if kind == "missing":
                    del wrong["files"][key]
                elif kind == "extra":
                    wrong["files"]["source/unreviewed.py"] = {}
                elif kind == "identity":
                    wrong["files"][key]["sha256"] = "0" * 64
                else:
                    (build / key).write_bytes(b"different source")
                with self.assertRaises(runner.c.Refused):
                    runner.verify_frozen_sources(build, repo, wrong)


if __name__ == "__main__":
    unittest.main()
