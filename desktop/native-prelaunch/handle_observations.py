"""Independent closed observation checks. Absence is not an I/O-denial claim."""

import json

FIELDS = set(
    "binding begin raw info_ok info_error flags before_duplicate duplicate_ok duplicate_error "
    "before_metadata type_status type file_type file_type_error standard_mask known_reference "
    "id_ok id_error volume file_low file_high regular_32_bytes process_pid process_pid_error "
    "process_times_ok process_times_error process_creation intended_identity before_operation "
    "read_marker mapping_flush_ok mapping_flush_error mapping_unmap_ok duplicated_read_identity "
    "duplicated_read_error duplicated_read_marker operation_attempted operation_ok operation_error "
    "operation_bytes outcome complete".split()
)
TOP = set(
    "schema pid stdin_raw stdout_raw stderr_raw stdin_pipe stdout_pipe stderr_pipe "
    "bindings_complete probe_complete".split()
)
KEYS = TOP | {f"h{i}_{field}" for i in range(5) for field in FIELDS}


class InvalidObservation(ValueError):
    pass


def require(condition, stage):
    if not condition:
        raise InvalidObservation(stage)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_field")
        result[key] = value
    return result


def parse(raw):
    """Retain safe partial progress even if the process later fails or times out."""
    require(type(raw) is bytes and len(raw) <= 65624, "probe_bound")
    values = {}
    for line in raw.splitlines():
        require(len(line) <= 192, "probe_line_bound")
        try:
            row = json.loads(line, object_pairs_hook=unique_pairs)
        except (ValueError, UnicodeError) as error:
            raise InvalidObservation("probe_json") from error
        require(type(row) is dict and set(row) == {"probe", "value"}, "probe_fields")
        key, value = row["probe"], row["value"]
        require(type(key) is str and key in KEYS and key not in values, "probe_key")
        require(type(value) is int and 0 <= value < 2**64, "probe_numeric")
        values[key] = value
    return values


def validate(values, rows):
    """Five complete identity determinations AND independent host evidence required."""
    host = {}
    for row in rows:
        key = row["native"]
        if key.startswith("a1_") or key in {"child_pid", "hostile_handles_inheritable"}:
            require(set(row) == {"native", "value"} and key not in host, "host_fields")
            require(type(row["value"]) is int and 0 <= row["value"] < 2**64, "host_numeric")
            host[key] = row["value"]

    def h(key, expected):
        require(host.get(key) == expected, "host_" + key)

    def v(key, expected):
        require(values.get(key) == expected, "child_" + key)

    h("a1_attribute_mask", 31)
    h("a1_attribute_count", 5)
    h("a1_inheritance_count", 3)
    h("hostile_handles_inheritable", 5)
    h("a1_suspended_handle_audit_complete", 1)
    h("a1_control_effects_verified_and_restored", 1)
    h("a1_hostile_event_after_child", 258)
    v("schema", 2)
    v("pid", host.get("child_pid"))
    h("a1_suspended_child_pid", host.get("child_pid"))
    v("bindings_complete", 1)
    v("probe_complete", 1)
    for n, stream in enumerate(("stdin", "stdout", "stderr")):
        require(host.get(f"a1_standard_{n}", 0) > 0, "standard_identity_missing")
        v(stream + "_raw", host[f"a1_standard_{n}"])
        v(stream + "_pipe", 1)
    determinations = []
    for i, wanted_type in enumerate((1, 1, 2, 3, 4)):
        control, audit, child = f"a1_control_h{i}_", f"a1_audit_h{i}_", f"h{i}_"
        for key, expected in {
            "begin": 1,
            "info_ok": 1,
            "info_error": 0,
            "before_duplicate": 1,
            "duplicate_ok": 1,
            "duplicate_error": 0,
            "before_metadata": 1,
            "type_status": 0,
            "type": wanted_type,
            "standard_mask": 0,
            "known_reference": 1,
            "intended_identity": 1,
            "before_operation": 1,
            "operation_attempted": 1,
            "operation_ok": 1,
            "operation_error": 0,
            "outcome": 3,
            "complete": 1,
        }.items():
            h(control + key, expected)
        require(host.get(control + "flags", 0) & 1, "control_not_inheritable")
        raw = host.get(control + "raw")
        require(type(raw) is int and 0 < raw < 2**63, "control_handle_missing")
        h(audit + "raw", raw)
        h(audit + "hostile_mask", 0)
        require(host.get(audit + "valid") in (0, 1), "audit_validity_missing")
        if host[audit + "valid"]:
            h(audit + "error", 0)
            require(host.get(audit + "standard_mask") in (0, 1, 2, 4), "audit_mask")
        else:
            h(audit + "error", 6)
            h(audit + "standard_mask", 0)
        v(child + "binding", raw)
        v(child + "raw", raw)
        for key in ("begin", "before_duplicate", "complete"):
            v(child + key, 1)
        # Explicitly record that no resource operation was attempted. A pass
        # requires independently established absence/different approved object;
        # it must never label a skipped ReadFile/WriteFile as an access denial.
        for key in ("operation_attempted", "operation_ok", "operation_error", "operation_bytes"):
            v(child + key, 0)
        require(child + "before_operation" not in values, "unreported_operation")
        outcome = values.get(child + "outcome")
        base_fields = set(
            "binding begin raw info_ok info_error flags before_duplicate duplicate_ok "
            "duplicate_error operation_attempted operation_ok operation_error "
            "operation_bytes outcome complete".split()
        )
        present = {key.removeprefix(child) for key in values if key.startswith(child)}
        require(values.get(child + "flags") in (0, 1, 2, 3), "handle_flags_missing")
        if outcome == 1:
            require(present == base_fields, "invalid_handle_fields")
            v(child + "flags", 0)
            for key, expected in {
                "info_ok": 0,
                "info_error": 6,
                "duplicate_ok": 0,
                "duplicate_error": 6,
            }.items():
                v(child + key, expected)
            require(child + "before_metadata" not in values, "metadata_without_handle")
            determination = "invalid_handle_no_capability"
        elif outcome == 2:
            require(
                present
                == base_fields
                | set(
                    "before_metadata type_status type file_type "
                    "file_type_error standard_mask known_reference intended_identity".split()
                ),
                "pipe_fields",
            )
            for key, expected in {
                "info_ok": 1,
                "info_error": 0,
                "duplicate_ok": 1,
                "duplicate_error": 0,
                "before_metadata": 1,
                "type_status": 0,
                "type": 1,
                "file_type": 3,
                "file_type_error": 0,
                "known_reference": 0,
                "intended_identity": 0,
            }.items():
                v(child + key, expected)
            require(values.get(child + "standard_mask") in (1, 2, 4), "unidentified_pipe")
            determination = "authorized_standard_pipe_object_not_hostile_resource"
        else:
            raise InvalidObservation("access_or_ambiguous_or_incomplete")
        determinations.append(
            {
                "resource": i,
                "handle": raw,
                "identity": determination,
                "resource_operation_attempted": False,
                "io_denial_claim": False,
            }
        )
    h("a1_control_h0_read_marker", 1)
    h("a1_control_h0_operation_bytes", 32)
    h("a1_control_h1_operation_bytes", 1)
    h("a1_control_h2_operation_bytes", 1)
    for key in ("mapping_flush_ok", "mapping_unmap_ok"):
        h("a1_control_h2_" + key, 1)
    h("a1_control_h2_mapping_flush_error", 0)
    h("a1_control_h4_duplicated_read_identity", 1)
    h("a1_control_h4_duplicated_read_marker", 1)
    h("a1_control_h4_duplicated_read_error", 0)
    return determinations
