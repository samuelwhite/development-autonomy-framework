"""A8 recorder and bounded supervision. Native entry point deliberately CLOSED."""

import hashlib
import os
import subprocess
import threading
import time

import a8_observations as diagnostic
from qualify import a, c, publish

NAMES = ("A8-C0", "A8-S1")
HELPER_SECONDS, KILL_SECONDS, OUTER_SECONDS = 30, 3, 35
# Source-controlled Product decision, never a CLI/environment/test override.
# Changing this requires separate Product authorisation and a fresh frozen build.
NATIVE_BUDGET_RELEASED = True


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


def prerequisites(output, case, build_hash, mode, exercise=None, *, verifying=False):
    c.require(case in NAMES and mode in ("native", "simulated"), "a8_case_mode")
    c.require(not (output / "STOP.json").exists(), "irreversible_stop")
    if not verifying:
        c.require(not (output / f"{case}-claimed.json").exists(), "attempt_consumed")
    prior = []
    for previous in NAMES[: NAMES.index(case)]:
        receipt_raw = (output / f"{previous}-independent.json").read_bytes()
        receipt = c.load(receipt_raw, 100000)
        result_raw = (output / f"{previous}-result.json").read_bytes()
        result = c.load(result_raw, 100000)
        c.require(
            result["case"] == previous
            and result["evidence"]["case"] == previous
            and result["prior"] == prior
            and result["retries"] == 0
            and result["qualified"] is False
            and result["execution_authority"] is False,
            "previous_result_binding",
        )
        checked = diagnostic.validate(result["evidence"])
        c.require(
            receipt
            == {
                "schema": "daf-a8-independent/v2",
                "case": previous,
                "mode": mode,
                "build_manifest": build_hash,
                "result_sha256": c.sha(result_raw),
                "independently_verified": True,
                "qualified": False,
                "execution_authority": False,
                "control": checked,
                "independent_readback_processes_launched": 0,
                **({"exercise": exercise} if exercise is not None else {}),
            },
            "previous_independent_receipt",
        )
        c.require(
            result["status"] == "expected_control_observed"
            and result["mode"] == mode
            and result["build_manifest"] == build_hash,
            "previous_result",
        )
        if exercise is not None:
            c.require(result.get("exercise") == exercise, "previous_exercise")
            expected_claim = {
                "case": previous,
                "mode": mode,
                "build_manifest": build_hash,
                "prior": prior,
                "retries": 0,
                "exercise": exercise,
            }
            for suffix in ("claimed", "started"):
                c.require(
                    c.load((output / f"{previous}-{suffix}.json").read_bytes(), 100000)
                    == expected_claim,
                    "previous_claim_binding",
                )
            for suffix, field in (("stdout.capture", "stdout"), ("stderr.jsonl", "stderr")):
                raw = (output / f"{previous}-{suffix}").read_bytes()
                identity = result["evidence"][field]
                c.require(
                    len(raw) == identity["bytes"] and c.sha(raw) == identity["sha256"],
                    "previous_original_bytes",
                )
            c.require(
                a.observations((output / f"{previous}-stderr.jsonl").read_bytes())
                == result["evidence"]["observations"],
                "previous_original_observations",
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
    return _record_attempt(output, case, build_hash, mode, collect)


def _record_attempt(output, case, build_hash, mode, collect, exercise=None):
    c.require(mode in ("simulated", "native"), "a8_record_mode")
    prior = prerequisites(output, case, build_hash, mode, exercise)
    initial = {
        "case": case,
        "mode": mode,
        "build_manifest": build_hash,
        "prior": prior,
        "retries": 0,
        **({"exercise": exercise} if exercise is not None else {}),
    }
    publish(output / f"{case}-claimed.json", initial)
    publish(output / f"{case}-started.json", initial)
    result = {**initial, "status": "INCONCLUSIVE", "qualified": False, "execution_authority": False}
    collected = {"stdout": b"", "stderr": b""}

    def persist():
        metadata = {}
        for field, suffix, limit in (
            ("stdout", "stdout.capture", c.MAX_OUTPUT),
            ("stderr", "stderr.jsonl", 32768),
        ):
            path = output / f"{case}-{suffix}"
            raw = collected[field]
            if "capture_meta" in collected:
                c.require(path.read_bytes() == raw[:limit], "capture_changed_after_persistence")
                metadata[field] = collected["capture_meta"][field]
            else:
                metadata[field] = retain_capture(path, raw, limit)
        collected["capture_meta"] = metadata
        return metadata

    collected["persist"] = persist
    raw_out, raw_err = b"", b""
    try:
        collect(collected)
        raw_out, raw_err = collected["stdout"], collected["stderr"]
        # These are the UNCHANGED accepted A3/A7 capture limits. The success
        # validator additionally requires empty stdout; no child work is allowed.
        metadata = persist()
        out, err = metadata["stdout"], metadata["stderr"]
        evidence = {
            **collected["evidence"],
            "stdout": out,
            "stderr": err,
            "observations": a.observations(raw_err),
        }
        c.require(evidence["mode"] == mode and evidence["case"] == case, "collector_binding")
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
        if result["status"] != "expected_control_observed":
            for name in ("evidence", "supervision"):
                if name in collected:
                    result["partial_" + name] = collected[name]
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
        try:
            publish(output / f"{case}-result.json", result)
        except Exception:
            stop(output, case, {"stage": "result_persistence"}, mode)
            raise
    return result


def verify_frozen_sources(build, repo, manifest):
    expected = {
        "source/" + path.relative_to(repo / "desktop").as_posix(): path
        for directory in ("native-prelaunch", "native-foundation")
        for path in (repo / "desktop" / directory).iterdir()
        if path.is_file()
    }
    c.require(
        {k for k in manifest["files"] if k.startswith("source/")} == set(expected),
        "complete_frozen_sources",
    )
    for name, path in expected.items():
        raw = path.read_bytes()
        c.require(raw == (build / name).read_bytes(), "current_source")
        c.require(
            manifest["files"][name] == {"bytes": len(raw), "sha256": c.sha(raw)},
            "frozen_source_identity",
        )


def verify_build(build, workers):
    """Exact future collector inputs. This is read-only and never starts a case."""
    from a7_qualify import HISTORY as prior
    from a8_build_review import review
    from qualify import FOUNDATION, WORKERS

    repo = FOUNDATION.parents[1]
    c.require(build.is_relative_to(repo / "dist"), "owned_build")
    raw = (build / "build-manifest.json").read_bytes()
    manifest = c.load(raw, 250000)
    c.require(
        manifest["schema"] == "daf-a8-compile-only/v1"
        and manifest["status"] == "COMPILED_NOT_EXECUTED"
        and manifest["native_executions"] == 0
        and manifest["qualified"] is False
        and manifest["execution_authority"] is False
        and manifest["cases"] == {name: "NOT RUN" for name in NAMES},
        "compile_identity",
    )
    verify_frozen_sources(build, repo, manifest)
    for name, expected in manifest["files"].items():
        path = (build / name).resolve()
        c.require(path.is_relative_to(build), "manifest_path")
        data = path.read_bytes()
        c.require(
            len(data) == expected["bytes"] and c.sha(data) == expected["sha256"], "build_bytes"
        )
        if name.startswith("source/"):
            c.require(
                (repo / "desktop" / name.removeprefix("source/")).read_bytes() == data,
                "current_source",
            )
    c.require(
        review(build, compiled=True)
        == c.load((build / "a8-build-review.json").read_bytes(), 250000),
        "compiled_input_review",
    )
    for role, expected in WORKERS.items():
        c.require(c.sha((workers / (role + ".exe")).read_bytes()) == expected, "accepted_workers")
    history = {
        **prior,
        "docs/evidence/m2.1b-a7-mutation-windows.json": (
            "a0c68c524b677094a0f65edeba508bef4d652d6bf24ba2514f042ab9106a3b88"
        ),
    }
    for name, expected in history.items():
        c.require(c.sha((repo / name).read_bytes()) == expected, "preserved_history")
    return c.sha(raw)


def bounded_readback(attempt, record, deadline):
    """No fresh allowance for cleanup. Daemon lifetime never implies success."""
    from a8_verify import native_resource_readback
    from qualify import cleanup

    result = {}

    def work():
        try:
            cleanup(attempt)
            result["value"] = native_resource_readback(attempt, record)
        except Exception as error:
            result["error"] = error

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(timeout=max(0, deadline - time.monotonic()))
    c.require(not thread.is_alive(), "cleanup_deadline_unconfirmed")
    if "error" in result:
        raise result["error"]
    c.require("value" in result, "missing_cleanup")
    return result["value"]


def _native_collect(staged, attempt, build, workers, case):
    """Dormant native adapter. Only the separately gated native_entry calls it."""
    from a7_qualify import helper_identity

    attempt.mkdir()
    (attempt / "runtime").mkdir()
    publish(attempt / "started.json", {"case": case, "mode": "native", "qualified": False})
    for target, source in {
        "harness.exe": build / "a8-fixture-host.exe",
        "probe.exe": build / "handle-probe.exe",
        "producer.exe": workers / "producer.exe",
        "verifier.exe": workers / "verifier.exe",
    }.items():
        with (attempt / target).open("xb") as stream:
            stream.write(source.read_bytes())
    a.preparation(attempt)
    fixtures = {
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
    for name, data in fixtures.items():
        with (attempt / name).open("xb") as stream:
            stream.write(data)
    began = time.monotonic()
    process = subprocess.Popen(
        [str(attempt / "harness.exe"), case, "probe"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x08000000,
    )
    out = err = None
    try:
        out, err = a.Capture(process.stdout, c.MAX_OUTPUT), a.Capture(process.stderr, 32768)
        outcome = supervise(process, began, (out, err))
        # Freeze copies before parsing, metadata queries or cleanup can fail.
        staged["stdout"], staged["stderr"] = bytes(out.data), bytes(err.data)
        staged["supervision"] = outcome
        staged["persist"]()
        identity = helper_identity(process)
        rows = a.observations(staged["stderr"])
        record = {
            "schema": "daf-a8-case/v1",
            "case": case,
            "sequence": NAMES.index(case) + 1,
            "role": "probe",
            "mode": "native",
            "qualified": False,
            "execution_authority": False,
            "capture_complete": outcome["capture_complete"],
            "forced_outer_termination": outcome["forced_outer_termination"],
            "parent_deadline_exceeded": outcome["parent_deadline_exceeded"],
            "helper_exit": outcome["helper_exit"],
            "elapsed_ms": outcome["elapsed_ms"],
            "outer_elapsed_ms": 35000,
            "helper_identity": identity,
            "observations": rows,
            "cleanup": "unconfirmed",
            "synthetic_resources_unchanged": False,
            "independent_cleanup": {},
        }
        staged["evidence"] = record
        c.require(
            not outcome["errors"]
            and outcome["outer_bound_met"]
            and not out.overflow
            and not err.overflow,
            "native_supervision_incomplete",
        )
        record["independent_cleanup"] = bounded_readback(attempt, record, began + OUTER_SECONDS)
        record["cleanup"] = "confirmed"
        record["synthetic_resources_unchanged"] = True
        record["outer_elapsed_ms"] = round((time.monotonic() - began) * 1000)
    finally:
        if out is not None:
            staged["stdout"] = bytes(out.data)
        if err is not None:
            staged["stderr"] = bytes(err.data)
        if process.poll() is None:
            # Only this retained owned helper; any fallback makes the case fail.
            process.kill()
            process.wait(
                timeout=max(0, min(KILL_SECONDS, began + OUTER_SECONDS - time.monotonic()))
            )


def owned_paths(repo, build, workers, output):
    paths = (build, workers, output)
    for path in paths:
        c.require(path == path.resolve() and path.is_relative_to(repo / "dist"), "owned_path")
    c.require(len(set(paths)) == 3, "distinct_exercise_paths")
    c.require(
        all(not left.is_relative_to(right) for left in paths for right in paths if left != right),
        "disjoint_exercise_paths",
    )


def exercise_binding(repo, build, workers, output, mode, build_hash, source_hash):
    """Closed identity shared by entry, predecessor checks and independent readback."""
    c.require(mode in ("native", "simulated"), "exercise_mode")
    owned_paths(repo, build, workers, output)
    c.hex_value(build_hash)
    c.hex_value(source_hash)
    return {
        "schema": "daf-a8-exercise/v2",
        "mode": mode,
        "output": output.relative_to(repo).as_posix(),
        "build_directory": build.relative_to(repo).as_posix(),
        "workers_directory": workers.relative_to(repo).as_posix(),
        "build_manifest": build_hash,
        "source_identity": source_hash,
        "cases": list(NAMES),
        "retries": 0,
        "qualified": False,
        "execution_authority": False,
    }


def frozen_source_identity(build):
    manifest = c.load((build / "build-manifest.json").read_bytes(), 250000)
    sources = {k: v for k, v in manifest["files"].items() if k.startswith("source/")}
    c.require(bool(sources), "missing_frozen_sources")
    return c.sha(c.canonical(sources))


class NativeExecution:
    """Fixed native effects. Never accepts injected collectors or readback adapters."""

    mode = "native"

    def __init__(self):
        from qualify import FOUNDATION

        self.repo = FOUNDATION.parents[1]

    def check(self, build, workers):
        return verify_build(build, workers), frozen_source_identity(build)

    def collect(self, staged, output, build, workers, case):
        _native_collect(staged, output / case, build, workers, case)


def exercise_entry(case, build, workers, output, effects):
    """One entry state machine; portable fakes have simulated evidence/claims only.

    Native callers cannot inject effects or bypass the source-controlled release.
    Tests exercise the same ordering and claim decisions with explicit fakes.
    """
    c.require(case in NAMES, "a8_case_binding")
    mode, repo = effects.mode, effects.repo
    c.require(mode in ("native", "simulated"), "entry_mode")
    if mode == "native":
        require_native_release(case)
        c.require(type(effects) is NativeExecution, "fixed_native_effects")
    else:
        c.require(not isinstance(effects, NativeExecution), "simulation_effects")
    # All source/build/path prerequisites run before any exercise/case claim.
    owned_paths(repo, build, workers, output)
    build_hash, source_hash = effects.check(build, workers)
    binding = exercise_binding(repo, build, workers, output, mode, build_hash, source_hash)
    prefix = "m21b-a8" if mode == "native" else "m21b-a8-simulated"
    exercise = repo / "dist" / f"{prefix}-exercise-claimed.json"
    claim = repo / "dist" / f"{prefix}-{case}-execution-claimed.json"
    c.require(not claim.exists(), "global_attempt_consumed")
    c.require(not (output / "STOP.json").exists(), "irreversible_stop")
    if case == NAMES[0]:
        c.require(not output.exists(), "fresh_exercise")
        publish(exercise, binding)
    else:
        c.require(c.load(exercise.read_bytes(), 100000) == binding, "same_exercise")
    try:
        if case == NAMES[0]:
            output.mkdir()
        prerequisites(output, case, build_hash, mode, binding)
        if case == NAMES[1]:
            predecessor = repo / "dist" / f"{prefix}-{NAMES[0]}-execution-claimed.json"
            c.require(
                c.load(predecessor.read_bytes(), 100000) == {**binding, "case": NAMES[0]},
                "previous_global_claim",
            )
        # Global exclusive claim survives result/STOP persistence failures.
        publish(claim, {**binding, "case": case})
        # Recheck before calling any collector, including changes during claiming.
        c.require(
            effects.check(build, workers) == (build_hash, source_hash), "frozen_before_launch"
        )
        return _record_attempt(
            output,
            case,
            build_hash,
            mode,
            lambda staged: effects.collect(staged, output, build, workers, case),
            binding,
        )
    except Exception as error:
        if output.is_dir():
            stop(output, case, {"stage": "entry", "type": type(error).__name__}, mode)
        raise


def require_native_release(case):
    c.require(case in NAMES, "a8_case_binding")
    if NATIVE_BUDGET_RELEASED is not True:
        raise PermissionError("A8 native execution allowance remains unreleased")


def native_entry(case, build, workers, output):
    """Explicit two-case entry. Product has NOT released its native budget."""
    require_native_release(case)
    return exercise_entry(case, build, workers, output, NativeExecution())


def main():
    # No switch, environment override, Popen or native execution claim.
    raise PermissionError("A8 native execution is not authorised; C0 and S1 are NOT RUN")


if __name__ == "__main__":
    main()
