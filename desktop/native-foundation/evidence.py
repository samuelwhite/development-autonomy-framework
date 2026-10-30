"""Durable, sanitized maintainer acceptance results; no execution journal or authority."""

import hashlib
import os
from pathlib import Path

import contracts as c

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


class Evidence:
    def __init__(self, root):
        self.root = root
        c.require(not (root / "results.json").exists(), "fresh_evidence_required")
        self.document = {
            "schema": "daf-native-acceptance/v2",
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
        self.persist()

    @property
    def records(self):
        return self.document["results"]

    def begin(self, name, role):
        record = {"case": name, "role": role, "status": "unconfirmed", "cleanup": "unconfirmed"}
        self.records.append(record)
        self.persist()
        return record

    def passed(self, record):
        c.require(record["cleanup"] == "confirmed", "cleanup_unconfirmed")
        record["status"] = "passed"
        self.persist()

    def failed(self, code):
        self.document["qualified"] = False
        self.document["stop"] = "mandatory_acceptance_failed"
        if self.records:
            self.records[-1]["status"] = "failed"
            self.records[-1]["failure"] = code
        self.persist()

    def persist(self):
        # Only this fresh generated root, inaccessible to children, is replaced.
        temporary = self.root / "results.pending"
        with temporary.open("xb") as stream:
            stream.write(c.canonical(self.document) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.root / "results.json")


class StreamHash:
    def __init__(self):
        self.digest = hashlib.sha256()
        self.bytes = 0

    def update(self, chunk):
        self.digest.update(chunk)
        self.bytes += len(chunk)

    def result(self, complete):
        return {"sha256": self.digest.hexdigest(), "bytes": self.bytes, "complete": complete}
