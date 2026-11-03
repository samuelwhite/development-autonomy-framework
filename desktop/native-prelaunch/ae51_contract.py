"""TC-0 closed schemas. Pure validation never creates a claim or receipt."""

import ast
import hashlib
import json
import re
import threading

from ae5_contract import ACK, MAGIC, canonical, exact, integer, require, unique

CASE = "TC-0"
# Reserved candidate binding label, not a Product approval or decision record.
PRODUCT_DECISION_ID = "DAF-A-E5.2-TC-0-RC1"


class Finalization:
    """Independent outer lane can revoke even while the persistence lane blocks."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = "PENDING"

    def stop(self):
        with self.lock:
            self.state = "STOP"

    def finish(self, now, deadline):
        with self.lock:
            if self.state != "PENDING" or now >= deadline:
                self.state = "STOP"
                raise ValueError("late_or_duplicate_completion")
            self.state = "COMPLETE"


def source_gates(root):
    result = {}
    for name, file, variable in (
        ("python", "ae5_parent.py", "NATIVE_RELEASE"),
        ("windows", "ae5_windows.py", "NATIVE_RELEASE"),
        ("recovery", "ae5_resources.py", "RECOVERY_RELEASE"),
        ("decision", "ae51_contract.py", "PRODUCT_DECISION_ID"),
    ):
        tree = ast.parse((root / file).read_text())
        matches = [
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == variable for t in node.targets)
        ]
        require(len(matches) == 1, "single_source_gate")
        result[name] = ast.literal_eval(matches[0])
    matches = re.findall(
        r"inline volatile const LONG NativeRelease = ([01]);", (root / "ae5-custody.h").read_text()
    )
    require(len(matches) == 1, "single_cpp_gate")
    result["cpp"] = matches[0] == "1"
    return result


def unused_attempt(root_exists, claim_exists, stop_exists):
    require(
        all(type(x) is bool for x in (root_exists, claim_exists, stop_exists)), "claim_state_types"
    )
    require(not any((root_exists, claim_exists, stop_exists)), "attempt_consumed_or_stop")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(raw, maximum=2_000_000):
    require(type(raw) is bytes and 0 < len(raw) <= maximum, "json_bound")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)


def hex_identity(value, size=64):
    require(
        type(value) is str and len(value) == size and all(c in "0123456789abcdef" for c in value),
        "identity_format",
    )


def binding(value):
    exact(value, ("case", "source_commit", "source_tree", "manifest", "files", "exercise"))
    require(value["case"] == CASE, "tc0_only")
    for key in ("source_commit", "source_tree"):
        hex_identity(value[key], 40)
    hex_identity(value["manifest"])
    hex_identity(value["exercise"], 32)
    exact(
        value["files"],
        (
            "ae5-fixture-host.exe",
            "handle-probe.exe",
            "ae5-fixture-host.cpp",
            "ae5-fixture-harness.h",
            "producer.exe",
            "verifier.exe",
        ),
    )
    for identity in value["files"].values():
        exact(identity, ("bytes", "sha256"))
        integer(identity["bytes"], 1, 10_000_000)
        hex_identity(identity["sha256"])
    return digest(canonical(value))


def approval(value, bound, now):
    exact(
        value,
        (
            "schema",
            "case",
            "binding",
            "decision",
            "decision_id",
            "attempts",
            "retries",
            "not_before",
            "expires",
        ),
    )
    require(value["schema"] == "daf-ae51-product-approval/v1", "approval_schema")
    require(value["case"] == CASE and value["binding"] == binding(bound), "approval_binding")
    require(value["decision"] == "AUTHORISE_TC0_ONCE", "explicit_product_decision")
    require(
        type(value["decision_id"]) is str and 0 < len(value["decision_id"]) <= 256, "decision_id"
    )
    require(type(value["attempts"]) is int and value["attempts"] == 1, "single_attempt")
    require(type(value["retries"]) is int and value["retries"] == 0, "zero_retries")
    integer(now)
    integer(value["not_before"])
    integer(value["expires"], value["not_before"] + 1)
    require(value["not_before"] <= now < value["expires"], "approval_expired_or_early")


def claim(value, bound, approval_sha):
    exact(value, ("schema", "case", "binding", "approval_sha256", "attempt", "retries", "mode"))
    hex_identity(approval_sha)
    require(
        value
        == {
            "schema": "daf-ae51-consumed-claim/v1",
            "case": CASE,
            "binding": binding(bound),
            "approval_sha256": approval_sha,
            "attempt": 1,
            "retries": 0,
            "mode": "native",
        },
        "claim_binding",
    )
    require(type(value["attempt"]) is int and type(value["retries"]) is int, "claim_types")


def acknowledgement(raw, exercise, parent, sequence, verified_at, now, deadline):
    for value in (sequence, verified_at, now, deadline):
        integer(value)
    require(type(raw) is bytes and len(raw) == ACK.size, "ack_size")
    magic, seq, due, pid, created, ex = ACK.unpack(raw)
    require(
        (magic, seq, pid, created, ex)
        == (MAGIC, sequence, parent["pid"], parent["creation"], exercise.encode("ascii")),
        "ack_identity",
    )
    require(verified_at <= now < due == deadline, "early_or_late_ack")


def receipt(value, bound, claim_sha, evidence_sha, observed_sha):
    exact(
        value,
        (
            "schema",
            "case",
            "binding",
            "claim_sha256",
            "evidence_sha256",
            "readback_sha256",
            "status",
            "qualified",
            "execution_authority",
            "additional_processes_launched",
        ),
    )
    for item in (claim_sha, evidence_sha, observed_sha):
        hex_identity(item)
    require(
        value["qualified"] is False and value["execution_authority"] is False,
        "receipt_no_authority",
    )
    require(
        value
        == {
            "schema": "daf-ae51-independent-receipt/v1",
            "case": CASE,
            "binding": binding(bound),
            "claim_sha256": claim_sha,
            "evidence_sha256": evidence_sha,
            "readback_sha256": observed_sha,
            "status": "TC0_EXPECTED_OBSERVATIONS",
            "qualified": False,
            "execution_authority": False,
            "additional_processes_launched": 0,
        },
        "stale_or_foreign_receipt",
    )
    require(type(value["additional_processes_launched"]) is int, "receipt_process_count")
