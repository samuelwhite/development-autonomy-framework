"""Run an inert two-segment demonstration in a NEW isolated directory."""

import argparse
import json
from pathlib import Path
from typing import Any

from .bounded_contract import Budget, Capability, Context, Scope
from .bounded_fixture import FixtureTransport, dispatch
from .bounded_ledger import Ledger
from .contract import Refused, require


def demonstration(directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    scope = Scope(
        "a" * 64, "b" * 40, "c" * 64, "d" * 64, "e" * 64, Capability().fingerprint, 100, 200
    )
    budget = Budget(3000, 10000)
    ledger = Ledger(directory / "bounded-fixture.sqlite", scope, budget, now=101)
    transport = FixtureTransport()
    try:
        criteria = ["Demonstrate bounded continuation offline"]
        ledger.job("fixture-demo", 1, Budget(2800, 9500), Budget(200, 500), criteria)
        context = Context.build(scope.source_revision, criteria)
        for segment in (1, 2):
            request = context.request()
            identity = ledger.reserve("fixture-demo", segment, request, now=101)
            dispatch(ledger, identity, request, scope, transport, now=101)
            context = ledger.checkpoint(
                identity, "+ inert fixture diff", ["fixture checks passed"], []
            )
            # A repeated dispatch is reconciliation only.
            dispatch(ledger, identity, request, scope, transport, now=102)
        try:
            ledger.reserve("fixture-demo", 3, context.request(), now=102)
        except Refused as error:
            require(str(error) == "budget_blocked", "unexpected_demo_refusal")
        else:
            raise Refused("demo_budget_boundary_not_reached")
        result = {
            **ledger.summary(),
            "next_segment": "budget_blocked",
            "simulated_sends": len(transport.sends),
            "provider_requests": 0,
            "approval_receipts": 0,
            "published_changes": 0,
        }
        (directory / "demonstration.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        return result
    finally:
        ledger.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(demonstration(args.output), indent=2))


if __name__ == "__main__":
    main()
