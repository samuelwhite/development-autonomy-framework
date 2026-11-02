"""Public TC-0 route. Closed source gates precede every claim and native effect."""

import os
import sys
import threading
import time
from pathlib import Path

import ae5_parent
import ae5_windows
import ae51_contract as contract
from ae5_contract import ACK, OUTER_MS, canonical, require
from ae51_evidence import cleanup_readback, fixture_baseline, frames, verify_observations
from ae51_package import REPO, identity, owned, verify_package

FIXTURES = {
    "allowed.txt": b"Explicitly readable synthetic fixture",
    "private.txt": b"Host-private synthetic fixture",
    "ambient-shared.txt": b"Synthetic resource shared with all LPACs",
    "dual-grant.txt": b"Explicit dual-grant synthetic fixture",
    "protected.bin": b"",
    "fixture-root.marker": b"DAF M2.1A owned acceptance fixture",
    "request.bin": b"",
    "smuggled-read.txt": b"R" * 32,
    "smuggled-write.txt": b"S" * 32,
}


def require_release():
    require(
        ae5_parent.NATIVE_RELEASE is True and ae5_windows.NATIVE_RELEASE is True,
        "native_source_gates_closed",
    )
    require(
        type(contract.PRODUCT_DECISION_ID) is str and bool(contract.PRODUCT_DECISION_ID),
        "product_decision_unreleased",
    )


def publish(path, raw):
    """Exclusive durable write. A partial file remains consumed, never overwritten."""
    with path.open("xb") as stream:
        require(stream.write(raw) == len(raw), "short_evidence_write")
        stream.flush()
        os.fsync(stream.fileno())
    require(path.read_bytes() == raw, "evidence_readback")


def execute_tc0(package):
    require_release()  # Calling this public function directly cannot bypass the gates.
    value, package_sha, _ = verify_package(package)
    bound = value["binding"]
    require(
        value["status"] == "PRODUCT_RELEASE_REVIEWED" and type(value["approval"]) is str,
        "preflight_is_not_approval",
    )
    approval_raw = owned(REPO / value["approval"]).read_bytes()
    approval = contract.load(approval_raw, 10000)
    contract.approval(approval, bound, int(time.time()))
    require(approval["decision_id"] == contract.PRODUCT_DECISION_ID, "unreviewed_product_decision")
    cpp = (REPO / value["build"] / "source/native-prelaunch/ae5-custody.h").read_text()
    require("inline volatile const LONG NativeRelease = 1;" in cpp, "cpp_native_gate_closed")
    # Fixed global paths; another output directory or package cannot reset the budget.
    root = owned(REPO / "dist/m21b-ae51-TC-0")
    claim_path = owned(REPO / "dist/m21b-ae51-TC-0-consumed.json")
    stop_path = owned(REPO / "dist/m21b-ae51-STOP.json")
    contract.unused_attempt(root.exists(), claim_path.exists(), stop_path.exists())
    consumed = {
        "schema": "daf-ae51-consumed-claim/v1",
        "case": "TC-0",
        "binding": contract.binding(bound),
        "approval_sha256": contract.digest(approval_raw),
        "attempt": 1,
        "retries": 0,
        "mode": "native",
    }
    contract.claim(consumed, bound, contract.digest(approval_raw))
    claim_raw = canonical(consumed)
    publish(claim_path, claim_raw)
    try:
        # Detect changes during claim persistence before any preparation/launch.
        require(verify_package(package)[1] == package_sha, "package_changed_during_claim")
        require(owned(REPO / value["approval"]).read_bytes() == approval_raw, "approval_changed")
        contract.approval(approval, bound, int(time.time()))
        root.mkdir()
        evidence = root / "evidence"
        attempt = root / "fixture"
        evidence.mkdir()
        attempt.mkdir()
        (attempt / "runtime").mkdir()
        sources = {
            "ae5-fixture-host.exe": REPO / value["build"] / "ae5-fixture-host.exe",
            "probe.exe": REPO / value["build"] / "handle-probe.exe",
            "producer.exe": REPO / value["workers"] / "producer.exe",
            "verifier.exe": REPO / value["workers"] / "verifier.exe",
        }
        for name, source in sources.items():
            publish(attempt / name, source.read_bytes())
            key = "handle-probe.exe" if name == "probe.exe" else name
            require(identity(attempt / name) == bound["files"][key], "staged_binary_identity")
        for name, data in FIXTURES.items():
            publish(attempt / name, data)
        b = ae5_windows.WindowsCustody(attempt)
        baseline = fixture_baseline(
            b,
            [
                attempt,
                attempt / "runtime",
                *(attempt / name for name in (*sources, *FIXTURES)),
            ],
        )
        publish(evidence / "fixture-baseline.json", canonical(baseline))
        return collect_tc0(b, value, evidence, baseline, claim_raw, approval_raw)
    except BaseException as error:
        if not stop_path.exists():
            publish(
                stop_path,
                canonical(
                    {
                        "schema": "daf-ae51-stop/v1",
                        "case": "TC-0",
                        "claim_sha256": contract.digest(claim_raw),
                        "failure": type(error).__name__,
                        "cleanup": "UNRESOLVED",
                        "qualified": False,
                        "execution_authority": False,
                        "retries": 0,
                    }
                ),
            )
        raise


def collect_tc0(b, package, evidence, baseline, claim_raw, approval_raw):
    require_release()  # No private collector bypass.
    bound = package["binding"]
    claim_path = REPO / "dist/m21b-ae51-TC-0-consumed.json"
    stop_path = REPO / "dist/m21b-ae51-STOP.json"
    require(
        claim_path.read_bytes() == claim_raw and not stop_path.exists(),
        "live_consumed_claim_required",
    )
    contract.claim(contract.load(claim_raw), bound, contract.digest(approval_raw))
    publish(
        evidence / "collection-started.json",
        canonical({"binding": contract.binding(bound), "case": "TC-0"}),
    )
    state, completed, revoked = {}, threading.Event(), threading.Event()
    finalization = contract.Finalization()
    outer_started = b.k.GetTickCount64()

    def work():
        try:
            b.pin_images(
                {
                    name: bound["files"]["handle-probe.exe" if name == "probe.exe" else name]
                    for name in (
                        "ae5-fixture-host.exe",
                        "probe.exe",
                        "producer.exe",
                        "verifier.exe",
                    )
                }
            )
            helper, started = b.create_helper(b.root / "ae5-fixture-host.exe")
            custodian = ae5_parent.Custodian(
                b,
                helper,
                started,
                bound["exercise"],
                lambda seq, raw: ae5_parent.append_exclusive(evidence, seq, raw),
                b.k.GetTickCount64,
            )
            state["custodian"] = custodian
            lanes = custodian.start()
            while b.helper_alive() and b.k.GetTickCount64() < outer_started + 30000:
                time.sleep(0.005)
            state["helper_elapsed_ms"] = b.k.GetTickCount64() - started
            if b.helper_alive():
                custodian.stop("helper_deadline")
            while not (custodian.stderr_complete and custodian.control_complete):
                require(b.k.GetTickCount64() < outer_started + OUTER_MS, "capture_deadline")
                time.sleep(0.005)
            # Freeze original bytes before parse/readback/receipt operations.
            for name, raw in (
                ("control.bin", bytes(custodian.control_capture)),
                ("stderr.jsonl", bytes(custodian.stderr)),
                ("acks.bin", bytes(custodian.ack_capture)),
            ):
                publish(evidence / name, raw)
            messages = frames(bytes(custodian.control_capture))
            custody_message = next(row for row in messages if row["kind"] == "custody")
            expected = {
                name: contract.digest(raw)
                for name, raw in FIXTURES.items()
                if name != "protected.bin"
            }
            expected["dual-grant.txt"] = contract.digest(
                FIXTURES["dual-grant.txt"] + b"\nAPPROVED SYNTHETIC POSITIVE CONTROL"
            )
            expected["protected.bin"] = b.protected_fixture_sha256
            for name in ("producer.exe", "verifier.exe", "probe.exe", "ae5-fixture-host.exe"):
                key = "handle-probe.exe" if name == "probe.exe" else name
                expected[name] = bound["files"][key]["sha256"]
            live = cleanup_readback(b, baseline, expected)
            record = {
                "schema": "daf-ae51-observation/v1",
                "case": "TC-0",
                "binding": contract.binding(bound),
                "qualified": False,
                "execution_authority": False,
                "resumes": 0,
                "parent": {"pid": b.parent_pid, "creation": b.parent_creation},
                "started": started,
                "helper_elapsed_ms": state["helper_elapsed_ms"],
                "elapsed_ms": b.k.GetTickCount64() - outer_started,
                "custody": custodian.observed,
                "snapshot": b.independent_snapshot,
                "custody_verified_ms": next(
                    row["ms"] for row in custodian.timeline if row["event"] == "custody_verified"
                ),
                "inspection_deadline": ACK.unpack(
                    bytes(custodian.ack_capture)[
                        custody_message["seq"] * 64 : (custody_message["seq"] + 1) * 64
                    ]
                )[2],
                "timeline": list(custodian.timeline),
                "ledger": list(custodian.ledger.records),
                "readback": live,
                "control_complete": custodian.control_complete,
                "stderr_complete": custodian.stderr_complete,
                "control_overflow": custodian.control_overflow,
                "stderr_overflow": custodian.stderr_overflow,
                "stop_reason": custodian.decision.reason,
                "termination_requests": dict(custodian.termination_calls),
                "failure": None,
                "captures": {
                    name: {"bytes": len(raw), "sha256": contract.digest(raw)}
                    for name, raw in (
                        ("control", bytes(custodian.control_capture)),
                        ("stderr", bytes(custodian.stderr)),
                        ("acks", bytes(custodian.ack_capture)),
                    )
                },
            }
            publish(evidence / "observations.json", canonical(record))
            # A separate readback repeats kernel exits and exact-resource checks,
            # then re-reads all durable original bytes. It launches no process.
            second = cleanup_readback(b, baseline, expected)
            original = contract.load((evidence / "observations.json").read_bytes())
            verify_observations(
                original,
                bound,
                (evidence / "control.bin").read_bytes(),
                (evidence / "stderr.jsonl").read_bytes(),
                (evidence / "acks.bin").read_bytes(),
                second,
            )
            require(
                not revoked.is_set() and b.k.GetTickCount64() < outer_started + OUTER_MS,
                "verification_deadline",
            )
            custodian.safety_done.set()
            for lane in (*lanes, *custodian.lanes.values()):
                lane.join(
                    timeout=max(
                        0, min(0.1, (outer_started + OUTER_MS - b.k.GetTickCount64()) / 1000)
                    )
                )
                require(not lane.is_alive(), "parent_lane_unresolved")
            b.close_custody()
            # Receipt construction is native-only, after all independent checks.
            receipt = {
                "schema": "daf-ae51-independent-receipt/v1",
                "case": "TC-0",
                "binding": contract.binding(bound),
                "claim_sha256": contract.digest(claim_raw),
                "evidence_sha256": contract.digest((evidence / "observations.json").read_bytes()),
                "readback_sha256": contract.digest(canonical(second)),
                "status": "TC0_EXPECTED_OBSERVATIONS",
                "qualified": False,
                "execution_authority": False,
                "additional_processes_launched": 0,
            }
            contract.claim(contract.load(claim_raw), bound, contract.digest(approval_raw))
            contract.receipt(
                receipt,
                bound,
                contract.digest(claim_raw),
                receipt["evidence_sha256"],
                receipt["readback_sha256"],
            )
            publish(evidence / "independent-receipt.json", canonical(receipt))
            require(
                not revoked.is_set()
                and b.k.GetTickCount64() < outer_started + OUTER_MS
                and not stop_path.exists(),
                "late_receipt_is_not_success",
            )
            publish(
                evidence / "completion.json",
                canonical(
                    {
                        "binding": contract.binding(bound),
                        "receipt_sha256": contract.digest(canonical(receipt)),
                        "parent_handles_closed": True,
                        "elapsed_ms": b.k.GetTickCount64() - outer_started,
                        "qualified": False,
                    }
                ),
            )
            require(
                not revoked.is_set() and b.k.GetTickCount64() < outer_started + OUTER_MS,
                "completion_deadline",
            )
            finalization.finish(b.k.GetTickCount64(), outer_started + OUTER_MS)
            state["result"] = receipt
        except BaseException as error:
            finalization.stop()
            state["failure"] = type(error).__name__
            if "custodian" in state:
                state["custodian"].stop("collector_failure")
                custodian = state["custodian"]
                # Preserve original bounded prefixes even when parsing/readback failed.
                for name, raw in (
                    ("control.bin", bytes(custodian.control_capture)),
                    ("stderr.jsonl", bytes(custodian.stderr)),
                    ("acks.bin", bytes(custodian.ack_capture)),
                ):
                    if not (evidence / name).exists():
                        publish(evidence / name, raw)
                publish(
                    evidence / "incomplete-observations.json",
                    canonical(
                        {
                            "failure": state["failure"],
                            "qualified": False,
                            "execution_authority": False,
                            "cleanup": "UNRESOLVED",
                            "ledger": list(custodian.ledger.records),
                            "timeline": list(custodian.timeline),
                            "custody": custodian.observed,
                            "termination_requests": dict(custodian.termination_calls),
                        }
                    ),
                )
        finally:
            completed.set()

    threading.Thread(target=work, daemon=True).start()
    # This lane never waits on IPC, filesystem, query/readback or helper shutdown.
    while not completed.is_set() and b.k.GetTickCount64() < outer_started + OUTER_MS:
        completed.wait(0.005)
    if (
        not completed.is_set()
        or "failure" in state
        or finalization.state != "COMPLETE"
        or b.k.GetTickCount64() >= outer_started + OUTER_MS
    ):
        revoked.set()
        finalization.stop()
        if "custodian" in state:
            state["custodian"].stop("collector_unresolved")
        threading.Thread(target=b.terminate, args=("outer",), daemon=True).start()
        raise RuntimeError("TC-0 unresolved; attempt consumed; no recovery or progression")
    require("result" in state, "missing_independent_receipt")
    return state["result"]


def main():
    require(len(sys.argv) == 2, "one_reviewed_package_path_required")
    # No activation option, case selector, adapter injection or environment control.
    return ae5_parent.native_entry(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
