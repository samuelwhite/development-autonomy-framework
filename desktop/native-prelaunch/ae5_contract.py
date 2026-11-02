"""Portable A-E5 custody/ledger contracts. No process or Windows API calls."""

import hashlib
import json
import re
import struct
import threading
from dataclasses import dataclass, field

INSPECTION_MS, TERMINATION_MS, RUNTIME_MS = 5000, 3000, 10000
HELPER_MS, OUTER_MS = 30000, 35000
MAX_FRAME, MAX_RECORDS, MAX_DESCRIPTOR = 32768, 256, 8192
MAX_CONTROL, MAX_STDERR = 65624, 32768  # Preserve existing helper capture byte ceilings.
MAGIC = 0x35454144
ACK = struct.Struct("<IIQQQ32s")
CASES = tuple(f"TC-{i}" for i in range(9))
PROFILE = re.compile(
    r"DAF\.M21A\.Acceptance\.[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\Z"
)
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
INNER = {"flags": 0x210A, "processes": 1, "memory": 134217728, "cpu": 20000000}
OUTER = {"flags": 0x2008, "processes": 2, "memory": 0, "cpu": 0}
RIGHTS = {"helper": 0x101001, "child": 0x101001, "thread": 0x100800, "inner": 4, "outer": 12}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def exact(value, keys):
    require(type(value) is dict and set(value) == set(keys), "closed_shape")


def integer(value, minimum=0, maximum=2**64 - 1):
    require(type(value) is int and minimum <= value <= maximum, "integer_bounds")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate_json_key")
        value[key] = item
    return value


def decode(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_FRAME, "frame_bound")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    exact(value, ("v", "exercise", "seq", "kind", "data"))
    require(value["v"] == 1 and type(value["v"]) is int, "wire_version")
    require(type(value["exercise"]) is str and HEX32.fullmatch(value["exercise"]), "exercise")
    integer(value["seq"], 1, MAX_RECORDS)
    require(value["kind"] in {"intent", "commit", "custody", "cleanup"}, "wire_kind")
    require(type(value["data"]) is dict, "wire_data")
    return value


def process(value):
    exact(value, ("pid", "creation"))
    integer(value["pid"], 1, 2**32 - 1)
    integer(value["creation"], 1)
    return value


def handoff(value):
    exact(value, ("process", "thread", "job", "pid", "tid", "creation", "helper_creation"))
    for key in value:
        integer(value[key], 1, 2**32 - 1 if key in {"pid", "tid"} else 2**63 - 1)
    require(len({value[k] for k in ("process", "thread", "job")}) == 3, "aliased_handle_slots")
    return value


@dataclass
class Decision:
    """Only short memory operations under this lock; never call a backend here."""

    started: int
    helper: dict
    state: str = "HELD"
    inspection_deadline: int | None = None
    abort_at: int | None = None
    reason: str | None = None
    child: dict | None = None
    lock: object = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        integer(self.started)
        process(self.helper)

    def stop(self, reason, now):
        integer(now, self.started)
        with self.lock:
            if self.state != "STOP":
                self.state, self.reason, self.abort_at = "STOP", reason, now

    def establish(self, observed, now):
        integer(now, self.started)
        # Independent OS adapter observations, never helper assertions alone.
        exact(
            observed,
            (
                "helper",
                "child",
                "inner",
                "outer",
                "members",
                "thread_pid",
                "inner_query_closed",
                "noninheritable",
                "outer_owner_only",
                "rights",
                "helper_transfer_closed",
            ),
        )
        for limits in (observed["inner"], observed["outer"]):
            exact(limits, ("flags", "processes", "memory", "cpu"))
            for value in limits.values():
                integer(value)
        exact(observed["members"], ("helper_outer", "child_outer", "child_inner", "helper_inner"))
        require(all(type(v) is bool for v in observed["members"].values()), "membership_types")
        integer(observed["thread_pid"], 1, 2**32 - 1)
        exact(observed["rights"], RIGHTS)
        for value in observed["rights"].values():
            integer(value)
        valid = (
            observed["helper"] == self.helper
            and observed["inner"] == INNER
            and observed["outer"] == OUTER
            and observed["members"]
            == {
                "helper_outer": True,
                "child_outer": True,
                "child_inner": True,
                "helper_inner": False,
            }
            and observed["thread_pid"] == process(observed["child"])["pid"]
            and observed["child"]["pid"] != self.helper["pid"]
            and observed["inner_query_closed"] is True
            and observed["noninheritable"] is True
            and observed["outer_owner_only"] is True
            and observed["helper_transfer_closed"] is True
            and observed["rights"] == RIGHTS
        )
        with self.lock:
            if not valid or self.state != "HELD" or now >= self.started + HELPER_MS:
                if self.state != "STOP":
                    self.state, self.reason, self.abort_at = "STOP", "custody_refused", now
                raise ValueError("custody_refused")
            self.child, self.state = dict(observed["child"]), "CUSTODIED"

    def arm(self, now):
        integer(now, self.started)
        with self.lock:
            if (
                self.state != "CUSTODIED"
                or now + INSPECTION_MS + TERMINATION_MS >= self.started + HELPER_MS
            ):
                if self.state != "STOP":
                    self.state, self.reason, self.abort_at = "STOP", "ack_refused", now
                raise ValueError("ack_refused")
            self.inspection_deadline = now + INSPECTION_MS
            self.state = "INSPECTING"
            return self.inspection_deadline

    def tick(self, now, helper_alive=True, communication=True):
        if not helper_alive:
            self.stop("helper_exit", now)
        elif not communication:
            self.stop("communication_lost", now)
        elif now >= self.started + HELPER_MS:
            self.stop("helper_deadline", now)
        elif self.inspection_deadline is not None and now >= self.inspection_deadline:
            self.stop("inspection_deadline", now)
        return self.state

    def inspection_result(self, passed, now):
        # This exercise has no accepting/resuming continuation state.
        self.stop("diagnostic_complete" if passed is True else "inspection_refused", now)

    def cleanup_phase(self, now):
        with self.lock:
            require(
                self.state == "INSPECTING" and now < self.inspection_deadline,
                "cleanup_after_revocation",
            )
            self.state, self.inspection_deadline = "DRAINING", None


class Ledger:
    """Write-ahead state machine. Append callback must durably create exact bytes.

    No callback executes under the safety Decision lock. A failed append poisons
    this ledger permanently; an on-disk prefix is never inferred to be complete.
    """

    def __init__(self, exercise, append):
        require(HEX32.fullmatch(exercise), "ledger_exercise")
        self.exercise, self.append = exercise, append
        self.records, self.pending, self.broken = [], None, False

    def _write(self, value):
        require(not self.broken and len(self.records) < MAX_RECORDS, "ledger_unavailable")
        record = {
            "v": 1,
            "exercise": self.exercise,
            "seq": len(self.records) + 1,
            "previous": hashlib.sha256(canonical(self.records[-1])).hexdigest()
            if self.records
            else "0" * 64,
            **value,
        }
        raw = canonical(record)
        require(len(raw) <= MAX_FRAME, "ledger_record_bound")
        try:
            require(self.append(record["seq"], raw) == raw, "ledger_readback")
        except BaseException:
            self.broken = True
            raise
        self.records.append(record)
        return record

    def intent(self, resource):
        require(self.pending is None, "pending_transaction")
        exact(resource, ("kind", "name", "identity", "original", "created"))
        require(
            resource["kind"] in {"profile", "credential", "registry", "desktop", "acl"},
            "resource_kind",
        )
        require(
            type(resource["name"]) is str
            and 0 < len(resource["name"]) <= 2048
            and "\x00" not in resource["name"],
            "resource_name",
        )
        require(type(resource["identity"]) is dict, "resource_identity")
        require(
            type(resource["original"]) is str
            and len(resource["original"]) <= MAX_DESCRIPTOR * 2
            and re.fullmatch(r"(?:[0-9a-f]{2})*", resource["original"]),
            "descriptor_encoding",
        )
        require(resource["created"] is False, "intent_not_creation")
        record = self._write({"kind": "intent", "resource": resource})
        self.pending = record["seq"]
        return self.pending

    def commit(self, intent, outcome):
        integer(intent, 1, MAX_RECORDS)
        require(self.pending == intent, "commit_without_matching_intent")
        exact(outcome, ("ok", "created", "identity"))
        require(
            type(outcome["ok"]) is bool
            and type(outcome["created"]) is bool
            and type(outcome["identity"]) is dict,
            "commit_outcome",
        )
        self._write({"kind": "commit", "intent": intent, "outcome": outcome})
        self.pending = None
        if not outcome["ok"]:
            self.broken = True

    def ready(self):
        return bool(self.records) and self.pending is None and not self.broken
