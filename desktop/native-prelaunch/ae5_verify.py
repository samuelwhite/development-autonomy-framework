"""Independent A-E5 evidence schema; no native calls, launch or recovery."""

import hashlib

from ae5_contract import (
    CASES,
    HELPER_MS,
    HEX32,
    OUTER_MS,
    TERMINATION_MS,
    Ledger,
    canonical,
    exact,
    integer,
    process,
    require,
)


def ledger_prefix(records, exercise):
    """A valid interrupted prefix is retained, but is not recovery-complete."""
    require(type(records) is list and len(records) <= 256, "ledger_bound")
    require(type(exercise) is str and HEX32.fullmatch(exercise), "ledger_exercise")
    previous, pending, operations = "0" * 64, None, []
    complete = bool(records)
    for index, row in enumerate(records, 1):
        common = ("v", "exercise", "seq", "previous", "kind")
        require(type(row) is dict and row.get("kind") in {"intent", "commit"}, "ledger_kind")
        exact(
            row,
            (*common, "resource") if row["kind"] == "intent" else (*common, "intent", "outcome"),
        )
        require(
            row["v"] == 1
            and row["exercise"] == exercise
            and row["seq"] == index
            and row["previous"] == previous,
            "ledger_chain",
        )
        if row["kind"] == "intent":
            require(pending is None, "ledger_nested_intent")
            # Revalidate the closed resource schema; no native side effects.
            check = Ledger(exercise, lambda _seq, raw: raw)
            check.intent(row["resource"])
            pending = row
        else:
            require(pending is not None and row["intent"] == pending["seq"], "ledger_orphan_commit")
            exact(row["outcome"], ("ok", "created", "identity"))
            require(type(row["outcome"]["ok"]) is bool, "ledger_commit_type")
            require(
                type(row["outcome"]["created"]) is bool
                and type(row["outcome"]["identity"]) is dict,
                "ledger_outcome_types",
            )
            complete &= row["outcome"]["ok"]
            operations.append({"intent": pending, "commit": row})
            pending = None
        previous = hashlib.sha256(canonical(row)).hexdigest()
    return {
        "complete": bool(complete and pending is None),
        "pending": pending,
        "operations": operations,
        "last_digest": previous,
    }


def verify(value, readback=None):
    exact(
        value,
        (
            "schema",
            "case",
            "mode",
            "exercise",
            "source",
            "build",
            "helper",
            "child",
            "termination",
            "tree",
            "cleanup",
            "elapsed_ms",
            "resumes",
            "ledger",
            "execution_authority",
            "qualified",
        ),
    )
    require(value["schema"] == "daf-ae5-observation/v1" and value["case"] in CASES, "schema_case")
    require(value["mode"] in {"simulated", "native"}, "mode")
    if value["mode"] == "native":
        require(callable(readback), "independent_live_readback_required")
        live = readback()
        exact(live, ("helper", "child", "tree", "cleanup", "processes_launched"))
        require(
            type(live["processes_launched"]) is int and live["processes_launched"] == 0,
            "readback_cannot_launch",
        )
        require(
            all(live[key] == value[key] for key in ("helper", "child", "tree", "cleanup")),
            "independent_readback_difference",
        )
    require(value["execution_authority"] is False and value["qualified"] is False, "no_authority")
    require(type(value["resumes"]) is int and value["resumes"] == 0, "resume_forbidden")
    for name in ("source", "build"):
        require(
            type(value[name]) is str
            and len(value[name]) == 64
            and all(c in "0123456789abcdef" for c in value[name]),
            "identity",
        )
    for name in ("helper", "child"):
        exact(value[name], ("identity", "wait", "exit", "forced"))
        process(value[name]["identity"])
        require(value[name]["wait"] in {"signalled", "unknown"}, "process_wait")
        require(type(value[name]["forced"]) is bool, "forced_type")
        if value[name]["wait"] == "signalled":
            integer(value[name]["exit"], 0, 2**32 - 1)
        else:
            require(value[name]["exit"] is None, "unknown_exit")
    exact(value["termination"], ("requested", "confirmed", "elapsed_ms", "api_results"))
    t = value["termination"]
    require(type(t["requested"]) is bool and type(t["confirmed"]) is bool, "termination_type")
    integer(t["elapsed_ms"])
    require(type(t["api_results"]) is list and len(t["api_results"]) <= 4, "termination_calls")
    for item in t["api_results"]:
        exact(item, ("target", "returned", "ok", "error"))
        require(
            item["target"] in {"child", "outer"} and type(item["returned"]) is bool,
            "termination_target",
        )
        require(type(item["ok"]) is bool, "termination_result")
        integer(item["error"], 0, 2**32 - 1)
    exact(value["tree"], ("confirmed", "active", "method", "parent_death_witness"))
    if value["tree"]["active"] is not None:
        integer(value["tree"]["active"], 0, 2)
    exact(value["cleanup"], ("confirmed", "remaining", "identity_verified"))
    require(
        type(value["tree"]["confirmed"]) is bool
        and type(value["cleanup"]["confirmed"]) is bool
        and type(value["cleanup"]["identity_verified"]) is bool,
        "observation_types",
    )
    require(
        value["tree"]["method"] in {"outer_query", "complete_retained_membership", "unknown"},
        "tree_method",
    )
    witness = value["tree"]["parent_death_witness"]
    if value["tree"]["method"] == "complete_retained_membership":
        exact(witness, ("parent", "parent_wait", "members", "outer_handles", "inner_handles"))
        process(witness["parent"])
        require(
            value["case"] in {"TC-5", "TC-6"} and witness["parent_wait"] == "signalled",
            "parent_death_binding",
        )
        require(
            witness["members"] == [value["helper"]["identity"], value["child"]["identity"]],
            "complete_retained_membership",
        )
        for field in ("outer_handles", "inner_handles"):
            require(
                type(witness[field]) is int and witness[field] == 0,
                "witness_invalidates_last_handle_test",
            )
    else:
        require(witness is None, "unexpected_parent_death_claim")
    require(type(value["cleanup"]["remaining"]) is list, "remaining_resources")
    integer(value["elapsed_ms"])
    exits = all(value[k]["wait"] == "signalled" for k in ("helper", "child"))
    require(
        not t["confirmed"] or (t["requested"] and exits and t["elapsed_ms"] <= TERMINATION_MS),
        "termination_not_confirmed",
    )
    require(
        not value["tree"]["confirmed"]
        or (exits and value["tree"]["active"] == 0 and value["tree"]["method"] != "unknown"),
        "tree_not_quiescent",
    )
    ledger = ledger_prefix(value["ledger"], value["exercise"])
    require(
        not value["cleanup"]["confirmed"]
        or (
            ledger["complete"]
            and exits
            and value["tree"]["confirmed"]
            and value["cleanup"]["identity_verified"]
            and not value["cleanup"]["remaining"]
        ),
        "cleanup_not_confirmed",
    )
    complete = (
        t["confirmed"]
        and value["tree"]["confirmed"]
        and value["cleanup"]["confirmed"]
        and value["elapsed_ms"] < OUTER_MS
    )
    return {
        "schema": "daf-ae5-independent/v1",
        "mode": value["mode"],
        "status": "complete_observations" if complete else "UNRESOLVED",
        "helper_budget_ms": HELPER_MS,
        "observation_sha256": hashlib.sha256(canonical(value)).hexdigest(),
        "qualified": False,
        "execution_authority": False,
        "independent_readback_processes_launched": 0,
    }
