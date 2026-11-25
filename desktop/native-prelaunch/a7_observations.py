"""Independent A7 evidence. Complete snapshots do not imply consistent inventories."""

import json
from collections import Counter
from pathlib import Path

from a7_cases import NAMES, specification
from handle_observations import InvalidObservation as InvalidObservation
from handle_observations import require

DEADLINE_MS = 5000
MAX_HANDLES = 16
COMMON_SHAPE = json.loads(Path(__file__).with_name("a7-common-shape.json").read_text("utf-8"))


def evidence_bound(rows):
    """Worst permitted scalar widths and CRLF; fixed keys, no native execution."""
    total = 0
    for row in rows:
        worst = {
            key: (
                2**64 - 1
                if type(value) is int
                else False
                if type(value) is bool
                else "S-" + "1" * 182
                if key == "sid"
                else value
            )
            for key, value in row.items()
        }
        total += len((json.dumps(worst, separators=(",", ":")) + "\r\n").encode("utf-8"))
    return total


def validate(record):
    case = record.get("case")
    require(case in NAMES, "a7_case")
    sequence, number, mutation, handle_count = specification(case)
    require(record.get("sequence") == sequence and record.get("role") == "probe", "a7_sequence")
    require(record.get("cleanup") == "confirmed", "cleanup")
    require(record.get("helper_exit") == 0, "helper_exit")
    require(not record.get("parent_deadline_exceeded"), "overall_deadline")
    require(record.get("elapsed_ms", 30000) < 30000, "attempt_bound")
    require(record.get("synthetic_resources_unchanged") is True, "resource_change")
    require(record.get("stdout", {}).get("bytes") == 0, "suspended_child_output")
    require(not record.get("stdout", {}).get("overflow", True), "stdout_bound")
    require(not record.get("stderr", {}).get("overflow", True), "stderr_bound")
    rows = record["observations"]
    common = [row for row in rows if not row["native"].startswith(("a3_", "a7_"))]
    shape = Counter(
        (
            row["native"],
            tuple(
                sorted((key, type(value).__name__) for key, value in row.items() if key != "native")
            ),
        )
        for row in common
    )
    wanted = Counter(
        {
            (row["native"], tuple(sorted(row["fields"].items()))): row["count"]
            for row in COMMON_SHAPE
        }
    )
    require(shape == wanted, "closed_common_shape")
    for row in common:
        for key, value in row.items():
            if type(value) is int:
                require(0 <= value < 2**64, "common_integer_bound")
            if key == "sid":
                require(value.isascii() and len(value) <= 184, "sid_bound")
    require(evidence_bound(rows) <= 32768, "evidence_byte_budget")
    host = {}
    for row in rows:
        key = row["native"]
        if key.startswith(("a3_", "a7_")):
            require(set(row) == {"native", "value"}, "closed_diagnostic_row")
        require(key not in {"child_resumed", "host_failure"}, "unexpected_execution_or_failure")
        require(not key.startswith("gate_refusal_"), "native_refusal")
        if "value" in row and key != "restore_profile_acl":
            require(key not in host and type(row["value"]) is int, "duplicate_or_invalid_row")
            require(0 <= row["value"] < 2**64, "numeric_bound")
            host[key] = row["value"]

    expected = set()

    def equal(key, value):
        expected.add(key)
        require(host.get(key) == value, key)

    def positive(key):
        expected.add(key)
        require(type(host.get(key)) is int and host[key] > 0, key)
        return host[key]

    fixed = {
        "host_elevated": 0,
        "host_appcontainer": 0,
        "appcontainer": 1,
        "final_elevated": 0,
        "CreateRestrictedToken_flags": 9,
        "job_at_creation": 1,
        "job_limit_flags": 8458,
        "job_process_limit": 1,
        "job_memory_bytes": 134217728,
        "job_cpu_100ns": 20000000,
        "capability_count": 1,
        "prelaunch_image_verified": 1,
        "launched_image_independently_verified": 1,
        "hostile_handles_inheritable": 5,
        "hostile_positive_controls": 1,
        "a1_control_effects_verified_and_restored": 1,
        "a3_attribute_mask": 31,
        "a3_attribute_count": 5,
        "a3_inheritance_count": 3,
        "a3_capture_flags": 132,
        "a3_context_flags": 0,
        "a3_inspection_deadline_ms": DEADLINE_MS,
        "a3_termination_deadline_ms": 3000,
        "a3_inspector_finished": 1,
        "a3_inspector_wait": 0,
        "a3_deadline_expired": 0,
        "a3_terminate_job_ok": 1,
        "a3_terminate_job_error": 0,
        "a3_process_wait": 0,
        "a3_exit_query_ok": 1,
        "a3_child_exit": 123,
        "a3_accounting_ok": 1,
        "a3_active_processes": 0,
        "a3_memory_query_ok": 1,
        "a3_child_resumed": 0,
        "a3_inspection_passed": int(not mutation),
        "a3_last_stage": 2 if mutation else 1,
        "a3_hostile_event_after_child": 258,
        "restore_registry_acl": 0,
        "delete_explicitly_created_registry_storage": 0,
        "delete_synthetic_registry_key": 0,
        "delete_owned_profile_hresult": 0,
        "delete_synthetic_credential": 1,
    }
    for key, value in fixed.items():
        equal(key, value)
    expected.update(
        (
            "a3_inspection_elapsed_ms",
            "a3_termination_elapsed_ms",
            "a3_user_cpu_100ns",
            "a3_peak_memory_bytes",
        )
    )
    require(host.get("a3_inspection_elapsed_ms", DEADLINE_MS) < DEADLINE_MS, "inspection_deadline")
    require(host.get("a3_termination_elapsed_ms", 3001) <= 3000, "termination_deadline")
    require(host.get("a3_user_cpu_100ns", 20000001) <= 20000000, "cpu_limit")
    require(host.get("a3_peak_memory_bytes", 134217729) <= 134217728, "memory_limit")
    pid, tid, creation = [positive("a3_expected_" + k) for k in ("pid", "tid", "creation")]
    helper = positive("helper_pid")
    external = record.get("helper_identity", {})
    require(
        external.get("query_ok") is True and external.get("error") == 0, "external_helper_query"
    )
    require(external.get("pid") == helper and helper != pid, "external_helper_pid")
    helper_creation = external.get("creation")
    require(type(helper_creation) is int and helper_creation > 0, "external_helper_creation")
    equal("a1_control_h4_process_pid", helper)
    equal("a1_control_h4_process_creation", helper_creation)
    frequency = positive("a7_qpc_frequency")
    require(frequency <= 10**12, "counter_frequency")
    for key, limit in (("inspection", 5000), ("termination", 3000)):
        expected.add(f"a7_{key}_qpc_ticks")
        ticks = host.get(f"a7_{key}_qpc_ticks")
        require(type(ticks) is int and 0 <= ticks * 1000 < limit * frequency, "counter_elapsed")
    independent = record.get("independent_cleanup", {})
    for key in (
        "profile_absent",
        "synthetic_key_absent",
        "synthetic_credential_absent",
        "owned_storage_absent",
    ):
        require(independent.get(key) is True, "independent_" + key)
    processes = independent.get("processes", [])
    require(
        len(processes) == 2 and {p.get("pid") for p in processes} == {pid, helper},
        "independent_pids",
    )
    for process in processes:
        require(process.get("terminated") is True, "independent_termination")
        if "open_error" in process:
            require(process["open_error"] == 87, "independent_absence")
        else:
            require(
                process.get("wait") == 0
                and process.get("exit") == (123 if process["pid"] == pid else 0),
                "independent_exit",
            )
    for key in ("a3_created_pid", "child_pid"):
        equal(key, pid)
    equal("a3_created_tid", tid)
    pipes = [positive(f"a3_pipe_{i}") for i in range(3)]
    require(len(set(pipes)) == 3, "distinct_pipes")

    def numeric(key, minimum=0, maximum=2**64 - 1):
        expected.add(key)
        require(type(host.get(key)) is int and minimum <= host[key] <= maximum, key)
        return host[key]

    def fields(prefix, values):
        for key, value in values.items():
            equal(prefix + key, value)

    fixed_a7 = {
        "case": number,
        "sequence": sequence,
        "controlled_stop": 1,
        "expected_result_verified": 1,
        "tick_unit_ms": 1,
        "qpc_queries_ok": 1,
        "boundary_calls": 1,
        "boundary_complete": 1,
        "inward_attempts": int(mutation),
        "requested_access": 0x100000 if mutation else 0,
        "requested_inherit": 0,
        "requested_options": 0,
        "event_before": 258,
        "boundary_before_ok": 1,
        "boundary_before_value": 3,
        "boundary_after_ok": 1,
        "boundary_after_value": handle_count,
        "shared_passed": int(not mutation),
        "shared_inventory_complete": int(not mutation),
        "shared_failure": 120 if mutation else 0,
        "post_count_ok": 1,
        "post_count_value": handle_count,
        "witness_complete": 1,
        "rows_bounded": 1,
    }
    fields("a7_", fixed_a7)
    if mutation:
        equal("a3_failure", 120)
        target = positive("a7_target")
        require(target not in pipes and target != 2**64 - 1, "new_target_slot")
        fields("a7_", {"inward_ok": 1, "inward_error": 0})
    else:
        equal("a3_inventories_consistent", 1)
        equal("a7_target", 0)
        target = 0
    points = [numeric("a7_boundary_begin_qpc")]
    if mutation:
        points += [numeric("a7_inward_begin_qpc"), numeric("a7_inward_end_qpc")]
    points += [numeric("a7_boundary_end_qpc"), numeric("a7_post_end_qpc")]
    require(points == sorted(points), "boundary_order")
    require(points[-1] - points[0] <= host["a7_inspection_qpc_ticks"], "boundary_deadline")
    identity = {
        "pid": pid,
        "tid": tid,
        "thread_owner": pid,
        "creation": creation,
        "times_error": 0,
        "process_wait": 258,
    }
    fields("a7_boundary_", identity)
    fields("a7_post_", identity)
    if not mutation:
        fields("a3_final_", identity)
    inventories = []
    ordered = []
    for round_number in (0, 1):
        prefix = f"a3_s{round_number}_"
        count = handle_count if round_number else 3
        fields(prefix, identity)
        fields(
            prefix,
            {
                "count_before_ok": 1,
                "count_before": count,
                "capture_status": 0,
                "handle_query_status": 0,
                "thread_query_status": 0,
                "handles_captured": count,
                "threads_captured": 1,
                "handle_marker_status": 0,
                "thread_marker_status": 0,
                "thread_walk_status": 0,
                "thread_pid": pid,
                "thread_tid": tid,
                "suspend_count": 1,
                "thread_exit": 259,
                "context_bytes": 0,
                "thread_end": 259,
                "handle_end": 259,
                "entries": count,
                "count_after_ok": 1,
                "count_after": count,
                "handle_marker_free": 0,
                "thread_marker_free": 0,
                "snapshot_free": 0,
                "policy_ok": 1,
                "policy_error": 0,
                "policy_flags": 3,
                "policy_raise": 1,
                "policy_permanent": 1,
            },
        )
        inventory, order = {}, []
        for i in range(count):
            entry = f"{prefix}h{i}_"
            raw = positive(entry + "raw")
            require(raw not in inventory and raw != 2**64 - 1, "duplicate_or_invalid_entry")
            event = mutation and round_number == 1 and raw == target
            require(event or raw in pipes, "unexpected_object")
            values = {
                "copy_error": 0,
                "checked": 255,
                "hostile": 8 if event else 0,
                "pipes": 0 if event else 1 << pipes.index(raw),
            }
            fields(entry, values)
            inventory[raw] = {key: values[key] for key in ("hostile", "pipes")}
            order.append(raw)
        require(
            set(inventory) == set(pipes) | ({target} if mutation and round_number else set()),
            "complete_inventory",
        )
        inventories.append(inventory)
        ordered.append(order)
    added = set(inventories[1]) - set(inventories[0])
    removed = set(inventories[0]) - set(inventories[1])
    require(added == ({target} if mutation else set()) and not removed, "exact_set_difference")
    for raw in pipes:
        require(inventories[0][raw] == inventories[1][raw], "original_pipes_unchanged")

    def witness(prefix, raw, event):
        values = {
            "raw": raw,
            "copy_ok": 1,
            "copy_error": 0,
            "checked": 255,
            "hostile": 8 if event else 0,
            "pipes": 0 if event else 1 << pipes.index(raw),
            "type_status": 0,
            "kind": 3 if event else 7,
        }
        fields(prefix, values)
        values["type_bytes"] = numeric(prefix + "type_bytes", 104, 1024)
        if event:
            more = {"basic_status": 0, "basic_bytes": 56, "access": 0x100000, "event_wait": 258}
        else:
            more = {"file_type": 3}
        fields(prefix, more)
        return {**values, **more}

    boundary_witness = witness("a7_boundary_w_", target, True) if mutation else None
    post_witness = {}
    for i, raw in enumerate(ordered[1]):
        post_witness[raw] = witness(f"a7_post_h{i}_", raw, mutation and raw == target)
    state_keys = {key for key in expected if key.startswith(("a3_s0_", "a3_s1_", "a3_final_"))}
    state_keys |= {
        "a3_capture_flags",
        "a3_context_flags",
        "a3_failure" if mutation else "a3_inventories_consistent",
    }
    outside_audit = {
        "case",
        "sequence",
        "controlled_stop",
        "expected_result_verified",
        "tick_unit_ms",
        "qpc_queries_ok",
        "qpc_frequency",
        "inspection_qpc_ticks",
        "termination_qpc_ticks",
        "published_rows",
        "rows_bounded",
    }
    audit_keys = {key for key in expected if key.startswith("a7_") and key[3:] not in outside_audit}
    require(
        len(audit_keys) <= 128 and len(state_keys) + len(audit_keys) <= 384, "evidence_row_budget"
    )
    equal("a7_published_rows", len(state_keys) + len(audit_keys))
    require(
        {key for key in host if key.startswith(("a3_", "a7_"))}
        == {key for key in expected if key.startswith(("a3_", "a7_"))},
        "closed_a7_snapshot_schema",
    )
    for i, control_kind in enumerate((1, 1, 2, 3, 4)):
        prefix = f"a1_control_h{i}_"
        for key, value in {
            "begin": 1,
            "info_ok": 1,
            "info_error": 0,
            "flags": 1,
            "duplicate_ok": 1,
            "duplicate_error": 0,
            "type_status": 0,
            "type": control_kind,
            "known_reference": 1,
            "intended_identity": 1,
            "operation_attempted": 1,
            "operation_ok": 1,
            "operation_error": 0,
            "outcome": 3,
            "complete": 1,
        }.items():
            equal(prefix + key, value)
        positive(prefix + "raw")
    for key, value in {
        "a1_control_h0_read_marker": 1,
        "a1_control_h0_operation_bytes": 32,
        "a1_control_h1_operation_bytes": 1,
        "a1_control_h2_operation_bytes": 1,
        "a1_control_h2_mapping_flush_ok": 1,
        "a1_control_h2_mapping_unmap_ok": 1,
        "a1_control_h2_mapping_flush_error": 0,
        "a1_control_h4_duplicated_read_identity": 1,
        "a1_control_h4_duplicated_read_marker": 1,
        "a1_control_h4_duplicated_read_error": 0,
    }.items():
        equal(key, value)
    restored = [r["value"] for r in rows if r["native"] == "restore_profile_acl"]
    require(len(restored) == 7 and all(v == 0 for v in restored), "profile_acl_cleanup")
    for key, allowed, error in (
        ("native_ambient_write", False, 5),
        ("native_explicit_dual_write", True, 0),
    ):
        found = [r for r in rows if r["native"] == key]
        require(
            len(found) == 1 and found[0]["allowed"] is allowed and found[0]["error"] == error, key
        )

    def sid(key):
        found = [r for r in rows if r["native"] == key and "sid" in r]
        require(len(found) == 1, key)
        return found[0]["sid"]

    require(sid("requested_attempt_sid") == sid("final_child_restricted_sids"), "attempt_sid")
    for i in (0, 1):
        prefix = f"a1_control_h{i}_"
        fields(prefix, {"regular_32_bytes": 1, "file_type": 1, "id_ok": 1, "id_error": 0})
        positive(prefix + "volume")
        low, high = numeric(prefix + "file_low"), numeric(prefix + "file_high")
        require(low or high, "fixture_file_identity")
    return {
        "inventories": inventories,
        "added": sorted(added),
        "removed": sorted(removed),
        "boundary_witness": boundary_witness,
        "post_witness": post_witness,
        "target": target,
        "candidate_passed": not mutation,
        "inventoryComplete": not mutation,
        "refusal_code": 120 if mutation else 0,
        "child_resumed": False,
        "qualified": False,
        "execution_authority": False,
        "control": "persistent_event_insertion" if mutation else "sham_boundary",
    }


def nonpass_classification(record):
    """A non-pass always stops. This label never upgrades an execution result."""
    if record.get("case") != "A7-15":
        return "FAIL"
    values = {r.get("native"): r.get("value") for r in record.get("observations", [])}
    if (
        record.get("parent_deadline_exceeded")
        or record.get("cleanup") != "confirmed"
        or record.get("helper_exit") not in (0, 1)
        or record.get("stdout", {}).get("bytes", 1) != 0
        or record.get("stdout", {}).get("overflow", True)
        or record.get("stderr", {}).get("overflow", True)
        or values.get("a3_deadline_expired") != 0
        or values.get("a3_child_resumed") != 0
        or record.get("synthetic_resources_unchanged") is not True
    ):
        return "FAIL"
    # Successful API alone is insufficient. Both complete tables and a real
    # outward event witness are required before calling this a missed detection.
    target = values.get("a7_target")
    first = {values.get(f"a3_s0_h{i}_raw") for i in range(3)}
    second = {values.get(f"a3_s1_h{i}_raw") for i in range(4)}
    complete = all(
        values.get(f"a3_s{n}_{key}") == count
        for n, count in ((0, 3), (1, 4))
        for key in ("count_before", "handles_captured", "entries", "count_after")
    )
    observed = (
        complete
        and target
        and None not in first | second
        and second - first == {target}
        and first <= second
        and values.get("a7_boundary_w_hostile") == 8
        and values.get("a7_boundary_w_checked") == 255
        and values.get("a7_boundary_w_access") == 0x100000
    )
    if observed and (values.get("a7_shared_passed") == 1 or values.get("a3_failure") != 120):
        return "FAIL"
    return "INCONCLUSIVE"
