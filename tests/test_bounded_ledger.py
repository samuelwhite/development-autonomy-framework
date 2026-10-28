"""Adversarial no-network/no-process fixtures; passing is not production cap proof."""

import json
import socket
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import httpx
import pytest

from daf.bounded_contract import Budget, Capability, Context, Observation, Scope
from daf.bounded_demo import demonstration
from daf.bounded_fixture import FixtureTransport, dispatch
from daf.bounded_ledger import Ledger
from daf.contract import Refused, canonical, digest
from daf.responses_request import Request


class Crash(BaseException):
    pass


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline fixture attempted external I/O")

    for target, name in (
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
        (socket.socket, "connect"),
        (httpx.Client, "send"),
        (subprocess, "Popen"),
        (subprocess, "run"),
    ):
        monkeypatch.setattr(target, name, forbidden)


@pytest.fixture
def example(tmp_path):
    scope = Scope(
        "a" * 64, "b" * 40, "c" * 64, "d" * 64, "e" * 64, Capability().fingerprint, 100, 200
    )
    path = tmp_path / "bounded-fixture.sqlite"
    ledger = Ledger(path, scope, Budget(220000, 1000000), now=101)
    ledger.job(
        "fixture-one", 1, Budget(200000, 900000), Budget(20000, 100000), ["fixture criterion"]
    )
    context = Context.build(scope.source_revision, ["fixture criterion"])
    yield ledger, context, scope, path
    ledger.close()


def prepare(example, segment=1, context=None):
    ledger, initial, scope, _ = example
    request = (context or initial).request()
    identity = ledger.reserve("fixture-one", segment, request, now=101)
    return ledger, identity, request, scope


def observed(identity, request, sequence=1, **changes):
    return replace(
        Observation(
            identity, "fixture-response-" + identity, sequence, Capability().count(request), 16
        ),
        **changes,
    )


def test_multiple_bounded_segments_never_create_authority(example):
    ledger, identity, request, scope = prepare(example)
    transport = FixtureTransport()
    assert (
        dispatch(ledger, identity, request, scope, transport, now=101)["phase"]
        == "checkpoint_incomplete"
    )
    context = ledger.checkpoint(identity, "+ inert proposed change", ["fixture tests passed"], [])
    assert context == ledger.checkpoint(
        identity, "+ inert proposed change", ["fixture tests passed"], []
    )
    _, second, next_request, _ = prepare(example, 2, context)
    assert (
        dispatch(ledger, second, next_request, scope, transport, now=102)["phase"]
        == "checkpoint_incomplete"
    )
    summary = ledger.summary()
    assert summary["actual_complete"] is True
    assert summary["known_gross_tokens"] == sum(
        Capability().count(r) + 16 for r in (request, next_request)
    )
    assert summary["known_micro_usd"] == sum(
        Capability().count(r) * 2 + 16 * 3 for r in (request, next_request)
    )
    assert summary["reserved_tokens"] == sum(
        Capability().count(r) + 32 for r in (request, next_request)
    )
    assert summary["live_transport"] == "transport_unbounded"
    assert summary["authority"] == "offline_fixture_only" and len(transport.sends) == 2


@pytest.mark.parametrize("delta,accepted", [(0, True), (-1, False)])
@pytest.mark.parametrize("dimension", ["tokens", "micro_usd"])
def test_exact_job_and_aggregate_boundaries(tmp_path, example, delta, accepted, dimension):
    _, context, scope, _ = example
    request = context.request()
    _, tokens, money = Capability().bounds(request)
    budget = Budget(
        tokens + (delta if dimension == "tokens" else 0),
        money + (delta if dimension == "micro_usd" else 0),
    )
    folder = tmp_path / "edge"
    folder.mkdir()
    ledger = Ledger(folder / "bounded-fixture.sqlite", scope, budget, now=101)
    try:
        ledger.job("fixture-edge", 1, budget, Budget(0, 0), ["fixture criterion"])
        if accepted:
            identity = ledger.reserve("fixture-edge", 1, request, now=101)
            dispatch(ledger, identity, request, scope, FixtureTransport(), now=101)
            ledger.checkpoint(identity, "", [], [])
            assert ledger.summary()["reserved_tokens"] == tokens  # No refund.
        else:
            with pytest.raises(Refused, match="budget_blocked"):
                ledger.reserve("fixture-edge", 1, request, now=101)
            assert not ledger.summary()["requests"]
        with pytest.raises(Refused, match="budget_blocked"):
            ledger.job("fixture-other", 1, Budget(1, 1), Budget(0, 0), ["fixture criterion"])
    finally:
        ledger.close()


@pytest.mark.parametrize("field", list(asdict(Capability())))
def test_no_caller_capability_or_proof_can_enable_a_transport(field):
    value = asdict(Capability())[field]
    changed = value + 1 if type(value) is int else value + "-unproven"
    with pytest.raises(Refused, match="transport_unbounded"):
        replace(Capability(), **{field: changed}).validate()


@pytest.mark.parametrize("value", [True, False, -1, 0, 1.1, "10", None, 2**63])
def test_explicit_budget_units_only(value):
    with pytest.raises(Refused):
        Budget(value, 1).validate()
    with pytest.raises(Refused):
        Budget(1, value).validate()


@pytest.mark.parametrize(
    "field",
    list(asdict(Scope("a" * 64, "b" * 40, "c" * 64, "d" * 64, "e" * 64, "f" * 64, 100, 200))),
)
def test_wrong_dispatch_scope_never_sends(example, field):
    ledger, identity, request, scope = prepare(example)
    value = getattr(scope, field)
    bad = replace(scope, **{field: value + 1 if type(value) is int else "0" * len(value)})
    transport = FixtureTransport()
    with pytest.raises(Refused):
        dispatch(ledger, identity, request, bad, transport, now=101)
    assert not transport.sends and ledger.read(identity)["phase"] == "reserved"


@pytest.mark.parametrize("now", [99, 200, 201, True])
def test_expired_or_not_started_reservations_and_dispatch_refused(example, now):
    ledger, identity, request, scope = prepare(example)
    with pytest.raises(Refused):
        ledger.reserve("fixture-one", 1, request, now=now)
    with pytest.raises(Refused):
        dispatch(ledger, identity, request, scope, FixtureTransport(), now=now)
    assert ledger.read(identity)["phase"] == "reserved"


def test_policy_cannot_expand_after_open(example):
    ledger, _, scope, path = example
    with pytest.raises(Refused, match="ledger_policy_changed"):
        Ledger(path, scope, Budget(220001, 1000000), now=101)
    ledger.budget = Budget(999999999, 999999999)
    with pytest.raises(Refused, match="ledger_policy_changed"):
        ledger.job("fixture-expanded", 1, Budget(1, 1), Budget(0, 0), ["criterion"])


@pytest.mark.parametrize(
    "point", ["before_intent", "after_intent", "after_send", "after_usage", "after_checkpoint"]
)
def test_crash_and_restart_never_repeat_possible_dispatch(example, monkeypatch, point):
    ledger, identity, request, scope = prepare(example)
    transport = FixtureTransport()
    claim, generate, record = ledger.claim, FixtureTransport.generate, ledger.record

    def crash_claim(*args, **kwargs):
        if point == "after_intent":
            claim(*args, **kwargs)
        raise Crash()

    def crash_generate(*args, **kwargs):
        generate(*args, **kwargs)
        raise Crash()

    def crash_record(*args):
        record(*args)
        raise Crash()

    if point != "after_checkpoint":
        with monkeypatch.context() as patch:
            if point in {"before_intent", "after_intent"}:
                patch.setattr(ledger, "claim", crash_claim)
            elif point == "after_send":
                patch.setattr(FixtureTransport, "generate", crash_generate)
            else:
                patch.setattr(ledger, "record", crash_record)
            with pytest.raises(Crash):
                dispatch(ledger, identity, request, scope, transport, now=101)
    else:
        dispatch(ledger, identity, request, scope, transport, now=101)
        ledger.checkpoint(identity, "", [], [])
    recovered = Ledger(example[3], scope, ledger.budget, now=102)
    try:
        result = dispatch(recovered, identity, request, scope, transport, now=102)
        assert len(transport.sends) == (0 if point == "after_intent" else 1)
        if point in {"after_intent", "after_send"}:
            assert result["phase"] == "unknown_exposure" and result["usage"] is None
            assert recovered.summary()["actual_complete"] is False
        elif point == "after_checkpoint":
            assert result["phase"] == "segment_ready_in_fixture_only"
        else:
            assert result["phase"] == "checkpoint_incomplete"
        assert dispatch(recovered, identity, request, scope, transport, now=102) == result
    finally:
        recovered.close()


@pytest.mark.parametrize("fault", ["timeout", "disconnect", "429", "500", "cancelled", "unknown"])
def test_ambiguous_failure_retains_full_hold_and_blocks_all_new_work(example, fault):
    ledger, identity, request, scope = prepare(example)
    transport = FixtureTransport(fault=fault)
    result = dispatch(ledger, identity, request, scope, transport, now=101)
    assert result["phase"] == "unknown_exposure" and result["usage"] is None
    assert ledger.summary()["reserved_tokens"] == Capability().bounds(request)[1]
    assert dispatch(ledger, identity, request, scope, transport, now=102) == result
    with pytest.raises(Refused, match="unknown_exposure"):
        ledger.reserve("fixture-one", 2, request, now=102)
    assert len(transport.sends) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"input_tokens": -1},
        {"input_tokens": True},
        {"output_tokens": None},
        {"cached_input_tokens": 999999},
        {"reasoning_tokens": 999999},
        {"sequence": 2},
        {"response_id": "wrong"},
        {"complete": 1},
    ],
)
def test_invalid_usage_is_unknown_not_zero(example, changes):
    ledger, identity, request, scope = prepare(example)
    ledger.claim(identity, request, scope, now=101)
    result = ledger.record(observed(identity, request, **changes))
    assert result["phase"] == "unknown_exposure" and result["usage"] is None
    assert ledger.summary()["requests"][0]["gross_tokens"] is None


def test_exact_gross_duplicate_and_partial_observations(example):
    ledger, identity, request, scope = prepare(example)
    ledger.claim(identity, request, scope, now=101)
    first = observed(
        identity,
        request,
        output_tokens=10,
        cached_input_tokens=5,
        reasoning_tokens=4,
        complete=False,
    )
    ledger.record(first)
    assert ledger.summary()["actual_complete"] is False
    terminal = replace(first, sequence=2, output_tokens=20, complete=True)
    saved = ledger.record(terminal)
    assert ledger.record(terminal) == saved
    assert ledger.summary()["known_gross_tokens"] == first.input_tokens + 20
    assert ledger.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2


@pytest.mark.parametrize("kind", ["regressed", "conflicting", "out_of_order", "terminal_changed"])
def test_conflicting_or_retrograde_usage_cannot_clear_exposure(example, kind):
    ledger, identity, request, scope = prepare(example)
    ledger.claim(identity, request, scope, now=101)
    first = observed(identity, request, complete=kind == "terminal_changed")
    ledger.record(first)
    next_value = replace(first, sequence=2, output_tokens=20)
    if kind == "regressed":
        next_value = replace(next_value, output_tokens=1)
    if kind == "conflicting":
        next_value = replace(next_value, sequence=1)
    if kind == "out_of_order":
        next_value = replace(next_value, sequence=3)
    assert ledger.record(next_value)["phase"] == "unknown_exposure"
    assert ledger.summary()["known_gross_tokens"] == first.input_tokens + 16
    assert ledger.record(first)["phase"] == "unknown_exposure"


def test_historical_overrun_is_preserved_and_never_refunded(example):
    ledger, identity, request, scope = prepare(example)
    ledger.claim(identity, request, scope, now=101)
    usage = observed(
        identity,
        request,
        input_tokens=903215,
        output_tokens=6624,
        cached_input_tokens=828544,
        reasoning_tokens=100,
    )
    assert ledger.record(usage)["phase"] == "unknown_exposure"
    assert ledger.summary()["known_gross_tokens"] == 909839
    assert 909839 - 220000 == 689839
    # A post-return warning or arbitrary process timeout cannot retract spend.
    assert ledger.summary()["known_gross_tokens"] > ledger.budget.tokens
    with pytest.raises(Refused, match="checkpoint_incomplete"):
        ledger.checkpoint(identity, "", [], [])


@pytest.mark.parametrize(
    "change", ["criteria", "diff", "tests", "blockers", "revision", "transcript", "window"]
)
def test_context_validation_has_no_transcript_or_truncation_fallback(example, change):
    ledger, context, scope, _ = example
    data = context.validate()
    if change == "criteria":
        data["criteria"] = []
    elif change == "diff":
        data["diff"] = "x" * 4097
    elif change == "tests":
        data["test_outputs"] = ["x" * 1025]
    elif change == "blockers":
        data["blockers"] = ["x"] * 9
    elif change == "revision":
        data["revision"] = "c" * 40
    elif change == "transcript":
        data["transcript"] = "raw history"
    else:
        data["test_outputs"] = ["x" * 1024] * 8
    invalid = Context(canonical(data), digest(data))
    with pytest.raises(Refused):
        ledger.reserve("fixture-one", 1, invalid.request(), now=101)


def test_checkpoint_must_match_verified_usage_and_exact_next_context(example):
    ledger, identity, request, scope = prepare(example)
    with pytest.raises(Refused, match="checkpoint_incomplete"):
        ledger.reserve("fixture-one", 2, request, now=101)
    dispatch(ledger, identity, request, scope, FixtureTransport(), now=101)
    checkpoint = ledger.checkpoint(identity, "+ fixture", ["bounded output"], [])
    with pytest.raises(Refused, match="checkpoint_changed"):
        ledger.reserve("fixture-one", 2, request, now=101)
    broken = json.loads(checkpoint.body)
    broken["confirmed"]["gross_tokens"] = 0
    ledger.db.execute("UPDATE requests SET checkpoint=? WHERE id=?", (canonical(broken), identity))
    with pytest.raises(Refused, match="checkpoint_changed"):
        ledger.reserve(
            "fixture-one", 2, Context(canonical(broken), digest(broken)).request(), now=101
        )


def test_concurrent_reservations_and_dispatch_claims_are_atomic(example):
    ledger, identity, request, scope = prepare(example)
    path = example[3]

    def claim():
        connection = Ledger(path, scope, ledger.budget, now=101)
        try:
            assert connection.reserve("fixture-one", 1, request, now=101) == identity
            return connection.claim(identity, request, scope, now=101)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _: claim(), range(4))) == 1
    assert ledger.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 1
    assert ledger.read(identity)["phase"] == "unknown_exposure"


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM requests",
        "UPDATE requests SET tokens=0",
        "UPDATE jobs SET tokens=9999999",
        "DELETE FROM jobs",
        "UPDATE policy SET body='{}'",
        "DELETE FROM observations",
        "DELETE FROM events",
    ],
)
def test_sql_cannot_refund_or_rewrite_accounting(example, sql):
    ledger, identity, request, scope = prepare(example)
    dispatch(ledger, identity, request, scope, FixtureTransport(), now=101)
    with pytest.raises(sqlite3.IntegrityError):
        ledger.db.execute(sql)
    assert ledger.summary()["reserved_tokens"] > 0


def test_no_historical_journal_adoption(example, tmp_path):
    ledger, _, scope, _ = example
    path = tmp_path / "journal.sqlite"
    path.write_bytes(b"historical evidence")
    with pytest.raises(Refused):
        Ledger(path, scope, ledger.budget, now=101)
    assert path.read_bytes() == b"historical evidence"
    with pytest.raises(Refused):
        Ledger(example[3], scope, ledger.budget, now=101)


def test_forged_transport_and_instance_callback_are_never_called(example):
    ledger, identity, request, scope = prepare(example)

    class Forged(FixtureTransport):
        pass

    with pytest.raises(Refused, match="transport_unbounded"):
        dispatch(ledger, identity, request, scope, Forged(), now=101)
    transport = FixtureTransport()
    transport.generate = lambda *a: pytest.fail("instance send override")
    assert (
        dispatch(ledger, identity, request, scope, transport, now=101)["phase"]
        == "checkpoint_incomplete"
    )


def test_mutation_after_intent_cannot_change_dispatched_request(example, monkeypatch):
    ledger, identity, request, scope = prepare(example)
    claim = ledger.claim

    def mutate(*a, **kw):
        result = claim(*a, **kw)
        changed = example[1].request(64)
        object.__setattr__(request, "body", changed.body)
        object.__setattr__(request, "sha256", changed.sha256)
        return result

    monkeypatch.setattr(ledger, "claim", mutate)
    transport = FixtureTransport()
    assert (
        dispatch(ledger, identity, request, scope, transport, now=101)["phase"]
        == "unknown_exposure"
    )
    assert not transport.sends


def test_repeatable_demonstration_has_no_authority_or_external_calls(tmp_path):
    first = demonstration(tmp_path / "first")
    second = demonstration(tmp_path / "second")
    assert first == second
    assert first["next_segment"] == "budget_blocked" and first["simulated_sends"] == 2
    assert (
        first["provider_requests"] == first["approval_receipts"] == first["published_changes"] == 0
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "real-model"),
        ("tools", [{}]),
        ("store", True),
        ("background", True),
        ("stream", True),
        ("truncation", "auto"),
        ("conversation", "external-context"),
        ("previous_response_id", "resp_old"),
        ("parallel_tool_calls", True),
        ("context_management", [{}]),
        ("service_tier", "auto"),
        ("tool_choice", "auto"),
        ("max_output_tokens", True),
        ("max_output_tokens", 15),
        ("max_output_tokens", None),
        ("metadata", {}),
        ("store", 0),
        ("text", {}),
    ],
)
def test_reused_immutable_request_refuses_unsupported_settings(example, field, value):
    data = example[1].request().generation()
    data[field] = value
    with pytest.raises(Refused):
        Request.freeze(data)


def test_racing_jobs_cannot_oversubscribe_aggregate(tmp_path, example):
    scope = example[2]
    folder = tmp_path / "race"
    folder.mkdir()
    path = folder / "bounded-fixture.sqlite"
    budget = Budget(100, 100)
    initial = Ledger(path, scope, budget, now=101)
    initial.close()

    def reserve(index):
        ledger = Ledger(path, scope, budget, now=101)
        try:
            ledger.job("fixture-" + str(index), 1, Budget(100, 100), Budget(0, 0), ["criterion"])
            return True
        except Refused as error:
            assert str(error) == "budget_blocked"
            return False
        finally:
            ledger.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 1


def test_crash_inside_reservation_rolls_back_all_exposure(example, monkeypatch):
    ledger, context, scope, _ = example
    event = ledger.event

    def crash(*a):
        event(*a)
        raise Crash()

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "event", crash)
        with pytest.raises(Crash):
            ledger.reserve("fixture-one", 1, context.request(), now=101)
    assert ledger.summary()["requests"] == []
    identity = ledger.reserve("fixture-one", 1, context.request(), now=101)
    assert ledger.read(identity)["phase"] == "reserved"


@pytest.mark.parametrize("field", ["cached_input_tokens", "reasoning_tokens"])
def test_subset_counters_are_monotonic_too(example, field):
    ledger, identity, request, scope = prepare(example)
    ledger.claim(identity, request, scope, now=101)
    first = observed(identity, request, cached_input_tokens=5, reasoning_tokens=5, complete=False)
    ledger.record(first)
    assert ledger.record(replace(first, sequence=2, **{field: 4}))["phase"] == "unknown_exposure"


def test_expired_ledger_can_be_inspected_without_new_dispatch(example):
    ledger, identity, request, scope = prepare(example)
    dispatch(ledger, identity, request, scope, FixtureTransport(), now=101)
    expired = Ledger(example[3], scope, ledger.budget, now=999)
    try:
        assert expired.summary() == ledger.summary()
        with pytest.raises(Refused, match="execution_window_closed"):
            dispatch(expired, identity, request, scope, FixtureTransport(), now=999)
    finally:
        expired.close()
