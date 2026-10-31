"""Closed maintainer contracts. No launcher, approval, provider or desktop dispatch."""

import base64
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path

BASELINE = "5b6f5d4328854df66d7bc25ab7aa0504256e6e12"
PLAN_COMMIT = "af6c620e5aa3b01c81179f91d093cefd7b9dd558"
PLAN_PATH = "docs/plans/m2.1-doc-status.json"
REPOSITORY = "samuelwhite/development-autonomy-framework"
TARGET = "docs/github-planning-ingestion.md"
SOURCE_BLOB = "4efee2c558dbc0c387fb15172d703796106c2caf"
PLAN_DIGEST = "d420c0f5b6784817fd991355ada9784eb35a3063f5a727ec194c48db0052b97f"
SOURCE_DIGEST = "9a22ac25b1fc42ff336b4bccfc434e9e29d751254d82256526e26343100cc0d0"
OLD_DIGEST = "e95610e8f9fe7de5ef2ba6f41c655d51d5c1d6d335b5331af73e41f72956170c"
NEW_DIGEST = "05bfc893fdf4fbf8ed43537784cc9b286957ca2c040ca2a8d4a100837cdaae37"
EXPECTED = "ab4dfef26d6ac32152e9e51d3d7896379e901d62a21160a4cc307daafcb468df"
POLICY_DIGEST = "64d0b0e8baf541ffe18c4fcd16d05444fc1b787815d219baf32ad2b69d66d0a5"
REQUEST = struct.Struct("<8s6I32s20s20s" + "32s" * 7)
RESPONSE = struct.Struct("<8s4I32s32s")
MAX_INPUT = REQUEST.size + 65536 * 2 + 8192 * 2
MAX_OUTPUT = RESPONSE.size + 65536
FAILURES = ("ok", "frame", "limit", "text", "binding", "occurrence", "preimage", "candidate", "io")


class Refused(ValueError):
    """Only fixed reason strings; never interpolate input or worker diagnostics."""


def require(ok, code):
    if not ok:
        raise Refused(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fields(value, names):
    require(type(value) is dict and set(value) == set(names.split()), "fields")
    return value


def load(raw, limit=262144):
    require(type(raw) is bytes and len(raw) <= limit, "limit")

    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, "duplicate_key")
            out[key] = value
        return out

    def nonfinite(_):
        raise Refused("nonfinite")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        raise Refused("json") from None


def hex_value(value, length=64):
    require(type(value) is str and re.fullmatch("[a-f0-9]{" + str(length) + "}", value), "hex")
    return value


def text_bytes(data, limit):
    require(type(data) is bytes and 0 < len(data) <= limit and b"\0" not in data, "text")
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeError:
        raise Refused("text") from None
    return data


def block(encoded):
    require(type(encoded) is str and len(encoded) <= 10924, "limit")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise Refused("base64") from None
    require(base64.b64encode(raw).decode() == encoded, "base64")
    return text_bytes(raw, 8192)


def specification(value, source):
    fields(value, "schema path beforeSha256 oldBlockBase64 newBlockBase64 expectedAfterSha256")
    require(
        value["schema"] == "daf-local-replacement/v1" and value["path"] == TARGET, "specification"
    )
    require(value["beforeSha256"] == SOURCE_DIGEST, "preimage")
    require(value["expectedAfterSha256"] == EXPECTED, "expected_digest")
    text_bytes(source, 65536)
    old, new = block(value["oldBlockBase64"]), block(value["newBlockBase64"])
    require(sha(old) == OLD_DIGEST and sha(new) == NEW_DIGEST and old != new, "blocks")
    require(sum(source.startswith(old, i) for i in range(len(source))) == 1, "occurrence")
    require(sha(source) == SOURCE_DIGEST and len(source) == 7594, "preimage")
    before, after = source.split(old)
    expected = before + new + after
    require(len(expected) == 7771 and sha(expected) == EXPECTED, "expected_digest")
    return old, new, expected


def binary(value, role):
    fields(value, "schema adapter role sha256 bytes")
    require(value["schema"] == "daf-native-build/v1", "build_version")
    require(value["adapter"] == "literal-markdown-v1" and value["role"] == role, "adapter")
    hex_value(value["sha256"])
    require(type(value["bytes"]) is int and 0 < value["bytes"] <= 1048576, "binary_size")


@dataclass(frozen=True)
class Preparation:
    """Canonical immutable bytes; caller-owned dictionaries cannot mutate a preparation."""

    encoded: bytes

    @property
    def digest(self):
        return sha(self.encoded)


def prepare(value, source, plan_bytes, protected):
    fields(value, "schema attempt source local_spec producer verifier policy inventory")
    require(value["schema"] == "daf-preparation/v1", "manifest_version")
    hex_value(value["attempt"], 32)
    provenance = fields(
        value["source"], "repository plan_commit plan_path plan_sha256 baseline path blob"
    )
    require(
        provenance
        == {
            "repository": REPOSITORY,
            "plan_commit": PLAN_COMMIT,
            "plan_path": PLAN_PATH,
            "plan_sha256": PLAN_DIGEST,
            "baseline": BASELINE,
            "path": TARGET,
            "blob": SOURCE_BLOB,
        },
        "source_binding",
    )
    require(sha(plan_bytes) == PLAN_DIGEST, "plan_digest")
    # The complete existing M1.1/M1.2 validators, not a competing plan store.
    from daf.planning_snapshot import make_snapshot, validate_snapshot

    snapshot = make_snapshot(
        {"repository": REPOSITORY, "commit_sha": PLAN_COMMIT, "path": PLAN_PATH}, plan_bytes
    )
    validate_snapshot(snapshot)
    plan = load(plan_bytes, 65536)
    require(len(plan["tasks"]) == 1 and plan["tasks"][0]["allowed_paths"] == [TARGET], "scope")
    require(plan["plan"]["baseline_revision"] == BASELINE, "baseline")
    require(len(plan["plan"]["milestones"]) == 1, "scope")
    require(plan["plan"]["milestones"][0]["depends_on"] == [], "dependencies")
    expected_inventory = plan["plan"]["validation"]["protected_files"]
    require(type(protected) is dict and set(protected) == set(expected_inventory), "inventory")
    require(sum(len(b) for b in protected.values()) + len(source) <= 2097152, "inventory_limit")
    require(len(protected) + 1 <= 16, "inventory_limit")
    require(all(sha(protected[p]) == h for p, h in expected_inventory.items()), "protected_digest")
    require(value["inventory"] == expected_inventory, "inventory")
    policy = value["policy"]
    require(sha(canonical(policy)) == POLICY_DIGEST, "policy")
    # Equality to the canonical hash closes fields and types, including bool/int confusion.
    binary(value["producer"], "producer")
    binary(value["verifier"], "verifier")
    specification(value["local_spec"], source)
    encoded = canonical(value)
    require(len(encoded) <= 32768, "manifest_limit")
    return Preparation(encoded)


def request(prepared, source, role, candidate=b""):
    require(type(prepared) is Preparation and type(role) is int and role in (1, 2), "request")
    value = load(prepared.encoded)
    old, new, _ = specification(value["local_spec"], source)
    require(type(candidate) is bytes and len(candidate) <= 65536, "limit")
    require((role == 1 and not candidate) or (role == 2 and bool(candidate)), "role")
    identity = value["producer" if role == 1 else "verifier"]
    return (
        REQUEST.pack(
            b"DAFN21A1",
            1,
            role,
            len(source),
            len(old),
            len(new),
            len(candidate),
            bytes.fromhex(prepared.digest),
            bytes.fromhex(PLAN_COMMIT),
            bytes.fromhex(SOURCE_BLOB),
            *[
                bytes.fromhex(h)
                for h in (
                    PLAN_DIGEST,
                    SOURCE_DIGEST,
                    OLD_DIGEST,
                    NEW_DIGEST,
                    EXPECTED,
                    POLICY_DIGEST,
                    identity["sha256"],
                )
            ],
        )
        + source
        + old
        + new
        + candidate
    )


def response(raw, role, manifest, candidate=None):
    require(type(raw) is bytes and RESPONSE.size <= len(raw) <= MAX_OUTPUT, "output_limit")
    magic, version, actual_role, status, size, binding, digest = RESPONSE.unpack(
        raw[: RESPONSE.size]
    )
    require(magic == b"DAFO21A1" and version == 1 and actual_role == role, "output_frame")
    require(status < len(FAILURES), "output_status")
    if status:
        require(
            len(raw) == RESPONSE.size
            and size == 0
            and binding == bytes(32)
            and digest == bytes(32),
            "failure_output",
        )
        return {"status": FAILURES[status]}, None
    require(
        size == 7771 and binding.hex() == manifest and digest.hex() == EXPECTED, "output_binding"
    )
    if role == 1:
        result = raw[RESPONSE.size :]
        require(len(result) == size and sha(result) == EXPECTED, "output_bytes")
    else:
        require(
            len(raw) == RESPONSE.size
            and type(candidate) is bytes
            and len(candidate) == size
            and sha(candidate) == EXPECTED,
            "verification_binding",
        )
        result = None
    return {"status": "ok", "bytes": size, "sha256": EXPECTED, "manifest": manifest}, result


def build_identity(path: Path, role):
    raw = path.read_bytes()
    value = {
        "schema": "daf-native-build/v1",
        "adapter": "literal-markdown-v1",
        "role": role,
        "sha256": sha(raw),
        "bytes": len(raw),
    }
    binary(value, role)
    return value
