"""Independent original-byte readback; never launches, retries or repairs a case."""

import a8_observations as diagnostic
from a8_qualify import stop
from qualify import a, c, publish


def verify(output, case, resource_readback):
    """Simulation-only adapter; live native readback remains separately gated."""
    c.require(not (output / "STOP.json").exists(), "irreversible_stop")
    result_raw = (output / f"{case}-result.json").read_bytes()
    result = c.load(result_raw, 100000)
    c.require(
        result["case"] == case and result["mode"] == "simulated", "a8_native_readback_not_activated"
    )
    try:
        evidence = result["evidence"]
        for name, field in (("stdout.capture", "stdout"), ("stderr.jsonl", "stderr")):
            raw = (output / f"{case}-{name}").read_bytes()
            c.require(
                len(raw) == evidence[field]["bytes"] and c.sha(raw) == evidence[field]["sha256"],
                "capture_identity",
            )
        original = a.observations((output / f"{case}-stderr.jsonl").read_bytes())
        c.require(original == evidence["observations"], "original_observations")
        checked = diagnostic.validate({**evidence, "independent_cleanup": resource_readback()})
        c.require(
            checked == result["control"] and result["status"] == "expected_control_observed",
            "control_identity",
        )
        claim = c.load((output / f"{case}-claimed.json").read_bytes(), 100000)
        c.require(
            claim == c.load((output / f"{case}-started.json").read_bytes(), 100000), "claim_binding"
        )
        for key, value in claim.items():
            c.require(result[key] == value, "result_binding")
        receipt = {
            "schema": "daf-a8-independent/v1",
            "case": case,
            "mode": "simulated",
            "build_manifest": result["build_manifest"],
            "result_sha256": c.sha(result_raw),
            "independently_verified": True,
            "qualified": False,
            "execution_authority": False,
            "control": checked,
            "native_processes_launched": 0,
        }
        publish(output / f"{case}-independent.json", receipt)
        return receipt
    except Exception as error:
        stop(
            output,
            case,
            {"stage": "independent_readback", "type": type(error).__name__},
            "simulated",
        )
        raise


if __name__ == "__main__":
    raise PermissionError("A8 native verification activation requires separate Product review")
