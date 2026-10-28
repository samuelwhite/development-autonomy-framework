# Security and reporting

This is an offline research/developer preview, not an approved autonomous
production controller. No live model transport, credential lookup, approval
service, remote listener, notification delivery or deployment adapter is shipped.

The CLI creates only new synthetic state. Its static dashboard uses text nodes,
escaped embedded data, a restrictive content security policy and no external
assets or network requests. Existing directories and linked output paths are
refused. The package does not inspect your home directory or discover credentials.

Source code, local databases and Python processes do not isolate a malicious
same-user actor. An attacker able to change the application can defeat local
checks. Arbitrary backup restoration is not proven rollback-resistant. Do not
extend this preview with real workers until independent admission, provider caps,
identity/signing isolation and recovery have been reviewed together.

## Public CI boundary

The `preview-quality` workflow targets standard GitHub-hosted Windows and Linux
with Python 3.12 and 3.13. It supports controlled manual validation as well as
push/pull-request checks. It has
`contents: read`, pinned actions, no persisted checkout credentials, no secrets,
no privileged pull-request trigger, no publishing step and no private-service access.
Never register a self-hosted runner for this repository or grant it access through
an organization runner group. Repository/organization settings must enforce that
boundary: a workflow file alone cannot prevent a future configuration change.

Private vulnerability reporting is enabled. Use **Security → Advisories →
Report a vulnerability**, or [report privately through GitHub](https://github.com/samuelwhite/development-autonomy-framework/security/advisories/new),
for sensitive findings. If that option is absent, keep the report private; do not
use a public Issue or guess a contact address.

DAF is a solo-maintained public project. Pull requests remain mandatory, along with
all four up-to-date matrix checks bound to GitHub Actions and resolved conversations.
Independent GitHub reviewer approval is not mandatory under the owner's policy
adopted on 2026-10-28. Protection still applies to administrators; force pushes and
branch deletion remain prohibited. Stale-review dismissal remains enabled.

All other security protections remain unchanged, including private reporting,
runner isolation and the pinned-action allowlist. Staging exceptions have expired.
Do not bypass these controls to integrate changes. The [launch record](docs/public-launch.md)
preserves the original controls and documents the subsequent policy change; see
also the [release checklist](docs/release-checklist.md).

Do not put credentials, private transcripts, private source material or personal
infrastructure details in public Issues. The successful offline matrix is evidence
for its recorded commit, not a security certification or approval for live execution.

Security-sensitive changes need focused adversarial tests and explicit review.
Do not weaken immutable history, budget reservations or stop/recovery invariants
to make a test pass. Test fixtures do not confer execution authority.
