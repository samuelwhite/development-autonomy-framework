"""A8 recorder and bounded supervision. Native entry point deliberately CLOSED."""

import hashlib
import os
import subprocess
import time

import a8_observations as diagnostic
from qualify import a, c, publish

NAMES = ("A8-C0", "A8-S1")
HELPER_SECONDS, KILL_SECONDS, OUTER_SECONDS = 30, 3, 35


def stop(output, case, failure, mode):
    c.require(case in NAMES and mode in ("native", "simulated"), "a8_stop_binding")
    path = output / "STOP.json"
    if path.exists():
        return c.load(path.read_bytes(), 100000)
    value = {
        "schema": "daf-a8-stop/v1",
        "case": case,
        "mode": mode,
        "failure": failure,
        "qualified": False,
        "execution_authority": False,
        "remaining_cases": {name: "NOT RUN" for name in NAMES[NAMES.index(case) + 1 :]},
        "retries": 0,
    }
    publish(path, value)
    return value


def prerequisites(output, case, build_hash, mode):
    c.require(case in NAMES and mode in ("native", "simulated"), "a8_case_mode")
    c.require(not (output / "STOP.json").exists(), "irreversible_stop")
    c.require(not (output / f"{case}-claimed.json").exists(), "attempt_consumed")
    prior = []
    for previous in NAMES[: NAMES.index(case)]:
        receipt_raw = (output / f"{previous}-independent.json").read_bytes()
        receipt = c.load(receipt_raw, 100000)
        result_raw = (output / f"{previous}-result.json").read_bytes()
        result = c.load(result_raw, 100000)
        checked = diagnostic.validate(result["evidence"])
        c.require(
            receipt
            == {
                "schema": "daf-a8-independent/v1",
                "case": previous,
                "mode": mode,
                "build_manifest": build_hash,
                "result_sha256": c.sha(result_raw),
                "independently_verified": True,
                "qualified": False,
                "execution_authority": False,
                "control": checked,
                "native_processes_launched": 0,
            },
            "previous_independent_receipt",
        )
        c.require(
            result["status"] == "expected_control_observed"
            and result["mode"] == mode
            and result["build_manifest"] == build_hash,
            "previous_result",
        )
        prior.append({"case": previous, "sha256": c.sha(receipt_raw)})
    return prior


def supervise(process, start, captures, clock=time.monotonic):
    """Process adapter or portable fake. Never launches; never resets a deadline."""
    value = {"forced_outer_termination": False, "parent_deadline_exceeded": False, "errors": []}
    try:
        process.wait(timeout=max(0, start + HELPER_SECONDS - clock()))
    except subprocess.TimeoutExpired:
        value.update(forced_outer_termination=True, parent_deadline_exceeded=True)
        try:
            process.kill()
            process.wait(timeout=max(0, min(KILL_SECONDS, start + OUTER_SECONDS - clock())))
        except Exception as error:
            value["errors"].append({"stage": "forced_wait", "type": type(error).__name__})
    except Exception as error:
        value["errors"].append({"stage": "helper_wait", "type": type(error).__name__})
        value["forced_outer_termination"] = True
        try:
            process.kill()
            process.wait(timeout=max(0, min(KILL_SECONDS, start + OUTER_SECONDS - clock())))
        except Exception as error:
            value["errors"].append({"stage": "failure_cleanup", "type": type(error).__name__})
    finally:
        for capture in captures:
            try:
                capture.thread.join(
                    timeout=max(0, min(KILL_SECONDS, start + OUTER_SECONDS - clock()))
                )
            except Exception as error:
                value["errors"].append({"stage": "capture_wait", "type": type(error).__name__})
        value["helper_exit"] = process.returncode
        value["elapsed_ms"] = round((clock() - start) * 1000)
        value["outer_bound_met"] = clock() < start + OUTER_SECONDS
        value["capture_complete"] = all(not capture.thread.is_alive() for capture in captures)
    return value


def retain_capture(path, raw, limit):
    """Persist original bounded prefix before parsing, including partial records."""
    c.require(type(raw) is bytes, "capture_type")
    retained = raw[:limit]
    with path.open("xb") as stream:
        c.require(stream.write(retained) == len(retained), "raw_write")
        stream.flush()
        os.fsync(stream.fileno())
    c.require(path.read_bytes() == retained, "raw_readback")
    return {
        "bytes": len(retained),
        "sha256": hashlib.sha256(retained).hexdigest(),
        "overflow": len(raw) > limit,
    }


def record_attempt(output, case, build_hash, mode, collect):
    """Portable recording adapter; claims/STOP are synthetic and explicitly labelled.

    Native activation and any launch require separate Product review. No switch or
    environment variable changes this gate. collect supplies copied raw bytes and
    separate observation/readback metadata, never an inferred successful timeout.
    """
    c.require(mode == "simulated", "a8_native_allowance_not_released")
    prior = prerequisites(output, case, build_hash, mode)
    initial = {
        "case": case,
        "mode": mode,
        "build_manifest": build_hash,
        "prior": prior,
        "retries": 0,
    }
    publish(output / f"{case}-claimed.json", initial)
    publish(output / f"{case}-started.json", initial)
    result = {**initial, "status": "INCONCLUSIVE", "qualified": False, "execution_authority": False}
    collected = {"stdout": b"", "stderr": b""}
    raw_out, raw_err = b"", b""
    try:
        collect(collected)
        raw_out, raw_err = collected["stdout"], collected["stderr"]
        # These are the UNCHANGED accepted A3/A7 capture limits. The success
        # validator additionally requires empty stdout; no child work is allowed.
        out = retain_capture(output / f"{case}-stdout.capture", raw_out, c.MAX_OUTPUT)
        err = retain_capture(output / f"{case}-stderr.jsonl", raw_err, 32768)
        evidence = {
            **collected["evidence"],
            "stdout": out,
            "stderr": err,
            "observations": a.observations(raw_err),
        }
        result["evidence"] = evidence
        result["control"] = diagnostic.validate(evidence)
        result["status"] = "expected_control_observed"
    except Exception as error:
        result["failure"] = {"type": type(error).__name__, "errno": getattr(error, "errno", None)}
        if isinstance(error, (diagnostic.InvalidObservation, c.Refused)):
            result["failure"]["stage"] = str(error)
    finally:
        # The collector stages immutable byte prefixes before operations that may
        # fail, so an exception cannot discard already captured failure evidence.
        raw_out, raw_err = collected["stdout"], collected["stderr"]
        for suffix, raw, limit in (
            ("stdout.capture", raw_out, c.MAX_OUTPUT),
            ("stderr.jsonl", raw_err, 32768),
        ):
            path = output / f"{case}-{suffix}"
            if not path.exists():
                try:
                    retain_capture(path, raw, limit)
                except Exception as error:
                    result["status"] = "INCONCLUSIVE"
                    result["persistence_failure"] = type(error).__name__
        if result["status"] != "expected_control_observed":
            stop(output, case, result.get("failure", {"stage": "persistence"}), mode)
        publish(output / f"{case}-result.json", result)
    return result


def main():
    # No switch, environment override, Popen or native execution claim.
    raise PermissionError("A8 native execution is not authorised; C0 and S1 are NOT RUN")


if __name__ == "__main__":
    main()
