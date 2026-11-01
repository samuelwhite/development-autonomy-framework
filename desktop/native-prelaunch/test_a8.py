"""A8 portable simulations/static review only. Never compile or execute a fixture."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import a8_build_review as review
import a8_observations as d
import a8_qualify as runner
import a8_verify as verifier
import instrument_a8 as instrument
from test_a7 import fixture as previous_fixture


def fixture(case="A8-C0"):
    stall = case == "A8-S1"
    prior = previous_fixture()
    rows = [r for r in prior["observations"] if not r["native"].startswith("a7_")]
    if stall:
        rows = [
            r
            for r in rows
            if not r["native"].startswith(("a3_s1_", "a3_final_"))
            and r["native"] not in ("a3_inventories_consistent", "a3_controlled_stop")
        ]
    values = {r["native"]: r["value"] for r in rows if "value" in r}
    changes = {
        "a3_inspector_finished": int(not stall),
        "a3_inspector_wait": 258 if stall else 0,
        "a3_deadline_expired": int(stall),
        "a3_inspection_passed": int(not stall),
        "a3_last_stage": 2 if stall else 1,
        "a3_inspection_elapsed_ms": 5001 if stall else 25,
        "a1_control_h4_process_pid": 92,
        "a1_control_h4_process_creation": 900,
    }
    changes["host_failure" if stall else "a3_controlled_stop"] = 1
    for key, value in changes.items():
        present = next((r for r in rows if r["native"] == key), None)
        if present is None:
            rows.append({"native": key, "value": value})
        else:
            present["value"] = value
    # Synthetic chronology follows the actual inspector writer, including final
    # consistency only AFTER both tables. It is not a captured Windows record.
    consistent = [r for r in rows if r["native"] == "a3_inventories_consistent"]
    rows = [r for r in rows if r["native"] != "a3_inventories_consistent"] + consistent
    end = 6001000 if stall else 1025000
    audit = {
        "rows_bounded": 1,
        "private_rows": 42 if stall else 47,
        "case": int(stall),
        "sequence": 2 if stall else 1,
        "gate_initial": int(not stall),
        "gate_flags": 0,
        "entered_flags": 0,
        "qpc_frequency": 1000000,
        "observer_start_tick": 990,
        "supervisor_tid": 201,
        "start_tick": 1000,
        "start_qpc": 1000000,
        "wait_error": 0,
        "wait_qpc": end,
        "raw_deadline": int(stall),
        "done": int(not stall),
        "stop": int(stall),
        "inspector_cut": 3 if stall else 8,
        "observer_cut": 5,
        "shared_cut": 51 if stall else 107,
        "kill_qpc": end + 1,
        "terminated_qpc": end + 2000,
        "shared_emit": 51 if stall else 107,
        "witness_wait": 0,
        "witness_exit_ok": 1,
        "witness_exit": 123,
        "witness_pid": values["a3_expected_pid"],
        "witness_times_ok": 1,
        "witness_creation": values["a3_expected_creation"],
        "witness_tid": values["a3_expected_tid"],
        "witness_thread_ok": 1,
        "witness_thread_exit": 123,
        "witness_job_ok": 1,
        "witness_active": 0,
        "witness_qpc": end + 3000,
        "observer_thread_wait": 0,
        "inspector_tid": 202,
        "boundary_ready": 1,
        "call_qpc": 1010000,
        "call_return": 0,
        "call_error": 0,
        "return_qpc": 1015000,
        "ack_wait": 0,
        "ack_qpc": 1020000,
        "observer_tid": 203,
        "entered_wait": 0,
        "entered_error": 0,
        "gate_wait": 258 if stall else 0,
        "observed_qpc": 1011000,
    }
    keys = [
        "rows_bounded",
        "private_rows",
        *d.SUPERVISOR,
        *(d.INSPECTOR[:3] if stall else d.INSPECTOR),
        *d.OBSERVER,
    ]
    rows.extend({"native": "a8_" + k, "value": audit[k]} for k in keys)
    cleanup = copy.deepcopy(prior["independent_cleanup"])
    for process in cleanup["processes"]:
        if "open_error" not in process:
            process["creation"] = values["a3_expected_creation"] if process["pid"] == 90 else 900
            process["exit"] = 123 if process["pid"] == 90 else int(stall)
    return {
        "schema": "daf-a8-case/v1",
        "case": case,
        "sequence": 2 if stall else 1,
        "role": "probe",
        "mode": "simulated",
        "qualified": False,
        "execution_authority": False,
        "capture_complete": True,
        "forced_outer_termination": False,
        "parent_deadline_exceeded": False,
        "cleanup": "confirmed",
        "helper_exit": int(stall),
        "elapsed_ms": 6000 if stall else 100,
        "synthetic_resources_unchanged": True,
        "observations": rows,
        "independent_cleanup": cleanup,
        "helper_identity": {"pid": 92, "creation": 900, "query_ok": True, "error": 0},
        "stdout": {"bytes": 0, "sha256": "0" * 64, "overflow": False},
        "stderr": {"bytes": 10000, "sha256": "0" * 64, "overflow": False},
    }


def changed(record, key, value):
    result = copy.deepcopy(record)
    next(r for r in result["observations"] if r["native"] == key)["value"] = value
    return result


def collected(record):
    return {
        "stdout": b"",
        "stderr": b"".join(
            json.dumps(r, separators=(",", ":")).encode() + b"\n" for r in record["observations"]
        ),
        "evidence": record,
    }


class A8Preflight(unittest.TestCase):
    def test_actual_input_review_rejects_unreviewed_dependencies_and_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory).resolve()
            baseline = Path(__file__).with_name("suspended-inspection.h").read_bytes()
            generated = build / "a8-suspended-inspection.generated.h"
            generated.write_bytes(instrument.inspector(baseline))
            (build / "a8-inspector-baseline.h").write_bytes(baseline)
            harness = review.SOURCE.parent / "native-foundation/harness.cpp"
            (build / "a8-fixture-harness.h").write_bytes(
                instrument.instrument(harness.read_bytes())
            )
            (build / "probe-identity.h").write_text("// portable synthetic input\n")
            for unit, header in (
                ("a8-fixture-host", generated),
                ("a8-preprocess-baseline", build / "a8-inspector-baseline.h"),
            ):
                (build / (unit + ".i")).write_text(
                    f"#line 1 {json.dumps(str(header))}\n" + header.read_text(), encoding="utf-8"
                )
            includes = [
                generated,
                build / "a8-fixture-harness.h",
                build / "probe-identity.h",
                review.SOURCE / "a8-stall-control.h",
                review.SOURCE / "identity.h",
                review.SOURCE / "handle-diagnostic.h",
                harness.parent / "readiness.h",
                harness.parent / "sha256.h",
            ]
            dependency = {
                "Data": {
                    "Source": str(review.SOURCE / "a8-fixture-host.cpp"),
                    "Includes": list(map(str, includes)),
                }
            }
            path = build / "a8-fixture-host.preprocess.json"
            path.write_text(json.dumps(dependency), encoding="utf-8")
            self.assertTrue(review.review(build)["inspect_and_supervisor_token_inverse_exact"])
            for wrong in (
                [],
                [*includes, includes[0]],
                [*includes, build / "unreviewed.h"],
                [*includes, review.SOURCE / "suspended-inspection.h"],
            ):
                dependency["Data"]["Includes"] = list(map(str, wrong))
                path.write_text(json.dumps(dependency), encoding="utf-8")
                with self.assertRaises(ValueError):
                    review.review(build)
            dependency["Data"]["Includes"] = list(map(str, includes))
            path.write_text(json.dumps(dependency), encoding="utf-8")
            preprocessed = build / "a8-fixture-host.i"
            preprocessed.write_text(
                preprocessed.read_text().replace("latency <= TerminationMs", "latency <= 9000"),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                review.review(build)

    def test_collector_failure_retains_already_staged_prefix_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def failed(staged):
                staged["stderr"] = b'{"native":"partial"'
                raise OSError("synthetic collector failure")

            value = runner.record_attempt(output, "A8-C0", "build", "simulated", failed)
            self.assertEqual(value["status"], "INCONCLUSIVE")
            self.assertEqual((output / "A8-C0-stderr.jsonl").read_bytes(), b'{"native":"partial"')
            self.assertTrue((output / "STOP.json").exists())

    def test_storage_failure_cannot_leave_reusable_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(
                runner, "retain_capture", side_effect=OSError("synthetic storage failure")
            ):
                value = runner.record_attempt(
                    output,
                    "A8-C0",
                    "build",
                    "simulated",
                    lambda staged: staged.update(collected(fixture())),
                )
            self.assertEqual(value["status"], "INCONCLUSIVE")
            self.assertTrue((output / "A8-C0-claimed.json").exists())
            with self.assertRaises(runner.c.Refused):
                runner.prerequisites(output, "A8-S1", "build", "simulated")

    def test_safety_hooks_are_bounded_single_writer_and_owned(self):
        source = Path(__file__).with_name("a8-stall-control.h").read_text()
        self.assertIn("Rows<44> supervisor", source)
        self.assertIn("Rows<10> inspector", source)
        self.assertIn("Rows<6> observer", source)
        self.assertEqual(source.count("SignalObjectAndWait("), 1)
        self.assertIn("SignalObjectAndWait(c->entered, c->gate, INFINITE, FALSE)", source)
        self.assertIn(
            "if (observerWait == WAIT_OBJECT_0) observer.join(); else observer.detach();", source
        )
        for forbidden in (
            "SetEvent(",
            "ResetEvent(",
            "TerminateThread(",
            "ResumeThread(",
            "Sleep(",
            "OpenProcess(",
            "CancelSynchronousIo(",
        ):
            self.assertNotIn(forbidden, source)
        for name in ("started", "decision", "killing", "terminated", "published"):
            start = source.index("inline void " + name + "(")
            body = (
                source[start : source.index("\n}", start) + 2]
                if name in ("started", "decision", "terminated", "published")
                else source[start : source.index("\n", start)]
            )
            self.assertIn("noexcept", body)
            for forbidden in (
                "emit(",
                "std::cerr",
                "new ",
                "make_shared",
                "WaitFor",
                "std::string",
                '.put("failure',
            ):
                self.assertNotIn(forbidden, body)

    def test_positive_controls_are_explicitly_simulated(self):
        for case in runner.NAMES:
            result = d.validate(fixture(case))
            self.assertTrue(result["expected_control_observed"])
            self.assertFalse(result["native_deadline_qualified"])
            self.assertFalse(result["qualified"])
            self.assertEqual(result["inspection_passed"], case == "A8-C0")

    def test_every_private_observation_is_required(self):
        for case in runner.NAMES:
            record = fixture(case)
            for row in record["observations"]:
                if row["native"].startswith("a8_"):
                    with self.subTest(case=case, missing=row["native"]):
                        value = copy.deepcopy(record)
                        value["observations"].remove(row)
                        with self.assertRaises((d.InvalidObservation, KeyError)):
                            d.validate(value)

    def test_adversarial_timeout_and_safety_observations(self):
        record = fixture("A8-S1")
        for key, value in {
            "a3_inspector_wait": 0xFFFFFFFF,
            "a8_wait_error": 6,
            "a8_raw_deadline": 0,
            "a3_deadline_expired": 0,
            "a3_inspection_elapsed_ms": 4999,
            "a8_stop": 0,
            "a8_done": 1,
            "a3_inspection_passed": 1,
            "a3_terminate_job_ok": 0,
            "a3_process_wait": 258,
            "a3_termination_elapsed_ms": 3001,
            "a8_witness_exit": 259,
            "a8_witness_active": 1,
            "a8_witness_creation": 1001,
            "a8_entered_wait": 258,
            "a8_observed_qpc": 7000000,
            "a8_gate_wait": 0,
            "a8_call_qpc": 0,
            "a8_qpc_frequency": 0,
            "a8_observer_thread_wait": 258,
            "a8_inspector_cut": 8,
            "a8_shared_emit": 52,
            "a8_rows_bounded": 0,
            "a8_inspector_tid": 201,
            "a3_s0_suspend_count": 0,
            "a3_s0_policy_flags": 1,
            "a3_s0_h0_hostile": 1,
            "a3_s0_handles_captured": 4,
        }.items():
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate(changed(record, key, value))
        for key, value in {
            "helper_exit": 0,
            "capture_complete": False,
            "forced_outer_termination": True,
            "cleanup": "unconfirmed",
            "elapsed_ms": 35000,
            "qualified": True,
            "execution_authority": True,
            "mode": "unlabelled",
        }.items():
            with self.subTest(key=key), self.assertRaises(d.InvalidObservation):
                d.validate({**record, key: value})
        for key in ("a3_s1_pid", "a3_inventories_consistent", "a3_failure"):
            value = copy.deepcopy(record)
            value["observations"].append({"native": key, "value": 1})
            with self.assertRaises(d.InvalidObservation):
                d.validate(value)

    def test_order_duplicate_missing_shape_and_byte_limits(self):
        record = fixture()
        for rows in (
            record["observations"][:-1],
            [*record["observations"], record["observations"][-1]],
            list(reversed(record["observations"])),
        ):
            with self.assertRaises((d.InvalidObservation, KeyError)):
                d.validate({**record, "observations": rows})
        for case in runner.NAMES:
            record = fixture(case)
            self.assertLessEqual(d.evidence_bound(record["observations"]), 32768)
            self.assertLessEqual(
                sum(r["native"].startswith("a8_") for r in record["observations"]), 64
            )
        value = copy.deepcopy(record)
        value["stdout"]["bytes"] = 1
        with self.assertRaises(d.InvalidObservation):
            d.validate(value)

    def test_complete_source_and_token_inverse_both_newlines(self):
        raw = (
            Path(__file__).with_name("suspended-inspection.h").read_bytes().replace(b"\r\n", b"\n")
        )
        for baseline in (raw, raw.replace(b"\n", b"\r\n")):
            generated = instrument.inspector(baseline)
            self.assertEqual(instrument.inverse(generated), baseline)
            self.assertEqual(
                review.inverse_tokens(review.tokens(generated.decode())),
                review.tokens(baseline.decode()),
            )
        for before, after in instrument.TRANSFORMS:
            with self.subTest(anchor=before), self.assertRaises(ValueError):
                instrument.inverse(instrument.inspector(raw).replace(after, before))
        with self.assertRaises(ValueError):
            instrument.inspector(raw.replace(b"DeadlineMs = 5000", b"DeadlineMs = 5001"))
        harness = Path(__file__).parents[1] / "native-foundation/harness.cpp"
        self.assertEqual(
            instrument.harness_inverse(
                instrument.instrument(harness.read_bytes()), harness.read_bytes()
            ),
            harness.read_bytes(),
        )
        review.launcher()

    def test_preprocessed_windows_escaping_and_wrong_path(self):
        for name in (r"C:\review\a8-generated.h", "/review/a8-generated.h"):
            self.assertEqual(
                review.section(f"#line 1 {json.dumps(name)}\nint exact;", name),
                ["int", "exact", ";"],
            )
            with self.assertRaises(ValueError):
                review.section(f"#line 1 {json.dumps(name)}\nint exact;", name + ".wrong")

    def test_native_entry_and_recording_cannot_launch_or_claim(self):
        with tempfile.TemporaryDirectory() as directory, patch("subprocess.Popen") as launch:
            output = Path(directory)
            with self.assertRaises(PermissionError):
                runner.main()
            with self.assertRaises(runner.c.Refused):
                runner.record_attempt(output, "A8-C0", "build", "native", Mock())
            self.assertEqual(list(output.iterdir()), [])
            launch.assert_not_called()

    def test_simulated_sequence_independent_receipt_and_no_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaises(FileNotFoundError):
                runner.prerequisites(output, "A8-S1", "build", "simulated")
            for case in runner.NAMES:
                record = fixture(case)
                result = runner.record_attempt(
                    output,
                    case,
                    "build",
                    "simulated",
                    lambda staged, value=record: staged.update(collected(value)),
                )
                self.assertEqual(result["status"], "expected_control_observed", result)
                verifier.verify(output, case, lambda value=record: value["independent_cleanup"])
                with self.assertRaises(runner.c.Refused):
                    runner.prerequisites(output, case, "build", "simulated")

    def test_partial_output_and_missing_cleanup_preserve_stop(self):
        for kind in ("partial", "cleanup", "collector"):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                record = fixture()
                data = collected(record)
                if kind == "partial":
                    data["stderr"] = b'{"native":"incomplete"'
                if kind == "cleanup":
                    record["cleanup"] = "unconfirmed"
                collect = (
                    Mock(side_effect=OSError("synthetic"))
                    if kind == "collector"
                    else lambda staged, value=data: staged.update(value)
                )
                result = runner.record_attempt(output, "A8-C0", "build", "simulated", collect)
                self.assertEqual(result["status"], "INCONCLUSIVE")
                self.assertEqual(
                    (output / "A8-C0-stderr.jsonl").read_bytes(),
                    b"" if kind == "collector" else data["stderr"],
                )
                before = (output / "STOP.json").read_bytes()
                runner.stop(output, "A8-S1", {}, "simulated")
                self.assertEqual((output / "STOP.json").read_bytes(), before)
                with self.assertRaises(runner.c.Refused):
                    runner.prerequisites(output, "A8-S1", "build", "simulated")

    def test_supervision_failures_use_original_absolute_bounds(self):
        for error in (subprocess.TimeoutExpired("synthetic", 30), OSError("synthetic")):
            process = Mock(returncode=None)
            process.wait.side_effect = [error, subprocess.TimeoutExpired("synthetic", 3)]
            thread = Mock()
            thread.is_alive.return_value = True
            clock = Mock(side_effect=[30, 34, 36, 36, 36])
            result = runner.supervise(process, 0, [SimpleNamespace(thread=thread)], clock)
            self.assertTrue(result["forced_outer_termination"])
            self.assertFalse(result["capture_complete"])
            self.assertFalse(result["outer_bound_met"])
            self.assertEqual(process.wait.call_args_list[1].kwargs["timeout"], 1)
            self.assertEqual(thread.join.call_args.kwargs["timeout"], 0)


if __name__ == "__main__":
    unittest.main()
