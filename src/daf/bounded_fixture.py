"""Deterministic no-I/O transport. No injectable send callable or live fallback."""

import json
from dataclasses import dataclass, field
from typing import Any

from .bounded_contract import Capability, Observation, Scope
from .bounded_ledger import Ledger
from .contract import Refused, require
from .responses_request import Request


@dataclass
class FixtureTransport:
    outputs: int = 16
    fault: str = ""
    sends: list[str] = field(default_factory=list)

    def generate(self, identity: str, request: Request) -> Observation:
        require(type(self) is FixtureTransport, "transport_unbounded")
        inputs, _, _ = Capability().bounds(request)
        self.sends.append(identity)
        if self.fault:
            raise Refused("simulated_ambiguous_dispatch")
        return Observation(identity, "fixture-response-" + identity, 1, inputs, self.outputs)


def dispatch(
    ledger: Ledger,
    identity: str,
    request: Request,
    scope: Scope,
    transport: FixtureTransport,
    *,
    now: int,
) -> dict[str, Any]:
    require(type(transport) is FixtureTransport, "transport_unbounded")
    if ledger.claim(identity, request, scope, now=now):
        try:
            # Recheck immutable settings after durable intent, immediately before
            # the only simulated send. There is no real transport implementation.
            scope.validate(now)
            Capability().bounds(request)
            require(scope == ledger.scope, "dispatch_scope_changed")
            ledger.verify_policy()
            row = ledger.read(identity)
            require(
                row["phase"] == "dispatching"
                and json.loads(row["binding"])["request"] == request.body,
                "dispatch_request_changed",
            )
            observation = FixtureTransport.generate(transport, identity, request)
            ledger.record(observation)
        except (Refused, OSError, ValueError, TypeError):
            with ledger.transaction():
                ledger.unknown(identity, "simulated_dispatch_or_receipt_unknown")
    return ledger.read(identity)
