"""Closed offline capability, price and context contracts; no provider client."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .contract import canonical, digest, keys, require, sha
from .responses_request import FIXTURE_MODEL, Request

INSTRUCTIONS = "DAF offline bounded segment v1. Return an inert proposal only."


def integer(value: Any, minimum: int = 0) -> int:
    require(type(value) is int and minimum <= value <= 2**53 - 1, "invalid_explicit_units")
    return int(value)


@dataclass(frozen=True)
class Budget:
    tokens: int
    micro_usd: int

    def validate(self) -> None:
        integer(self.tokens, 1)
        integer(self.micro_usd, 1)


@dataclass(frozen=True)
class Capability:
    provider: str = "offline-fixture"
    model: str = FIXTURE_MODEL
    transport: str = "builtin-no-io-v1"
    revision: str = "byte-token-v1"
    counter: str = "canonical-count-projection-utf8-one-byte-one-fixture-token"
    evidence: str = "offline-algorithm-only-not-provider-proof"
    context_window: int = 8192
    output_max: int = 256
    hidden_max: int = 0
    retries_max: int = 0
    compaction_max: int = 0
    input_micro_usd: int = 2
    output_micro_usd: int = 3
    counting_micro_usd: int = 0
    currency: str = "USD"
    unit: str = "micro_usd"

    @property
    def fingerprint(self) -> str:
        return digest(asdict(self))

    def validate(self) -> None:
        require(
            type(self) is Capability and canonical(asdict(self)) == canonical(asdict(Capability())),
            "transport_unbounded",
        )

    def count(self, request: Request) -> int:
        self.validate()
        # This IS the defined tokenizer of the synthetic byte-token model. It
        # makes no estimate or claim about tokenization of a production model.
        return len(canonical(request.counting()).encode("utf-8"))

    def bounds(self, request: Request) -> tuple[int, int, int]:
        self.validate()
        body = request.generation()
        require(body["instructions"] == INSTRUCTIONS, "context_contract_changed")
        inputs = self.count(request)
        outputs = integer(body["max_output_tokens"], 16)
        require(outputs <= self.output_max, "transport_unbounded")
        require(inputs + outputs <= self.context_window, "context_window_exceeded")
        return (
            inputs,
            inputs + outputs,
            inputs * self.input_micro_usd + outputs * self.output_micro_usd,
        )


@dataclass(frozen=True)
class Scope:
    plan_sha256: str
    source_revision: str
    configuration_sha256: str
    permissions_sha256: str
    validator_sha256: str
    proof_sha256: str
    starts_at: int
    deadline: int

    def validate(self, now: int) -> None:
        for name, value in asdict(self).items():
            if name.endswith("sha256"):
                sha(value, 64)
        sha(self.source_revision, 40)
        integer(self.starts_at)
        integer(self.deadline, self.starts_at + 1)
        integer(now)
        require(self.starts_at <= now < self.deadline, "execution_window_closed")
        require(self.proof_sha256 == Capability().fingerprint, "transport_unbounded")


def texts(value: Any, count: int, size: int) -> list[str]:
    require(type(value) is list and len(value) <= count, "context_shape_invalid")
    require(
        all(type(item) is str and 0 < len(item.encode("utf-8")) <= size for item in value),
        "context_bytes_exceeded",
    )
    return list(value)


@dataclass(frozen=True)
class Context:
    body: str
    sha256: str

    @classmethod
    def build(
        cls,
        revision: str,
        criteria: list[str],
        diff: str = "",
        test_outputs: list[str] | None = None,
        blockers: list[str] | None = None,
        confirmed: dict[str, Any] | None = None,
    ) -> "Context":
        data = {
            "schema": "bounded-context-v1",
            "revision": revision,
            "criteria": criteria,
            "diff": diff,
            "diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
            "test_outputs": test_outputs or [],
            "blockers": blockers or [],
            "confirmed": confirmed,
        }
        result = cls(canonical(data), digest(data))
        result.validate()
        return result

    def validate(self) -> dict[str, Any]:
        require(
            type(self.body) is str and len(self.body.encode("utf-8")) <= 16384,
            "context_bytes_exceeded",
        )
        data = keys(
            json.loads(self.body),
            {
                "schema",
                "revision",
                "criteria",
                "diff",
                "diff_sha256",
                "test_outputs",
                "blockers",
                "confirmed",
            },
        )
        require(self.body == canonical(data) and self.sha256 == digest(data), "context_changed")
        require(data["schema"] == "bounded-context-v1", "context_shape_invalid")
        sha(data["revision"], 40)
        require(bool(texts(data["criteria"], 20, 512)), "acceptance_criteria_missing")
        texts(data["test_outputs"], 8, 1024)
        texts(data["blockers"], 8, 512)
        require(
            type(data["diff"]) is str and len(data["diff"].encode("utf-8")) <= 4096,
            "context_bytes_exceeded",
        )
        require(
            data["diff_sha256"] == hashlib.sha256(data["diff"].encode("utf-8")).hexdigest(),
            "context_changed",
        )
        if data["confirmed"] is not None:
            usage = keys(
                data["confirmed"],
                {"request_id", "response_id", "gross_tokens", "micro_usd", "scope_sha256"},
            )
            sha(usage["request_id"], 64)
            sha(usage["scope_sha256"], 64)
            require(
                type(usage["response_id"]) is str and len(usage["response_id"]) <= 96,
                "context_shape_invalid",
            )
            integer(usage["gross_tokens"])
            integer(usage["micro_usd"])
        return dict(data)

    def request(self, output_max: int = 32) -> Request:
        self.validate()
        return Request.build(INSTRUCTIONS, self.body, output_max)


@dataclass(frozen=True)
class Observation:
    request_id: str
    response_id: str
    sequence: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    complete: bool = True

    def validate(self) -> None:
        sha(self.request_id, 64)
        require(
            self.response_id == "fixture-response-" + self.request_id, "response_identity_mismatch"
        )
        integer(self.sequence, 1)
        for value in (
            self.input_tokens,
            self.output_tokens,
            self.cached_input_tokens,
            self.reasoning_tokens,
        ):
            integer(value)
        require(
            self.cached_input_tokens <= self.input_tokens
            and self.reasoning_tokens <= self.output_tokens,
            "usage_subset_invalid",
        )
        require(type(self.complete) is bool, "usage_incomplete")
