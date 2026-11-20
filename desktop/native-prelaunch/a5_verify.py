"""Separate A5 evidence/resource readback. Never launches or retries a fixture."""

import json
import sys
from pathlib import Path

import a5_observations as diagnostic
from a3_qualify import verify_cleanup
from a4_verify import fixture_file_identity, storage_absent
from a5_cases import NAMES, specification
from a5_qualify import prerequisite, stop, verify_build
from qualify import FOUNDATION, WORKERS, c, publish


def verify(output, case):
    c.require(case in NAMES and not (output / "STOP.json").exists(), "a5_stopped_or_unknown")
    repo = FOUNDATION.parents[1]
    c.require(output.is_relative_to(repo / "dist"), "readback_owned_root")
    sequence = specification(case)[0]
    attempt = output / f"{sequence:02d}-{case}-probe"
    raw = (output / f"{case}-completion.json").read_bytes()
    complete = c.load(raw, 100000)
    result_raw = (attempt / "result.json").read_bytes()
    record = c.load(result_raw, 100000)
    c.require(
        complete["records"] == [record] and record["status"] == "passed", "complete_case_result"
    )
    c.require(
        complete["case"] == case
        and complete["sequence"] == sequence
        and complete["retries"] == 0
        and complete["qualified"] is False,
        "case_completion",
    )
    c.require(complete["detector_refusal_observed"] is True, "case_outcome")
    checked = diagnostic.validate(record)
    c.require(json.loads(json.dumps(checked)) == record["inspection"], "saved_inspection")
    start = (output / f"{case}-started.json").read_bytes()
    c.require(
        start == (repo / "dist" / f"m21b-a5-{case}-execution-claimed.json").read_bytes(),
        "consumed_claim_identity",
    )
    for key, value in c.load(start, 100000).items():
        c.require(complete.get(key) == value, "start_completion_identity")
    build = (repo / complete["build_directory"]).resolve()
    c.require(build.is_relative_to(repo / "dist"), "readback_owned_build")
    c.require(
        verify_build(build, repo / "dist/m21a-persistence-01") == complete["build_manifest"],
        "readback_build_identity",
    )
    manifest = c.load((build / "build-manifest.json").read_bytes(), 250000)
    c.require(complete["implementation_commit"] == manifest["git_parent"], "executed_source_commit")
    for name, expected in complete["binary_identities"].items():
        c.require(manifest["files"][name] == expected, "case_image_manifest")
    c.require(
        prerequisite(output, complete["build_manifest"], case)
        == complete["prior_independent_receipts"],
        "independent_case_order",
    )
    for target, source in (("harness.exe", "fixture-host.exe"), ("probe.exe", "handle-probe.exe")):
        c.require(
            (attempt / target).read_bytes() == (build / source).read_bytes(), "executed_image_copy"
        )
    for role, expected in WORKERS.items():
        c.require(
            c.sha((attempt / (role + ".exe")).read_bytes()) == expected, "unchanged_worker_copy"
        )
    for leaf, expected in {
        "smuggled-read.txt": b"R" * 32,
        "smuggled-write.txt": b"S" * 32,
        "ambient-shared.txt": b"Synthetic resource shared with all LPACs",
        "request.bin": b"",
    }.items():
        c.require((attempt / leaf).read_bytes() == expected, "independent_fixture_bytes")
    values = {r["native"]: r["value"] for r in record["observations"] if "value" in r}
    identities = {}
    for i, name in enumerate(("read", "write")):
        identities[name] = fixture_file_identity(attempt / f"smuggled-{name}.txt")
        for key, value in identities[name].items():
            c.require(values[f"a1_control_h{i}_" + key] == value, "independent_fixture_identity")
    cleaned = verify_cleanup(attempt, record["observations"], record["helper_identity"]["pid"])
    storage_absent(attempt)
    receipt = {
        "schema": "daf-a5-independent/v1",
        "case": case,
        "independently_verified": True,
        "qualified": False,
        "completion_sha256": c.sha(raw),
        "result_sha256": c.sha(result_raw),
        "build_manifest": complete["build_manifest"],
        "verifier_sha256": c.sha(Path(__file__).read_bytes()),
        "inspection": checked,
        "cleanup_readback": cleaned,
        "fixture_file_identities": identities,
        "fixture_bytes_unchanged": True,
        "owned_registry_storage_independently_absent": True,
        "native_processes_launched_by_readback": 0,
    }
    path = output / f"{case}-independent.json"
    publish(path, receipt)
    receipt_hash = c.sha(path.read_bytes())
    if case == NAMES[-1]:
        publish(
            output / "exercise-completion.json",
            {
                "schema": "daf-a5-exercise-completion/v1",
                "qualified": False,
                "execution_authority": False,
                "native_executions": 8,
                "retries": 0,
                "results": {name: "PASS" for name in NAMES},
                "receipts": [
                    *complete["prior_independent_receipts"],
                    {"case": case, "sha256": receipt_hash},
                ],
            },
        )
    return {"case": case, "independently_verified": True, "receipt_sha256": receipt_hash}


if __name__ == "__main__":
    c.require(len(sys.argv) == 3 and sys.argv[2] in NAMES, "a5_readback_arguments")
    output, case = Path(sys.argv[1]).resolve(), sys.argv[2]
    c.require(output.is_relative_to(FOUNDATION.parents[1] / "dist"), "readback_owned_root")
    c.require(not (output / f"{case}-independent.json").exists(), "readback_already_recorded")
    try:
        print(json.dumps(verify(output, case)))
    except Exception as error:
        failure = {"type": type(error).__name__, "errno": getattr(error, "errno", None)}
        if isinstance(error, (c.Refused, diagnostic.InvalidObservation)):
            failure["stage"] = str(error)
        publish(output / f"{case}-independent-failure.json", failure)
        if not (output / "STOP.json").exists():
            stop(output, case, failure)
        print(json.dumps({"case": case, "independently_verified": False, "failure": failure}))
        raise SystemExit(1) from None
