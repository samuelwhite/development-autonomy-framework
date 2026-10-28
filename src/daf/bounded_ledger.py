"""Additive offline request ledger. Never opens a controller journal or issues authority."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bounded_contract import Budget, Capability, Context, Observation, Scope, integer, texts
from .contract import Refused, canonical, digest, require
from .responses_request import Request

APPLICATION = 0x44414642


class Ledger:
    def __init__(self, path: Path, scope: Scope, budget: Budget, *, now: int):
        scope.validate(scope.starts_at)
        integer(now)
        budget.validate()
        require(
            path.name == "bounded-fixture.sqlite"
            and not path.is_symlink()
            and not (path.parent / "journal.sqlite").exists(),
            "isolated_fixture_ledger_required",
        )
        # Inspect existing files read-only before any PRAGMA or table mutation.
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as prior:
                require(
                    prior.execute("PRAGMA application_id").fetchone()[0] == APPLICATION,
                    "foreign_ledger_refused",
                )
        self.scope, self.budget = scope, budget
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        try:
            self.initialize(scope, budget)
        except BaseException:
            self.close()
            raise

    def initialize(self, scope: Scope, budget: Budget) -> None:
        with self.transaction():
            self.db.execute(f"PRAGMA application_id={APPLICATION}")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY "
                "CHECK(id=1), body TEXT NOT NULL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, body "
                "TEXT NOT NULL, tokens INTEGER NOT NULL, money INTEGER NOT NULL)"
            )
            self.db.execute("""CREATE TABLE IF NOT EXISTS requests(
                id TEXT PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id),
                segment INTEGER NOT NULL,
                binding TEXT NOT NULL, tokens INTEGER NOT NULL, money INTEGER NOT NULL,
                phase TEXT NOT NULL, response_id TEXT UNIQUE, sequence INTEGER NOT NULL DEFAULT 0,
                usage TEXT, checkpoint TEXT, UNIQUE(job,segment))""")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS observations(request TEXT NOT "
                "NULL REFERENCES requests(id), sequence INTEGER NOT NULL, "
                "body TEXT NOT NULL, PRIMARY KEY(request,sequence))"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, "
                "request TEXT, kind TEXT NOT NULL, body TEXT NOT NULL)"
            )
            for table in ("policy", "jobs", "observations", "events"):
                for operation in ("UPDATE", "DELETE"):
                    self.db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_{operation} "
                        f"BEFORE {operation} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'immutable ledger'); END"
                    )
            self.db.execute(
                "CREATE TRIGGER IF NOT EXISTS requests_delete BEFORE DELETE "
                "ON requests BEGIN SELECT RAISE(ABORT,'retained exposure'); END"
            )
            self.db.execute(
                "CREATE TRIGGER IF NOT EXISTS requests_binding BEFORE "
                "UPDATE OF id,job,segment,binding,tokens,money ON requests "
                "BEGIN SELECT RAISE(ABORT,'immutable reservation'); END"
            )
            binding = canonical(
                {
                    "version": 1,
                    "scope": asdict(scope),
                    "budget": asdict(budget),
                    "capability": asdict(Capability()),
                }
            )
            old = self.db.execute("SELECT body FROM policy WHERE id=1").fetchone()
            require(old is None or old[0] == binding, "ledger_policy_changed")
            self.db.execute("INSERT OR IGNORE INTO policy VALUES(1,?)", (binding,))

    def close(self) -> None:
        self.db.close()

    def verify_policy(self) -> None:
        expected = canonical(
            {
                "version": 1,
                "scope": asdict(self.scope),
                "budget": asdict(self.budget),
                "capability": asdict(Capability()),
            }
        )
        require(
            self.db.execute("SELECT body FROM policy WHERE id=1").fetchone()[0] == expected,
            "ledger_policy_changed",
        )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def event(self, request: str | None, kind: str, data: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO events(request,kind,body) VALUES(?,?,?)", (request, kind, canonical(data))
        )

    def job(
        self, identity: str, attempt: int, normal: Budget, grace: Budget, criteria: list[str]
    ) -> None:
        require(
            identity.startswith("fixture-") and len(identity) <= 100, "fixture_identity_required"
        )
        integer(attempt, 1)
        normal.validate()
        integer(grace.tokens)
        integer(grace.micro_usd)
        require(bool(texts(criteria, 20, 512)), "acceptance_criteria_missing")
        tokens, money = normal.tokens + grace.tokens, normal.micro_usd + grace.micro_usd
        integer(tokens, 1)
        integer(money, 1)
        body = canonical(
            {
                "id": identity,
                "attempt": attempt,
                "scope": asdict(self.scope),
                "normal": asdict(normal),
                "grace": asdict(grace),
                "criteria": criteria,
            }
        )
        with self.transaction():
            self.verify_policy()
            old = self.db.execute("SELECT body FROM jobs WHERE id=?", (identity,)).fetchone()
            if old:
                require(old[0] == body, "job_binding_changed")
                return
            held = self.db.execute(
                "SELECT COALESCE(SUM(tokens),0),COALESCE(SUM(money),0) FROM jobs"
            ).fetchone()
            require(
                held[0] + tokens <= self.budget.tokens and held[1] + money <= self.budget.micro_usd,
                "budget_blocked",
            )
            self.db.execute("INSERT INTO jobs VALUES(?,?,?,?)", (identity, body, tokens, money))
            self.event(
                None,
                "job_reserved_fixture_only",
                {"job": identity, "tokens": tokens, "micro_usd": money},
            )

    def read(self, request_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        require(row is not None, "request_missing")
        return dict(row)

    def reserve(self, job: str, segment: int, request: Request, *, now: int) -> str:
        self.scope.validate(now)
        integer(segment, 1)
        capability = Capability()
        inputs, tokens, money = capability.bounds(request)
        context = request.generation()["input"][0]["content"][0]["text"]
        context_object = Context(context, digest(json.loads(context)))
        data = context_object.validate()
        with self.transaction():
            self.verify_policy()
            job_row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            require(job_row is not None, "job_missing")
            job_data = json.loads(job_row["body"])
            require(
                data["criteria"] == job_data["criteria"]
                and data["revision"] == self.scope.source_revision,
                "context_scope_changed",
            )
            binding = canonical(
                {
                    "job": job_data,
                    "segment": segment,
                    "request": request.body,
                    "request_sha256": request.sha256,
                    "count_sha256": digest(request.counting()),
                    "context_sha256": context_object.sha256,
                    "capability": asdict(capability),
                    "proof_sha256": capability.fingerprint,
                    "input_tokens": inputs,
                    "max_tokens": tokens,
                    "max_micro_usd": money,
                }
            )
            identity = digest(json.loads(binding))
            prior = self.db.execute(
                "SELECT id,binding FROM requests WHERE job=? AND segment=?", (job, segment)
            ).fetchone()
            if prior:
                require(prior["binding"] == binding, "reservation_changed")
                return str(prior["id"])
            previous = self.db.execute(
                "SELECT * FROM requests WHERE job=? ORDER BY segment DESC LIMIT 1", (job,)
            ).fetchone()
            if previous:
                require(
                    previous["phase"] == "segment_ready_in_fixture_only",
                    "unknown_exposure"
                    if previous["phase"] == "unknown_exposure"
                    else "checkpoint_incomplete",
                )
                require(segment == previous["segment"] + 1, "segment_sequence_invalid")
                require(previous["checkpoint"] == context, "checkpoint_changed")
                self.verify_checkpoint(dict(previous))
            else:
                require(segment == 1 and data["confirmed"] is None, "checkpoint_incomplete")
            held = self.db.execute(
                "SELECT COALESCE(SUM(tokens),0),COALESCE(SUM(money),0) FROM requests WHERE job=?",
                (job,),
            ).fetchone()
            require(
                held[0] + tokens <= job_row["tokens"] and held[1] + money <= job_row["money"],
                "budget_blocked",
            )
            # A known contract breach invalidates this fixture ledger, not merely
            # the offending job. Unknown exposure may exceed its claimed hold.
            require(
                not self.db.execute(
                    "SELECT 1 FROM requests WHERE phase='unknown_exposure'"
                ).fetchone(),
                "unknown_exposure",
            )
            self.db.execute(
                "INSERT INTO "
                "requests(id,job,segment,binding,tokens,money,phase) "
                "VALUES(?,?,?,?,?,?,'reserved')",
                (identity, job, segment, binding, tokens, money),
            )
            self.event(
                identity, "request_reserved_fixture_only", {"tokens": tokens, "micro_usd": money}
            )
            return identity

    def claim(self, request_id: str, request: Request, scope: Scope, *, now: int) -> bool:
        scope.validate(now)
        require(scope == self.scope, "dispatch_scope_changed")
        Capability().bounds(request)
        with self.transaction():
            self.verify_policy()
            row = self.read(request_id)
            binding = json.loads(row["binding"])
            require(
                binding["request"] == request.body and binding["request_sha256"] == request.sha256,
                "dispatch_request_changed",
            )
            if row["phase"] != "reserved":
                if row["phase"] == "dispatching":
                    self.unknown(request_id, "recovered_dispatch_intent")
                return False
            require(
                not self.db.execute(
                    "SELECT 1 FROM requests WHERE phase='unknown_exposure'"
                ).fetchone(),
                "unknown_exposure",
            )
            self.db.execute("UPDATE requests SET phase='dispatching' WHERE id=?", (request_id,))
            self.event(request_id, "durable_dispatch_intent", {"request_sha256": request.sha256})
            return True

    def unknown(self, request_id: str, reason: str) -> None:
        self.db.execute("UPDATE requests SET phase='unknown_exposure' WHERE id=?", (request_id,))
        self.event(request_id, "unknown_exposure", {"reason": reason})

    def record(self, observation: Observation) -> dict[str, Any]:
        # Only the closed offline adapter supplies these observations. There is
        # intentionally no HTTP endpoint, worker-written receipt or SDK callback.
        with self.transaction():
            self.verify_policy()
            row = self.read(observation.request_id)
            require(row["phase"] != "reserved", "dispatch_intent_missing")
            try:
                require(type(observation) is Observation, "untrusted_observation")
                observation.validate()
                raw = canonical(asdict(observation))
                old = self.db.execute(
                    "SELECT body FROM observations WHERE request=? AND sequence=?",
                    (observation.request_id, observation.sequence),
                ).fetchone()
                if old:
                    require(old[0] == raw, "conflicting_observation")
                    return self.read(observation.request_id)
                require(observation.sequence == row["sequence"] + 1, "observation_out_of_order")
                require(
                    row["response_id"] in (None, observation.response_id),
                    "response_identity_mismatch",
                )
                previous = json.loads(row["usage"]) if row["usage"] else None
                if previous:
                    require(not previous["complete"], "terminal_observation_changed")
                    require(
                        observation.input_tokens >= previous["input_tokens"]
                        and observation.output_tokens >= previous["output_tokens"]
                        and observation.cached_input_tokens >= previous["cached_input_tokens"]
                        and observation.reasoning_tokens >= previous["reasoning_tokens"],
                        "usage_regressed",
                    )
                # Preserve valid known usage BEFORE enforcing the promised bound.
                self.db.execute(
                    "INSERT INTO observations VALUES(?,?,?)",
                    (observation.request_id, observation.sequence, raw),
                )
                self.db.execute(
                    "UPDATE requests SET response_id=?,sequence=?,usage=? WHERE id=?",
                    (observation.response_id, observation.sequence, raw, observation.request_id),
                )
                binding = json.loads(row["binding"])
                maximum = json.loads(binding["request"])["max_output_tokens"]
                require(
                    observation.input_tokens <= binding["input_tokens"]
                    and observation.output_tokens <= maximum,
                    "proven_bound_breached",
                )
                if observation.complete:
                    require(observation.input_tokens == binding["input_tokens"], "counter_mismatch")
                    # A conflict/ambiguity is never cleared by a later claim.
                    if row["phase"] != "unknown_exposure":
                        self.db.execute(
                            "UPDATE requests SET phase='checkpoint_incomplete' WHERE id=?",
                            (observation.request_id,),
                        )
                self.event(
                    observation.request_id,
                    "confirmed_fixture_usage" if observation.complete else "partial_fixture_usage",
                    {
                        "gross_tokens": observation.input_tokens + observation.output_tokens,
                        "micro_usd": self.price(observation),
                    },
                )
            except (Refused, ValueError, TypeError, KeyError) as error:
                self.unknown(
                    observation.request_id,
                    str(error) if isinstance(error, Refused) else "malformed_observation",
                )
        return self.read(observation.request_id)

    @staticmethod
    def price(observation: Observation) -> int:
        cap = Capability()
        return (
            observation.input_tokens * cap.input_micro_usd
            + observation.output_tokens * cap.output_micro_usd
        )

    def checkpoint(
        self, request_id: str, diff: str, test_outputs: list[str], blockers: list[str]
    ) -> Context:
        with self.transaction():
            self.verify_policy()
            row = self.read(request_id)
            require(
                row["phase"] in {"checkpoint_incomplete", "segment_ready_in_fixture_only"},
                "checkpoint_incomplete",
            )
            context = self.checkpoint_context(row, diff, test_outputs, blockers)
            require(row["checkpoint"] in (None, context.body), "checkpoint_changed")
            if row["checkpoint"] is None:
                self.db.execute(
                    "UPDATE requests SET "
                    "checkpoint=?,phase='segment_ready_in_fixture_only' WHERE id=?",
                    (context.body, request_id),
                )
                self.event(request_id, "checkpoint_saved_fixture_only", {"sha256": context.sha256})
            return context

    def checkpoint_context(
        self, row: dict[str, Any], diff: str, tests: list[str], blockers: list[str]
    ) -> Context:
        require(row["usage"] is not None, "checkpoint_incomplete")
        observation = Observation(**json.loads(row["usage"]))
        observation.validate()
        require(observation.complete, "checkpoint_incomplete")
        binding = json.loads(row["binding"])
        return Context.build(
            self.scope.source_revision,
            binding["job"]["criteria"],
            diff,
            tests,
            blockers,
            {
                "request_id": row["id"],
                "response_id": observation.response_id,
                "gross_tokens": observation.input_tokens + observation.output_tokens,
                "micro_usd": self.price(observation),
                "scope_sha256": digest(asdict(self.scope)),
            },
        )

    def verify_checkpoint(self, row: dict[str, Any]) -> None:
        data = json.loads(row["checkpoint"])
        rebuilt = self.checkpoint_context(row, data["diff"], data["test_outputs"], data["blockers"])
        require(rebuilt.body == row["checkpoint"], "checkpoint_changed")

    def summary(self) -> dict[str, Any]:
        rows = [dict(row) for row in self.db.execute("SELECT * FROM requests ORDER BY job,segment")]
        known, money, incomplete = 0, 0, False
        details = []
        for row in rows:
            usage = Observation(**json.loads(row["usage"])) if row["usage"] else None
            gross = usage.input_tokens + usage.output_tokens if usage else None
            known += gross or 0
            money += self.price(usage) if usage else 0
            incomplete |= usage is None or not usage.complete or row["phase"] == "unknown_exposure"
            details.append(
                {
                    "request_id": row["id"],
                    "job": row["job"],
                    "segment": row["segment"],
                    "status": row["phase"],
                    "gross_tokens": gross,
                    "maximum_tokens": row["tokens"],
                    "maximum_micro_usd": row["money"],
                }
            )
        return {
            "authority": "offline_fixture_only",
            "live_transport": "transport_unbounded",
            "actual_complete": not incomplete,
            "known_gross_tokens": known,
            "known_micro_usd": money,
            "reserved_tokens": sum(row["tokens"] for row in rows),
            "reserved_micro_usd": sum(row["money"] for row in rows),
            "requests": details,
        }
