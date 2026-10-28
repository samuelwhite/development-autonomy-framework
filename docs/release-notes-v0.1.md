# DAF v0.1 Developer Preview — source notes

**Public source preview · package version `0.1.0.dev1` · offline only**

These notes describe the source available in this repository. No formal GitHub
Release, version tag or package registry release is available.

DAF (Development Autonomy Framework) explores the control layer around AI development:
explicit plans, retained evidence, recovery and clear stopping boundaries. This first
Developer Preview makes those ideas available as inspectable Python components and
an offline Mission Control demonstration.

## Included

- Synthetic milestone progression with dependency ordering and independent fixture
  validation. Failed attempts remain visible after successful correction.
- Durable SQLite journals and reconciliation across connection restarts without
  duplicate fixture dispatch.
- Committed stop fencing for new admissions and retention of uncertain operations.
- Atomic fixture reservations, bounded context checkpoints and refusal when another
  synthetic segment would exceed its budget.
- A static, read-only Mission Control snapshot plus JSON evidence for inspection.
- Standard-library-only runtime, local wheel/source builds and Apache-2.0 licensing.

## Try the preview

Python 3.12+ and the repository source are sufficient; no model credentials or server
are needed. Follow the [README quick start](../README.md#try-it-in-a-minute), then open
the generated HTML snapshot. The [walkthrough](demo.md) explains each scenario.

The package identifier is `daf-developer-preview`, with development version
`0.1.0.dev1`. Install from the repository. No package registry release is available.

## Validation

The [public launch matrix](public-launch.md) passed all four standard GitHub-hosted
Ubuntu/Windows × Python 3.12/3.13 jobs: 145 tests per job, lint/format, distribution
checks, builds, isolated wheel/source smoke demonstrations and dependency audits.
Those results apply to commit `a9181e7b84ecdff74e3e1afb4db52460ddf63f57`.
For later revisions, consult the checks attached to that exact commit or pull request.

## Developer Preview limitations

All execution and usage data is synthetic. This preview has no live model transport,
production owner authentication, approval service, product-repository editing,
GitHub publication adapter, notification delivery or deployment capability. Mission
Control is a snapshot, not a live controller or interactive approval interface.

Fixture budgets and stop tests do not prove real provider spending limits, remote
cancellation, OS isolation or rollback-resistant recovery. Do not attach real workers
and treat these demonstrations as live safety guarantees. macOS is not included in
the hosted matrix. See [capabilities](capabilities.md) and [security](../SECURITY.md).

## Feedback

Evaluation feedback and focused contributions are welcome through Issues and pull
requests. Report sensitive findings using the private route in [SECURITY.md](../SECURITY.md).
