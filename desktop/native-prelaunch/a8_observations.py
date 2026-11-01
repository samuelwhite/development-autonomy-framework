"""Closed A8 control evidence. Simulations never qualify native deadlines."""

from collections import Counter

from a7_observations import COMMON_SHAPE, evidence_bound
from handle_observations import InvalidObservation as InvalidObservation
from handle_observations import require

DEADLINE_MS = 5000
MAX_HANDLES = 16

SUPERVISOR = """case sequence gate_initial gate_flags entered_flags qpc_frequency
observer_start_tick supervisor_tid start_tick start_qpc wait_error wait_qpc
raw_deadline done stop inspector_cut observer_cut shared_cut kill_qpc terminated_qpc
shared_emit witness_wait witness_exit_ok witness_exit witness_pid witness_times_ok
witness_creation witness_tid witness_thread_ok witness_thread_exit witness_job_ok
witness_active witness_qpc observer_thread_wait""".split()
INSPECTOR = (
    "inspector_tid boundary_ready call_qpc call_return call_error return_qpc ack_wait ack_qpc"
).split()
OBSERVER = "observer_tid entered_wait entered_error gate_wait observed_qpc".split()
RECORD_FIELDS = set(
    """schema case sequence role mode qualified execution_authority
capture_complete forced_outer_termination parent_deadline_exceeded cleanup helper_exit
elapsed_ms outer_elapsed_ms synthetic_resources_unchanged stdout stderr observations
independent_cleanup
helper_identity""".split()
)


def validate_shape(record, stall):
    require(set(record) == RECORD_FIELDS, "closed_record")
    rows = record["observations"]
    common = [row for row in rows if not row["native"].startswith(("a3_", "a8_"))]
    shape = Counter(
        (r["native"], tuple(sorted((k, type(v).__name__) for k, v in r.items() if k != "native")))
        for r in common
    )
    wanted = Counter(
        {(r["native"], tuple(sorted(r["fields"].items()))): r["count"] for r in COMMON_SHAPE}
    )
    if stall:
        wanted[("host_failure", (("value", "int"),))] = 1
    require(shape == wanted, "closed_common_shape")
    for row in rows:
        require(type(row.get("native")) is str, "row_key")
        if row["native"].startswith(("a3_", "a8_")):
            require(set(row) == {"native", "value"}, "closed_diagnostic_row")
        for key, value in row.items():
            if type(value) is int:
                require(0 <= value < 2**64, "scalar_width")
            if key == "sid":
                require(type(value) is str and value.isascii() and len(value) <= 184, "sid_bound")
    require(evidence_bound(rows) <= 32768, "stderr_budget")
    # Successful suspended-child evidence permits no stdout at all. Raw capture
    # keeps the unchanged accepted contracts.MAX_OUTPUT, as in A3/A7.
    for stream, limit in (("stdout", 0), ("stderr", 32768)):
        value = record[stream]
        require(set(value) == {"bytes", "sha256", "overflow"}, "closed_capture")
        require(type(value["bytes"]) is int and 0 <= value["bytes"] <= limit, "capture_bytes")
        require(
            type(value["sha256"]) is str
            and len(value["sha256"]) == 64
            and all(c in "0123456789abcdef" for c in value["sha256"]),
            "capture_hash",
        )
    require(record["parent_deadline_exceeded"] is False, "parent_deadline")
    require(
        type(record["outer_elapsed_ms"]) is int
        and record["elapsed_ms"] <= record["outer_elapsed_ms"] < 35000,
        "outer_cleanup_bound",
    )
    helper = record["helper_identity"]
    require(set(helper) == {"pid", "creation", "query_ok", "error"}, "helper_identity_shape")
    require(
        helper["query_ok"] is True and helper["error"] == 0 and helper["creation"] > 0,
        "helper_identity",
    )
    host = {r["native"]: r["value"] for r in rows if "value" in r}
    require(
        helper["pid"] == host["helper_pid"] == host["a1_control_h4_process_pid"], "helper_binding"
    )
    require(helper["creation"] == host["a1_control_h4_process_creation"], "helper_creation")
    for process in record["independent_cleanup"]["processes"]:
        if "open_error" not in process:
            expected = (
                host["a3_expected_creation"]
                if process["pid"] == host["a3_expected_pid"]
                else helper["creation"]
            )
            require(process.get("creation") == expected, "process_reuse_ambiguity")


def validate_private(record, host, stall, pid, tid, creation):
    keys = [
        "rows_bounded",
        "private_rows",
        *SUPERVISOR,
        *(INSPECTOR[:3] if stall else INSPECTOR),
        *OBSERVER,
    ]
    actual = [r["native"] for r in record["observations"] if r["native"].startswith("a8_")]
    require(actual == ["a8_" + key for key in keys], "closed_ordered_private_schema")
    values = {key: host["a8_" + key] for key in keys}
    state_rows = 51 if stall else 107
    fixed = {
        "rows_bounded": 1,
        "private_rows": len(keys) - 2,
        "case": int(stall),
        "sequence": 2 if stall else 1,
        "gate_initial": int(not stall),
        "gate_flags": 0,
        "entered_flags": 0,
        "wait_error": 0,
        "raw_deadline": int(stall),
        "done": int(not stall),
        "stop": int(stall),
        "inspector_cut": 3 if stall else 8,
        "observer_cut": 5,
        "shared_cut": state_rows,
        "shared_emit": state_rows,
        "witness_wait": 0,
        "witness_exit_ok": 1,
        "witness_exit": 123,
        "witness_pid": pid,
        "witness_times_ok": 1,
        "witness_creation": creation,
        "witness_tid": tid,
        "witness_thread_ok": 1,
        "witness_thread_exit": 123,
        "witness_job_ok": 1,
        "witness_active": 0,
        "observer_thread_wait": 0,
        "boundary_ready": 1,
        "entered_wait": 0,
        "entered_error": 0,
        "gate_wait": 258 if stall else 0,
    }
    if not stall:
        fixed.update(call_return=0, call_error=0, ack_wait=0)
    for key, value in fixed.items():
        require(values[key] == value, "a8_" + key)
    require(len(keys) <= 64 and state_rows + values["private_rows"] <= 384, "private_bound")
    require(all(len("a8_" + k) <= 40 for k in keys), "private_key_bound")
    threads = [values[k] for k in ("supervisor_tid", "inspector_tid", "observer_tid")]
    require(all(v > 0 for v in threads) and len(set([*threads, tid])) == 4, "distinct_threads")
    frequency = values["qpc_frequency"]
    require(frequency > 0, "qpc_frequency")
    start, call, observed, wait, kill, terminated, witness = [
        values[k]
        for k in (
            "start_qpc",
            "call_qpc",
            "observed_qpc",
            "wait_qpc",
            "kill_qpc",
            "terminated_qpc",
            "witness_qpc",
        )
    ]
    require(
        0 < start < call < observed < wait <= kill <= terminated <= witness, "unambiguous_qpc_order"
    )
    require(0 < values["observer_start_tick"] <= values["start_tick"], "observer_original_budget")
    require(
        (5000 <= (wait - start) * 1000 / frequency < 30000)
        if stall
        else (wait - start) * 1000 < 5000 * frequency,
        "real_clock_corroboration",
    )
    require((terminated - kill) * 1000 <= 3000 * frequency, "termination_qpc_bound")
    if not stall:
        require(
            call < values["return_qpc"] <= values["ack_qpc"] < wait
            and observed < values["ack_qpc"],
            "sham_ack_order",
        )
    ordered = [r["native"] for r in record["observations"]]
    require(
        ordered.index("a3_s0_snapshot_free") < ordered.index("a3_s0_policy_flags"),
        "complete_first_snapshot",
    )
    if not stall:
        require(
            ordered.index("a3_s0_policy_flags")
            < ordered.index("a3_s1_pid")
            < ordered.index("a3_final_pid")
            < ordered.index("a3_inventories_consistent"),
            "snapshot_order",
        )


def validate(record):
    stall = record.get("case") == "A8-S1"
    require(record.get("case") in ("A8-C0", "A8-S1"), "a8_case")
    require(
        record.get("sequence") == (2 if stall else 1) and record.get("role") == "probe", "a8_order"
    )
    require(record.get("mode") in ("simulated", "native"), "evidence_mode")
    require(
        record.get("qualified") is False and record.get("execution_authority") is False,
        "no_authority",
    )
    require(record.get("schema") == "daf-a8-case/v1", "a8_schema")
    require(record.get("capture_complete") is True, "capture_complete")
    require(record.get("forced_outer_termination") is False, "forced_outer_termination")
    require(record.get("cleanup") == "confirmed", "cleanup")
    require(record.get("helper_exit") == int(stall), "helper_exit")
    require(not record.get("parent_deadline_exceeded"), "overall_deadline")
    require(record.get("elapsed_ms", 30000) < 30000, "attempt_bound")
    require(record.get("synthetic_resources_unchanged") is True, "resource_change")
    require(record.get("stdout", {}).get("bytes") == 0, "suspended_child_output")
    require(not record.get("stdout", {}).get("overflow", True), "stdout_bound")
    require(not record.get("stderr", {}).get("overflow", True), "stderr_bound")
    rows = record["observations"]
    host = {}
    for row in rows:
        key = row["native"]
        require(
            key != "child_resumed" and (key != "host_failure" or stall),
            "unexpected_execution_or_failure",
        )
        require(not key.startswith("gate_refusal_"), "native_refusal")
        if "value" in row and key != "restore_profile_acl":
            require(key not in host and type(row["value"]) is int, "duplicate_or_invalid_row")
            require(0 <= row["value"] < 2**64, "numeric_bound")
            host[key] = row["value"]

    def equal(key, value):
        require(host.get(key) == value, key)

    def positive(key):
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
        "a3_inspector_finished": int(not stall),
        "a3_inspector_wait": 258 if stall else 0,
        "a3_deadline_expired": int(stall),
        "a3_terminate_job_ok": 1,
        "a3_terminate_job_error": 0,
        "a3_process_wait": 0,
        "a3_exit_query_ok": 1,
        "a3_child_exit": 123,
        "a3_accounting_ok": 1,
        "a3_active_processes": 0,
        "a3_memory_query_ok": 1,
        "a3_child_resumed": 0,
        "a3_inspection_passed": int(not stall),
        "a3_last_stage": 2 if stall else 1,
        "a3_hostile_event_after_child": 258,
        "restore_registry_acl": 0,
        "delete_explicitly_created_registry_storage": 0,
        "delete_synthetic_registry_key": 0,
        "delete_owned_profile_hresult": 0,
        "delete_synthetic_credential": 1,
    }
    if stall:
        fixed["host_failure"] = 1
    else:
        fixed.update(a3_controlled_stop=1, a3_inventories_consistent=1)
    for key, value in fixed.items():
        equal(key, value)
    elapsed = host.get("a3_inspection_elapsed_ms")
    require(
        type(elapsed) is int and (5000 <= elapsed < 30000 if stall else elapsed < 5000),
        "inspection_deadline",
    )
    require(host.get("a3_termination_elapsed_ms", 3001) <= 3000, "termination_deadline")
    require(host.get("a3_user_cpu_100ns", 20000001) <= 20000000, "cpu_limit")
    require(host.get("a3_peak_memory_bytes", 134217729) <= 134217728, "memory_limit")
    pid, tid, creation = [positive("a3_expected_" + k) for k in ("pid", "tid", "creation")]
    helper = positive("helper_pid")
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
                and process.get("exit") == (123 if process["pid"] == pid else int(stall)),
                "independent_exit",
            )
    for key in ("a3_created_pid", "child_pid"):
        equal(key, pid)
    equal("a3_created_tid", tid)
    pipes = [positive(f"a3_pipe_{i}") for i in range(3)]
    require(len(set(pipes)) == 3, "distinct_pipes")
    expected_a3 = {key for key in fixed if key.startswith("a3_")} | {
        "a3_expected_pid",
        "a3_expected_tid",
        "a3_expected_creation",
        "a3_created_pid",
        "a3_created_tid",
        "a3_inspection_elapsed_ms",
        "a3_termination_elapsed_ms",
        "a3_user_cpu_100ns",
        "a3_peak_memory_bytes",
        "a3_last_stage",
        *(f"a3_pipe_{i}" for i in range(3)),
    }
    inventories = []
    for prefix in ("a3_s0_",) if stall else ("a3_s0_", "a3_s1_", "a3_final_"):
        identity = {
            "pid": pid,
            "tid": tid,
            "thread_owner": pid,
            "creation": creation,
            "times_error": 0,
            "process_wait": 258,
        }
        for key, value in identity.items():
            equal(prefix + key, value)
            expected_a3.add(prefix + key)
        if prefix == "a3_final_":
            continue
        snapshot = {
            "count_before_ok": 1,
            "count_before": 3,
            "capture_status": 0,
            "handle_query_status": 0,
            "thread_query_status": 0,
            "handles_captured": 3,
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
            "entries": 3,
            "count_after_ok": 1,
            "count_after": 3,
            "handle_marker_free": 0,
            "thread_marker_free": 0,
            "snapshot_free": 0,
            "policy_ok": 1,
            "policy_error": 0,
            "policy_flags": 3,
            "policy_raise": 1,
            "policy_permanent": 1,
        }
        for key, value in snapshot.items():
            equal(prefix + key, value)
            expected_a3.add(prefix + key)
        inventory = {}
        for i in range(3):
            e = f"{prefix}h{i}_"
            raw = positive(e + "raw")
            mask = host.get(e + "pipes")
            require(raw not in inventory and mask in (1, 2, 4), "entry_identity")
            require(raw == pipes[(1, 2, 4).index(mask)], "pipe_identity")
            for key, value in {"copy_error": 0, "checked": 255, "hostile": 0}.items():
                equal(e + key, value)
            inventory[raw] = mask
            expected_a3.update(e + k for k in ("raw", "pipes", "copy_error", "checked", "hostile"))
        require(
            set(inventory) == set(pipes) and set(inventory.values()) == {1, 2, 4},
            "complete_inventory",
        )
        inventories.append(inventory)
    if not stall:
        require(inventories[0] == inventories[1], "inventory_changed")
    require({key for key in host if key.startswith("a3_")} == expected_a3, "closed_a3_schema")
    for i, kind in enumerate((1, 1, 2, 3, 4)):
        prefix = f"a1_control_h{i}_"
        for key, value in {
            "begin": 1,
            "info_ok": 1,
            "info_error": 0,
            "flags": 1,
            "duplicate_ok": 1,
            "duplicate_error": 0,
            "type_status": 0,
            "type": kind,
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
    validate_private(record, host, stall, pid, tid, creation)
    validate_shape(record, stall)
    return {
        "mode": record["mode"],
        "native_deadline_qualified": False,  # Parsing alone never qualifies a native attempt.
        "inspection_passed": not stall,
        "expected_control_observed": True,
        "execution_authority": False,
        "inventories": [{str(key): value for key, value in item.items()} for item in inventories],
        "child_resumed": False,
        "qualified": False,
        "control": "expected_deadline_failure" if stall else "sham",
    }
