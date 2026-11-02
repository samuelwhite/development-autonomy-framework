"""Independent TC-0 verification: raw inspector rows plus live parent readback."""

from pathlib import Path

import a3_observations
from ae5_contract import (
    ACK,
    HELPER_MS,
    MAX_CONTROL,
    MAX_STDERR,
    OUTER_MS,
    canonical,
    decode,
    exact,
    handoff,
    integer,
    process,
    require,
)
from ae5_verify import ledger_prefix
from ae51_contract import acknowledgement, binding, digest, load
from ae51_snapshot import validate_snapshot


def frames(raw):
    require(type(raw) is bytes and len(raw) <= MAX_CONTROL, "control_bound")
    at, result = 0, []
    while at < len(raw):
        require(at + 4 <= len(raw), "partial_control_header")
        size = int.from_bytes(raw[at : at + 4], "little")
        at += 4
        require(0 < size <= 32768 and at + size <= len(raw), "partial_control_frame")
        result.append(decode(raw[at : at + size]))
        at += size
    require(len(result) <= 256, "control_count")
    return result


def original_rows(raw):
    require(
        type(raw) is bytes and 0 < len(raw) <= MAX_STDERR and raw.endswith(b"\n"), "stderr_complete"
    )
    rows = [load(line, 32768) for line in raw.splitlines()]
    require(
        len(rows) <= 512
        and all(type(row) is dict and type(row.get("native")) is str for row in rows),
        "native_rows",
    )
    return rows


def verify_observations(record, bound, control, stderr, acks, live):
    """Returns checked observations only, never an execution receipt or approval."""
    exact(
        record,
        (
            "schema",
            "case",
            "binding",
            "qualified",
            "execution_authority",
            "resumes",
            "parent",
            "started",
            "helper_elapsed_ms",
            "elapsed_ms",
            "custody",
            "snapshot",
            "custody_verified_ms",
            "inspection_deadline",
            "timeline",
            "ledger",
            "readback",
            "control_complete",
            "stderr_complete",
            "control_overflow",
            "stderr_overflow",
            "stop_reason",
            "termination_requests",
            "failure",
            "captures",
        ),
    )
    require(
        record["schema"] == "daf-ae51-observation/v1" and record["binding"] == binding(bound),
        "evidence_binding",
    )
    require(
        record["case"] == "TC-0"
        and record["execution_authority"] is False
        and record["qualified"] is False
        and type(record["resumes"]) is int
        and record["resumes"] == 0,
        "no_execution_authority",
    )
    require(record["readback"] == live, "independent_readback_difference")
    exact(live, ("helper", "child", "active", "total", "cleanup"))
    for key in ("helper", "child"):
        exact(live[key], ("identity", "wait", "exit"))
        process(live[key]["identity"])
        integer(live[key]["exit"], 0, 2**32 - 1)
    integer(live["active"], 0, 2)
    require(type(live["total"]) is int and live["total"] == 2, "unexpected_process_count")
    for key in (
        "started",
        "helper_elapsed_ms",
        "elapsed_ms",
        "custody_verified_ms",
        "inspection_deadline",
    ):
        integer(record[key])
    exact(record["captures"], ("control", "stderr", "acks"))
    for name, raw in (("control", control), ("stderr", stderr), ("acks", acks)):
        require(
            record["captures"][name] == {"bytes": len(raw), "sha256": digest(raw)},
            "original_capture_identity",
        )
    require(live["helper"]["wait"] == live["child"]["wait"] == "signalled", "ambiguous_exit")
    require(live["helper"]["exit"] == 0 and live["child"]["exit"] == 123, "wrong_exit")
    require(live["active"] == 0 and live["cleanup"] is True, "cleanup_or_tree_unresolved")
    require(
        record["control_complete"] is True
        and record["stderr_complete"] is True
        and record["control_overflow"] is False
        and record["stderr_overflow"] is False,
        "incomplete_capture",
    )
    require(
        record["failure"] is None and record["stop_reason"] in (None, "helper_exit"),
        "unexpected_stop",
    )
    require(
        record["helper_elapsed_ms"] < HELPER_MS and record["elapsed_ms"] < OUTER_MS,
        "absolute_deadline",
    )
    rows = original_rows(stderr)
    messages = frames(control)
    require([row["seq"] for row in messages] == list(range(1, len(messages) + 1)), "wire_sequence")
    require(all(row["exercise"] == bound["exercise"] for row in messages), "wire_exercise")
    custody = [row for row in messages if row["kind"] == "custody"]
    cleanup = [row for row in messages if row["kind"] == "cleanup"]
    require(
        len(custody) == len(cleanup) == 1 and messages[-1] == cleanup[0], "custody_cleanup_count"
    )
    require(custody[0]["seq"] < cleanup[0]["seq"], "cleanup_before_custody")
    offer = handoff(custody[0]["data"])
    observed = record["custody"]
    from ae5_contract import Decision

    decision = Decision(record["started"], live["helper"]["identity"])
    decision.establish(observed, record["custody_verified_ms"])
    require(observed["child"] == live["child"]["identity"], "retained_child_binding")
    validate_snapshot(record["snapshot"], offer)
    require(len(acks) == (len(messages) + 1) * ACK.size, "ack_completeness")
    timeline = record["timeline"]
    written = [row for row in timeline if row["event"] == "ack_written"]
    require(len(written) == len(messages) + 1, "ack_timing_completeness")
    for index, row in enumerate(written):
        require(row["sequence"] == index, "ack_sequence")
        due = (
            record["inspection_deadline"]
            if index == custody[0]["seq"]
            else record["started"] + HELPER_MS
        )
        verified = (
            record["custody_verified_ms"] if index == custody[0]["seq"] else record["started"]
        )
        acknowledgement(
            acks[index * ACK.size : (index + 1) * ACK.size],
            bound["exercise"],
            record["parent"],
            index,
            verified,
            row["ms"],
            due,
        )
    require(
        record["inspection_deadline"] - record["custody_verified_ms"] <= 5000,
        "inspection_deadline_reset",
    )
    require(written[cleanup[0]["seq"]]["ms"] < record["inspection_deadline"], "late_cleanup_ack")
    ledger = ledger_prefix(record["ledger"], bound["exercise"])
    require(ledger["complete"], "incomplete_ledger")
    kinds = [item["intent"]["resource"]["kind"] for item in ledger["operations"]]
    require(
        kinds.count("profile") == kinds.count("credential") == kinds.count("desktop") == 1
        and kinds.count("registry") == 2
        and kinds.count("acl") >= 15,
        "resource_coverage",
    )
    require(len(messages) == len(record["ledger"]) + 2, "ledger_wire_coverage")
    for wire, persisted in zip(messages[:-2], record["ledger"], strict=True):
        require(wire["kind"] == persisted["kind"], "ledger_wire_order")
        if wire["kind"] == "intent":
            require(
                wire["data"]["kind"] == persisted["resource"]["kind"]
                and wire["data"]["name"] == persisted["resource"]["name"],
                "ledger_wire_resource",
            )
        else:
            require(
                wire["data"]["ok"] == persisted["outcome"]["ok"]
                and wire["data"]["created"] == persisted["outcome"]["created"],
                "ledger_wire_commit",
            )
    processes = [
        {**live[key]["identity"], "wait": 0, "exit": live[key]["exit"], "terminated": True}
        for key in ("helper", "child")
    ]
    old_shape = {
        "cleanup": "confirmed",
        "helper_exit": 0,
        "parent_deadline_exceeded": False,
        "elapsed_ms": record["helper_elapsed_ms"],
        "synthetic_resources_unchanged": True,
        "stdout": {"bytes": 0, "overflow": False},
        "stderr": {"overflow": False},
        "observations": rows,
        "independent_cleanup": {
            "profile_absent": True,
            "synthetic_key_absent": True,
            "synthetic_credential_absent": True,
            "owned_storage_absent": True,
            "processes": processes,
        },
    }
    # Pure historical validator only; no historical runner/collector is invoked.
    a3_observations.validate(old_shape)
    numeric = {row["native"]: row["value"] for row in rows if "value" in row}
    require(
        numeric["a3_expected_creation"] == live["child"]["identity"]["creation"],
        "creation_confusion",
    )
    witness = {row["value"]: row["pipes"] for row in record["snapshot"]["handles"]}
    for round_number in (0, 1):
        actual = {
            numeric[f"a3_s{round_number}_h{i}_raw"]: numeric[f"a3_s{round_number}_h{i}_pipes"]
            for i in range(3)
        }
        require(actual == witness, "parent_helper_snapshot_difference")
    return {
        "observations_sha256": digest(canonical(record)),
        "qualified": False,
        "execution_authority": False,
    }


def cleanup_readback(backend, baseline, fixtures):
    """Read-only exact resources; neither calls recovery nor deletes diagnostic artifacts."""
    from ae5_resources import (
        MAPPINGS,
        STORAGE,
        credential_absent,
        descriptor,
        desktop_absent,
        open_exact,
        registry_absent,
    )

    b = backend
    exits, active = b.exits()
    require(
        active == 0 and all(row["wait"] == "signalled" for row in exits.values()), "tree_unresolved"
    )
    profile = b.profile
    require(profile is not None and profile["storage"] is not None, "profile_identity_missing")
    require(
        not Path(profile["storage"]).exists()
        and registry_absent(MAPPINGS + "\\" + profile["sid"])
        and registry_absent(STORAGE + "\\" + profile["sid"])
        and registry_absent("Software\\" + profile["name"])
        and credential_absent(b, profile["name"])
        and desktop_absent(profile["name"] + ".Desktop"),
        "owned_cleanup_unresolved",
    )
    expected_leaves = {*fixtures, "runtime", "owned-profile.txt"}
    actual_leaves = set()
    for index, path in enumerate(b.root.iterdir()):
        require(index < 64, "fixture_inventory_bound")
        actual_leaves.add(path.name)
    require(actual_leaves == expected_leaves, "unexpected_fixture_inventory")
    require(not any((b.root / "runtime").iterdir()), "unexpected_runtime_content")
    marker_handle, _ = open_exact(b, str(b.root / "owned-profile.txt"))
    try:
        with (b.root / "owned-profile.txt").open("rb") as marker_file:
            marker = marker_file.read(8193)
        require(len(marker) <= 8192, "profile_marker_bound")
        folder = next(
            item["outcome"]["identity"]["folder"]
            for item in b.owned
            if item["resource"]["kind"] == "profile"
        )
        require(
            marker.decode("utf-8").splitlines() == [profile["name"], folder], "owned_profile_marker"
        )
    finally:
        b.close(marker_handle)
    for name, expected in baseline.items():
        handle, actual = open_exact(b, name, expected["identity"])
        try:
            for information, original in expected["descriptors"].items():
                require(
                    descriptor(b, handle, 1, int(information)) == original,
                    "fixture_acl_not_restored",
                )
        finally:
            b.close(handle)
    for name, expected in fixtures.items():
        require(digest((b.root / name).read_bytes()) == expected, "fixture_bytes_changed")
    return {**exits, "active": active, "total": b.last_total_processes, "cleanup": True}


def fixture_baseline(backend, paths):
    from ae5_resources import descriptor, open_exact

    result = {}
    for path in paths:
        handle, identity = open_exact(backend, str(path))
        try:
            info = (4, 16) if path.name in {"dual-grant.txt", "ambient-shared.txt"} else (4,)
            result[str(path)] = {
                "identity": identity,
                "descriptors": {str(i): descriptor(backend, handle, 1, i) for i in info},
            }
        finally:
            backend.close(handle)
    return result
