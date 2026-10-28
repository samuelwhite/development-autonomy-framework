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

The proposed workflow runs on GitHub-hosted Windows and Linux only. It has
`contents: read`, pinned actions, no persisted checkout credentials, no secrets,
no privileged pull-request trigger, no publishing step and no private-service access.
Never register a self-hosted runner for this repository or grant it access through
an organization runner group. Repository/organization settings must enforce that
boundary: a workflow file alone cannot prevent a future configuration change.

GitHub private vulnerability reporting is available for public repositories.
Before publication, confirm a private maintainer reporting channel; enable GitHub's
private reporting when publication is explicitly approved and verify it before
announcing the release. Private staging must use a confirmed private maintainer
channel. Do not assume a private repository has a public reporting form. These
are release blockers until configured by the owner.
Do not put credentials, private transcripts, source code or personal infrastructure
details in a public issue. Until a private channel is configured, keep sensitive
reports private rather than guessing an address.

Security-sensitive changes need focused adversarial tests and explicit review.
Do not weaken immutable history, budget reservations or stop/recovery invariants
to make a test pass. Test fixtures do not confer execution authority.
