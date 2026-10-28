# Architecture

DAF separates a proposed development plan from durable execution observations.
Planning should ultimately stay in the project's planning system; an execution
journal records attempts and evidence rather than becoming a competing task database.
The preview accepts only schema-1 synthetic plan documents. It imports no remote
planning records.

```text
Synthetic plan + fixture marker
             |
             v
        Plan validation
             |
             v
 Engine <--> SQLite execution journal <--> durable stop gate
    |
    v
Built-in fixture adapter --> independent simulated validator evidence
             |
             v
Static Mission Control snapshot (read-only, no HTTP service)

Separate bounded transport experiment:
immutable scope --> atomic reservations --> once-only simulated dispatch
                 --> exact fixture usage --> bounded continuation checkpoint
```

The progression engine and bounded ledger are **separate experiments**. The
preview does not claim to combine them into a production admission boundary.

`contract.py` validates scope, dependency order, acceptance criteria, immutable
hashes and budget shapes. `engine.py` advances synthetic milestones and verifies
validator bindings. `store.py` owns execution history and the unsent outbox.
`stop_control.py` orders admissions against a durable stop independently of the
main journal. `bounded_ledger.py` retains reserved exposure across uncertain
outcomes, and `bounded_contract.py` validates exact context and fixture capability.

The stop gate protects **new committed admissions**. Already admitted operations
can remain uncertain. A Python object check, SQLite file or local cancellation is
not a sandbox, external spending guarantee or proof of remote cancellation.

The static viewer consumes only the demonstration's safe projection. It cannot
read arbitrary journals, receive approval requests or mutate execution state.
The demo's fixture marker is shipped test data; it authenticates nobody and is
never a production approval receipt.
