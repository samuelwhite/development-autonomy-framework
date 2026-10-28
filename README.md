# DAF — Development Autonomy Framework

**v0.1 Developer Preview · offline evaluation candidate**

AI development needs more than generated code. It needs a durable account of what
was requested, what was attempted, what was checked, what it consumed and where
work must stop. DAF explores that control layer with small, inspectable Python
components and deterministic demonstrations.

This preview runs **synthetic development only**. It does not connect to a model,
authenticate an owner, approve execution, edit a product repository, merge code,
send notifications or deploy. Its fixture budgets are not proof of provider
spending limits. See [capabilities and limitations](docs/capabilities.md).

**Candidate status:** Apache-2.0 licensed, privately staged for validation.
Public release requires completed hosted CI, security and disclosure checks,
and separate owner approval. See [licensing](LICENSING.md).

## Quick start

Python 3.12 or newer; no server, Node.js, API key or runtime package download is
needed to run directly from the unpacked source directory.

```text
cd src
python -m daf demo --output ../demo-output
```

Open `demo-output/index.html` in your browser. It is a self-contained, read-only
Mission Control snapshot. The accompanying JSON and SQLite journals let you
inspect the underlying results. Pick a **new** output directory each time: DAF
refuses to overwrite or reopen an existing demo directory.

For an installed command, from the candidate root:

```text
python -m venv .venv
```

Activate with `.venv\Scripts\Activate.ps1` on Windows PowerShell, or
`source .venv/bin/activate` on Linux/macOS, then:

```text
python -m pip install .
daf-preview demo --output demo-output
```

Installation downloads the pinned build backend, not a model client. The installed
runtime uses the standard library only. To avoid downloads entirely, use the
source quick start or an already built wheel with `pip install --no-index`.

## What the demonstration proves

- Three dependent milestones progress using separate simulated developer and
  validator outputs. A failed attempt stays failed after a successful correction.
- Restarted fixture connections reconcile existing jobs without duplicating them.
- A scope exception remains blocked; a committed stop admits no new job.
- A two-segment experiment reserves fixture tokens and currency atomically,
  checkpoints bounded context and refuses a third segment that exceeds its budget.
- The dashboard distinguishes fixture acceptance, unavailable planning/CI evidence,
  merging and deployment. No status is inferred from an absent record.

These are automated offline tests of the implementation, not evidence of real
provider reliability or operating-system isolation.

## Explore and contribute

[Demo walkthrough](docs/demo.md) · [Architecture](docs/architecture.md) ·
[Security](SECURITY.md) · [Roadmap](docs/roadmap.md) ·
[Contributing](CONTRIBUTING.md) · [Release checklist](docs/release-checklist.md)

The intended repository is `development-autonomy-framework`; the package name is
`daf-developer-preview`. No package registry release is available from this candidate.
Do not install an unrelated package from a public index by guessing its name.
