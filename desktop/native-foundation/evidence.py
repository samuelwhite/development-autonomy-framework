"""Durable, sanitized maintainer acceptance results; no execution journal or authority."""

import hashlib
import os
import time
import uuid
from pathlib import Path

import contracts as c
from case_manifest import CASES

OBSERVED = (
    "child_exit job_total_user_time_100ns peak_process_memory_bytes wall_elapsed_ms "
    "termination_latency_ms termination_reason worker_output_rejected active_after_wait "
    "hold_ready readiness_ms terminate_job_called terminate_job_succeeded "
    "retained_process_handle_signalled creation_time_100ns image_identity_checked "
    "host_elevated host_appcontainer appcontainer final_elevated CreateRestrictedToken_flags "
    "job_at_creation job_limit_flags job_process_limit job_memory_bytes job_cpu_100ns "
    "capability_count child_resumed host_failure termination_unconfirmed termination_api_error "
    "child_pid helper_pid"
).split()


def observed(record, rows):
    """Only known host keys and bounded scalar values; missing is never success."""
    missing, ambiguous = [], []
    for name in OBSERVED:
        values = [r.get("value") for r in rows if r.get("native") == name and "value" in r]
        if not values:
            missing.append(name)
        elif len(values) != 1 or type(values[0]) is not int or not 0 <= values[0] < 2**64:
            ambiguous.append(name)
        else:
            record[name] = values[0]
    record["missing_observations"] = missing
    record["invalid_or_duplicate_observations"] = ambiguous
    for name in ("child_stdout_prefix", "child_stderr_prefix"):
        matches = [r for r in rows if r.get("native") == name]
        if len(matches) == 1:
            r = matches[0]
            if (
                set(r) == {"native", "sha256", "bytes", "complete"}
                and type(r["sha256"]) is str
                and len(r["sha256"]) == 64
                and all(ch in "0123456789abcdef" for ch in r["sha256"])
                and type(r["bytes"]) is int
                and 0 <= r["bytes"] <= 65624
                and type(r["complete"]) is bool
            ):
                record[name] = {k: r[k] for k in ("sha256", "bytes", "complete")}
    for name, output in (
        ("requested_attempt_sid", "attempt_identity_sha256"),
        ("final_appcontainer_sid", "package_identity_sha256"),
    ):
        values = [r.get("sid") for r in rows if r.get("native") == name]
        if len(values) == 1 and type(values[0]) is str and len(values[0]) <= 256:
            record[output] = c.sha(values[0].encode())


def error_identity(error):
    # Never serialize exception messages, filenames, paths or worker-selected text.
    return {
        "kind": "filesystem" if isinstance(error, OSError) else "validation",
        "errno": getattr(error, "errno", None),
        "winerror": getattr(error, "winerror", None),
        "code": str(error) if isinstance(error, c.Refused) else None,
    }


class EvidenceFailure(RuntimeError):
    def __init__(self, report):
        super().__init__("mandatory_evidence_failure")
        self.report = report


class FileIO:
    """Small fault-injectable OS boundary; no retries or replacement fallbacks."""

    def create(self, path):
        return path.open("xb")

    def write(self, stream, data):
        c.require(stream.write(data) == len(data), "partial_evidence_write")

    def flush(self, stream):
        stream.flush()

    def sync(self, stream):
        os.fsync(stream.fileno())

    def read(self, path):
        with path.open("rb") as stream:
            return stream.read(1048577)

    def replace(self, source, destination):
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            move = kernel.MoveFileExW
            move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
            move.restype = wintypes.BOOL
            # Same-volume rename, REPLACE_EXISTING | WRITE_THROUGH.
            # No COPY_ALLOWED, delayed reboot, retry or delete-before-replace.
            if not move(str(source), str(destination), 0x1 | 0x8):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            os.replace(source, destination)

    def remove(self, path):
        path.unlink()


def validate_inventory(document, complete=False):
    c.require(document.get("schema") == "daf-native-acceptance/v3", "evidence_schema")
    run_id = c.hex_value(document.get("run_id"), 32)
    c.require(document.get("case_manifest") == [list(case) for case in CASES], "case_manifest")
    c.require(document.get("case_manifest_sha256") == c.sha(c.canonical(CASES)), "manifest_hash")
    rows = document.get("results")
    c.require(type(rows) is list and len(rows) <= 55, "case_count")
    for index, record in enumerate(rows):
        c.require(type(record) is dict, "case_record")
        name, role = CASES[index]
        c.require(
            record.get("case") == name
            and record.get("role") == role
            and record.get("run_id") == run_id
            and record.get("case_id") == f"{run_id}:{index:02}:{name}",
            "case_identity",
        )
        c.require(record.get("status") in ("unconfirmed", "passed", "failed"), "case_status")
    if complete:
        c.require(len(rows) == 55, "incomplete_cases")
        c.require(all(r["status"] == "passed" for r in rows), "incomplete_cases")
        c.require("stop" not in document, "failed_run")
        for name in ("attempt_identity_sha256", "package_identity_sha256"):
            c.require(len({c.hex_value(r.get(name)) for r in rows}) == 55, "shared_identity")


def read_qualified(root, validator):
    """Read-only, fail-closed review. Never resumes or repairs interrupted runs."""
    folder = root / "evidence"
    c.require(not (folder / "run.active").exists(), "run_unconfirmed")
    c.require(not list(folder.glob("*.pending")), "pending_evidence")
    c.require(not list(folder.glob("failure-*.json")), "failed_run")
    c.require(not (root / "results.pending").exists(), "legacy_pending_evidence")
    io = FileIO()
    raw = io.read(root / "results.json")
    document = c.load(raw, 1048576)
    validate_inventory(document, complete=True)
    c.require(
        document.get("execution_authority") is False and document.get("desktop_execution") is False,
        "unexpected_authority",
    )
    c.require(
        c.sha((root / "build-manifest.json").read_bytes()) == document.get("build_manifest_sha256"),
        "build_identity",
    )
    c.require(document.get("qualified") is True, "run_unqualified")
    owner = c.load(io.read(folder / "owner.json"))
    receipt = c.load(io.read(folder / "completion.json"))
    c.require(
        owner
        == {
            "run_id": document["run_id"],
            "build_manifest_sha256": document["build_manifest_sha256"],
        },
        "owner_identity",
    )
    c.require(
        receipt.get("run_id") == document["run_id"]
        and receipt.get("results_sha256") == c.sha(raw)
        and receipt.get("sequence") == document["sequence"]
        and receipt.get("cases") == 55
        and receipt.get("readback_verified") is True,
        "completion_identity",
    )
    checkpoint = folder / f"checkpoint-{document['run_id']}-{document['sequence']:06}.json"
    c.require(io.read(checkpoint) == raw, "checkpoint_mismatch")
    for record in document["results"]:
        validator(record)
    return document, receipt


class Evidence:
    def __init__(self, root, *, io=None):
        self.root, self.io = root, io or FileIO()
        c.require(
            not (root / "results.json").exists() and not (root / "results.pending").exists(),
            "fresh_evidence_required",
        )
        self.folder = root / "evidence"
        # Atomic directory claim: one writer ever; no auto-resume of an old run.
        self.folder.mkdir(exist_ok=False)
        self.sequence, self.aborted, self.closed = 0, False, False
        self.verified = []
        self.last_valid = None
        self.stage = "initialize"
        self.document = {
            "schema": "daf-native-acceptance/v3",
            "run_id": uuid.uuid4().hex,
            "case_manifest": [list(case) for case in CASES],
            "case_manifest_sha256": c.sha(c.canonical(CASES)),
            "execution_authority": False,
            "desktop_execution": False,
            "strict_read_isolation": False,
            "hard_cpu_ceiling": False,
            "build_manifest_sha256": c.sha((root / "build-manifest.json").read_bytes()),
            "runner_source_sha256": c.sha((Path(__file__).parent / "acceptance.py").read_bytes()),
            "evidence_source_sha256": c.sha(Path(__file__).read_bytes()),
            "results": [],
            "qualified": False,
        }
        try:
            owner = {key: self.document[key] for key in ("run_id", "build_manifest_sha256")}
            self._write_new(self.folder / "owner.json", c.canonical(owner), "owner")
            self._write_new(self.folder / "run.active", c.canonical(owner), "active")
        except (OSError, ValueError) as error:
            self._abort("evidence_initialization", error)
        self.persist()

    @property
    def records(self):
        return self.document["results"]

    def begin(self, name, role):
        c.require(not self.aborted and not self.closed, "run_closed")
        index = len(self.records)
        c.require(index < 55 and (name, role) == CASES[index], "case_order")
        record = {
            "case": name,
            "role": role,
            "status": "unconfirmed",
            "cleanup": "unconfirmed",
            "run_id": self.document["run_id"],
            "case_id": f"{self.document['run_id']}:{index:02}:{name}",
        }
        self.records.append(record)
        self.persist()
        return record

    def passed(self, record, validator):
        c.require(not self.aborted and not self.closed, "run_closed")
        c.require(bool(self.records) and record is self.records[-1], "case_identity")
        c.require(record.get("status") == "unconfirmed", "case_status")
        c.require(record["cleanup"] == "confirmed", "cleanup_unconfirmed")
        validator({**record, "status": "passed"})
        record["status"] = "passed"
        self.persist()

    def _abort(self, code, error=None):
        self.aborted = True
        self.document["qualified"] = False
        self.document["stop"] = "mandatory_acceptance_failed"
        if self.records and self.records[-1]["status"] == "unconfirmed":
            self.records[-1]["status"] = "failed"
            self.records[-1]["failure"] = code
        report = {
            "schema": "daf-native-evidence-failure/v1",
            "run_id": self.document["run_id"],
            "case_id": self.records[-1]["case_id"] if self.records else None,
            "attempted_sequence": self.sequence,
            "qualified": False,
            "reason": code,
            "stage": self.stage,
            "error": error_identity(error),
            "last_valid_checkpoint": self.last_valid,
            "evidence_retained": False,
        }
        # Independent unique file; never uses or replaces the primary pending path.
        path = self.folder / f"failure-{self.document['run_id']}-{uuid.uuid4().hex}.json"
        try:
            retained = {k: v for k, v in report.items() if k != "evidence_retained"}
            raw = c.canonical({**retained, "snapshot": self.document}) + b"\n"
            self._write_new(path, raw, "failure")
            report["evidence_retained"] = True
            report["failure_sha256"] = c.sha(raw)
        except (OSError, ValueError) as secondary:
            report["failure_record_error"] = error_identity(secondary)
            report["failure_record_stage"] = self.stage
        raise EvidenceFailure(report) from None

    def failed(self, code, error=None):
        self.stage = "case_validation"
        self._abort(code, error)

    def _readback(self, path, raw, phase):
        self.stage = phase + "_readback"
        received = self.io.read(path)
        c.load(received, 1048576)  # Reject duplicate keys, malformed and truncated data.
        c.require(received == raw, "evidence_readback_mismatch")

    def _write_new(self, path, raw, phase):
        self.stage = phase + "_create"
        with self.io.create(path) as stream:
            self.stage = phase + "_write"
            self.io.write(stream, raw)
            self.stage = phase + "_flush"
            self.io.flush(stream)
            self.stage = phase + "_fsync"
            self.io.sync(stream)
        self._readback(path, raw, phase)

    def _publish(self, target, raw, phase):
        temporary = (
            self.folder
            / f"{phase}-{self.document['run_id']}-{self.sequence:06}-{uuid.uuid4().hex}.pending"
        )
        self._write_new(temporary, raw, phase + "_temporary")
        self.stage = phase + "_replace"
        self.io.replace(temporary, target)
        self._readback(target, raw, phase)

    def persist(self):
        c.require(not self.aborted and not self.closed, "run_closed")
        started = time.monotonic()
        try:
            validate_inventory(self.document)
            self.sequence += 1
            self.document["sequence"] = self.sequence
            raw = c.canonical(self.document) + b"\n"
            c.require(len(raw) <= 1048576, "evidence_limit")
            checkpoint = (
                self.folder / f"checkpoint-{self.document['run_id']}-{self.sequence:06}.json"
            )
            c.require(not checkpoint.exists(), "checkpoint_conflict")
            self._publish(checkpoint, raw, "checkpoint")
            self._publish(self.root / "results.json", raw, "results")
            self.last_valid = {"sequence": self.sequence, "sha256": c.sha(raw)}
            self.verified.append(
                {**self.last_valid, "elapsed_ms": round((time.monotonic() - started) * 1000)}
            )
        except (OSError, ValueError) as error:
            self._abort("evidence_publication", error)

    def qualify(self, validator):
        try:
            validate_inventory(self.document, complete=True)
            for record in self.records:
                validator(record)
            c.require(
                not list(self.folder.glob("*.pending"))
                and not list(self.folder.glob("failure-*.json"))
                and not (self.root / "results.pending").exists(),
                "pending_or_failed_evidence",
            )
            self.document["qualified"] = True
            self.persist()
            receipt = {
                "schema": "daf-native-completion/v1",
                "run_id": self.document["run_id"],
                "sequence": self.sequence,
                "cases": 55,
                "results_sha256": self.last_valid["sha256"],
                "readback_verified": True,
                "retries": 0,
                "publications": self.verified,
            }
            self._publish(
                self.folder / "completion.json", c.canonical(receipt) + b"\n", "completion"
            )
            # Final commit point AFTER result/checkpoint/receipt readback. Any earlier
            # interruption leaves this marker and cannot qualify, even with 55 passes.
            self.stage = "active_remove"
            self.io.remove(self.folder / "run.active")
            self.closed = True
        except EvidenceFailure:
            raise
        except (OSError, ValueError, KeyError) as error:
            self._abort("qualification_incomplete", error)


class StreamHash:
    def __init__(self):
        self.digest = hashlib.sha256()
        self.bytes = 0

    def update(self, chunk):
        self.digest.update(chunk)
        self.bytes += len(chunk)

    def result(self, complete):
        return {"sha256": self.digest.hexdigest(), "bytes": self.bytes, "complete": complete}
