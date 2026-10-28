"""Closed, immutable request contract for an OFFLINE Responses transport experiment.

No model capability or live provider is certified by these fixture contracts.
"""

import json
from dataclasses import dataclass
from typing import Any

from .contract import canonical, digest, integer, keys, require

FIXTURE_MODEL = "fixture-only-responses-model"
COUNT_FIELDS = frozenset(
    {
        "model",
        "instructions",
        "input",
        "text",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "truncation",
        "conversation",
        "previous_response_id",
    }
)
GENERATION_FIELDS = COUNT_FIELDS | {
    "max_output_tokens",
    "store",
    "background",
    "stream",
    "context_management",
    "service_tier",
}


def proposal_format() -> dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": "daf_offline_patch_proposal",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"scope_change": {"type": "boolean"}, "patch": {"type": "string"}},
                "required": ["scope_change", "patch"],
                "additionalProperties": False,
            },
        }
    }


@dataclass(frozen=True)
class Request:
    """Only canonical strings are retained; callers never receive mutable owned state."""

    body: str
    sha256: str

    @classmethod
    def build(cls, instructions: str, text: str, output_ceiling: int) -> "Request":
        return cls.freeze(
            {
                "model": FIXTURE_MODEL,
                "instructions": instructions,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}],
                "text": proposal_format(),
                "max_output_tokens": integer(output_ceiling, 16),
                "store": False,
                "background": False,
                "stream": False,
                "truncation": "disabled",
                "conversation": None,
                "previous_response_id": None,
                "tools": [],
                "tool_choice": "none",
                "parallel_tool_calls": False,
                "context_management": [],
                "service_tier": "default",
            }
        )

    @classmethod
    def freeze(cls, payload: dict[str, Any]) -> "Request":
        request = cls(canonical(payload), digest(payload))
        request.generation()
        return request

    def generation(self) -> dict[str, Any]:
        data = keys(json.loads(self.body), set(GENERATION_FIELDS))
        require(canonical(data) == self.body and digest(data) == self.sha256, "request_mutated")
        require(data["model"] == FIXTURE_MODEL, "unproven_model_capabilities")
        for name in ("instructions",):
            require(
                isinstance(data[name], str) and 0 < len(data[name]) <= 1_000_000, "invalid_text"
            )
        require(isinstance(data["input"], list) and len(data["input"]) == 1, "invalid_input")
        item = keys(data["input"][0], {"role", "content"})
        require(item["role"] == "user" and isinstance(item["content"], list), "invalid_input")
        require(len(item["content"]) == 1, "invalid_input")
        content = keys(item["content"][0], {"type", "text"})
        require(
            content["type"] == "input_text"
            and isinstance(content["text"], str)
            and 0 < len(content["text"]) <= 1_000_000,
            "invalid_input",
        )
        integer(data["max_output_tokens"], 16)
        # Canonical comparison also rejects 0 substituted for false, and unknown fields.
        fixed = {
            "text": proposal_format(),
            "store": False,
            "background": False,
            "stream": False,
            "truncation": "disabled",
            "conversation": None,
            "previous_response_id": None,
            "tools": [],
            "tool_choice": "none",
            "parallel_tool_calls": False,
            "context_management": [],
            "service_tier": "default",
        }
        require(
            canonical({k: data[k] for k in fixed}) == canonical(fixed), "unsafe_request_settings"
        )
        return data

    def counting(self) -> dict[str, Any]:
        # The counting endpoint does not accept generation-only settings. This is
        # a closed projection, not a separately assembled prompt or schema.
        return {k: v for k, v in self.generation().items() if k in COUNT_FIELDS}


@dataclass(frozen=True)
class FixtureCapabilities:
    model: str = FIXTURE_MODEL
    generation_fields: frozenset[str] = GENERATION_FIELDS
    count_fields: frozenset[str] = COUNT_FIELDS
    exact_count: bool = True
    reasoning_in_output_cap: bool = True
    maximum_output: int = 100_000

    def admit(self, request: Request) -> None:
        data = request.generation()
        require(
            self.model == data["model"]
            and self.generation_fields == GENERATION_FIELDS
            and self.count_fields == COUNT_FIELDS
            and self.exact_count is True
            and self.reasoning_in_output_cap is True
            and type(self.maximum_output) is int
            and data["max_output_tokens"] <= self.maximum_output,
            "unsupported_fixture_capabilities",
        )


@dataclass(frozen=True)
class TransportSettings:
    """Future SDK construction must use max_retries=0; no SDK is constructed here."""

    max_retries: int = 0
    automatic_replay: bool = False
    follow_redirects: bool = False
    model_fallback: bool = False

    def admit(self) -> None:
        require(
            type(self.max_retries) is int
            and self.max_retries == 0
            and self.automatic_replay is False
            and self.follow_redirects is False
            and self.model_fallback is False,
            "unsafe_transport_settings",
        )

    def sdk_options(self) -> dict[str, int]:
        self.admit()
        return {"max_retries": 0}
