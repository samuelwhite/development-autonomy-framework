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

After the public repository's security controls are verified, use **Security →
Advisories → Report a vulnerability** for sensitive findings. Private vulnerability
reporting must be enabled and verified as part of the approved visibility transition,
before Actions is enabled or the project is announced. If the private reporting
option is absent, keep the report private; do not use a public Issue as a substitute.

During private staging, owner-only private Issues are the approved internal tracking
channel. The temporary private-staging exceptions for branch protection and GitHub
private vulnerability reporting expire at public visibility. Disable Actions before
the transition; configure and verify both controls before enabling the approved
workflow. See the [publication checklist](docs/release-checklist.md).
Do not put credentials, private transcripts, private source material or personal infrastructure
details in a public issue. Until a private channel is configured, keep sensitive
reports private rather than guessing an address. Public source availability does
not itself establish a formal release or a completed hosted validation matrix.

Security-sensitive changes need focused adversarial tests and explicit review.
Do not weaken immutable history, budget reservations or stop/recovery invariants
to make a test pass. Test fixtures do not confer execution authority.
