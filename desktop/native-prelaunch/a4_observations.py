"""A4 detector-control evidence; expected refusal is never candidate acceptance."""

from handle_observations import InvalidObservation as InvalidObservation
from handle_observations import require

DEADLINE_MS = 5000
MAX_HANDLES = 16


def validate(record):
    case = record.get("case")
    require(case in ("A4-01", "A4-02"), "a4_case")
    sequence = 1 if case == "A4-01" else 2
    require(record.get("sequence") == sequence and record.get("role") == "probe", "a4_sequence")
    require(record.get("cleanup") == "confirmed", "cleanup")
    require(record.get("helper_exit") == 0, "helper_exit")
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
        require(key not in {"child_resumed", "host_failure"}, "unexpected_execution_or_failure")
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
        "a3_inheritance_count": 4,
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
        "a3_inspection_passed": 0,
        "a3_failure": 201,
        "a3_fixture_table_verified": 1,
        "a3_fixture_copy_error": 0,
        "a3_fixture_object_same": 1,
        "a3_fixture_object_error": 0,
        "a3_fixture_file_id_ok": 1,
        "a3_fixture_file_id_error": 0,
        "a3_fixture_witness_complete": 1,
        "a4_controlled_stop": 1,
        "a4_expected_refusal_verified": 1,
        "a4_case": sequence,
        "a4_normal_inheritance_count": 3,
        "a4_original_flags": 1,
        "a4_inherited_flags": 1,
        "a4_parent_same_object": 1,
        "a4_original_in_list": int(sequence == 1),
        "a4_fixture_list_installed": 1,
        "a3_inventories_consistent": 1,
        "a3_last_stage": 1,
        "a3_hostile_event_after_child": 258,
        "restore_registry_acl": 0,
        "delete_explicitly_created_registry_storage": 0,
        "delete_synthetic_registry_key": 0,
        "delete_owned_profile_hresult": 0,
        "delete_synthetic_credential": 1,
    }
    for key, value in fixed.items():
        equal(key, value)
    require(host.get("a3_inspection_elapsed_ms", DEADLINE_MS) < DEADLINE_MS, "inspection_deadline")
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
                and process.get("exit") == (123 if process["pid"] == pid else 0),
                "independent_exit",
            )
    for key in ("a3_created_pid", "child_pid"):
        equal(key, pid)
    equal("a3_created_tid", tid)
    pipes = [positive(f"a3_pipe_{i}") for i in range(3)]
    require(len(set(pipes)) == 3, "distinct_pipes")
    original = positive("a4_original_handle")
    inherited = positive("a4_inherited_handle")
    equal("a1_control_h0_raw", original)
    require(original not in pipes and inherited not in pipes, "fixture_not_pipe")
    require((original == inherited) == (sequence == 1), "alias_value")
    for i, value in enumerate([*pipes, inherited]):
        equal(f"a4_inherit_{i}", value)
    for field in ("volume", "file_low", "file_high"):
        value = host.get("a1_control_h0_" + field)
        require(type(value) is int, "fixture_identity_missing")
        equal("a4_original_" + field, value)
        equal("a3_fixture_" + field, value)
    positive("a4_original_volume")
    require(host["a4_original_file_low"] or host["a4_original_file_high"], "fixture_file_identity")
    equal("a1_control_h0_regular_32_bytes", 1)
    equal("a1_control_h0_file_type", 1)
    equal("a1_control_h0_id_ok", 1)
    equal("a1_control_h0_id_error", 0)
    expected_a4 = {key for key in fixed if key.startswith("a4_")} | {
        "a4_original_handle",
        "a4_inherited_handle",
        "a4_original_volume",
        "a4_original_file_low",
        "a4_original_file_high",
        *(f"a4_inherit_{i}" for i in range(4)),
    }
    require({key for key in host if key.startswith("a4_")} == expected_a4, "closed_a4_schema")
    expected_a3 = {key for key in fixed if key.startswith("a3_")} | {
        "a3_fixture_volume",
        "a3_fixture_file_low",
        "a3_fixture_file_high",
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
    for prefix in ("a3_s0_", "a3_s1_", "a3_final_", "a3_fixture_final_"):
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
        if prefix in ("a3_final_", "a3_fixture_final_"):
            continue
        snapshot = {
            "count_before_ok": 1,
            "count_before": 4,
            "capture_status": 0,
            "handle_query_status": 0,
            "thread_query_status": 0,
            "handles_captured": 4,
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
            "entries": 4,
            "count_after_ok": 1,
            "count_after": 4,
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
        for i in range(4):
            e = f"{prefix}h{i}_"
            raw = positive(e + "raw")
            mask = host.get(e + "pipes")
            hostile = host.get(e + "hostile")
            require(raw not in inventory, "duplicate_entry")
            if raw == inherited:
                require(mask == 0 and hostile == 1, "exact_hostile_object_match")
            else:
                require(mask in (1, 2, 4) and hostile == 0, "unexpected_object")
                require(raw == pipes[(1, 2, 4).index(mask)], "pipe_identity")
            for key, value in {"copy_error": 0, "checked": 255}.items():
                equal(e + key, value)
            if sequence == 2:
                require(raw != original, "original_alias_slot_present")
            inventory[raw] = {"pipes": mask, "hostile": hostile}
            expected_a3.update(e + k for k in ("raw", "pipes", "copy_error", "checked", "hostile"))
        require(
            set(inventory) == {*pipes, inherited}
            and {v["pipes"] for v in inventory.values()} == {0, 1, 2, 4},
            "complete_inventory",
        )
        inventories.append(inventory)
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
    return {
        "inventories": inventories,
        "child_resumed": False,
        "qualified": False,
        "initial_detector_sensitivity": True,
        "refusal_reason": "hostile_object_identity_match",
        "policy_refusal_code": 201,
        "original_handle": original,
        "inherited_handle": inherited,
    }
