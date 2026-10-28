# Developer Preview release checklist

DAF v0.1 is an **offline Developer Preview**. The source is public and the initial
four-job hosted validation matrix passed. Package metadata is `0.1.0.dev1`.
Published release records belong on [GitHub Releases](https://github.com/samuelwhite/development-autonomy-framework/releases).
No package registry release is available; installation uses repository source.

## Completed public source launch — 2026-10-28

- [x] Independent review of the exact source, history and disclosure inventory.
- [x] Confirmed Samuel James White's ownership and redistribution authority under
  Apache-2.0; preserved LICENSE, NOTICE and third-party provenance checks.
- [x] Integrated reviewed source without rewriting history and verified anonymous
  access to all 47 approved files.
- [x] Established administrator-enforced branch protection, independent PR review,
  conversation resolution and four strict checks bound to GitHub Actions.
- [x] Enabled and verified private vulnerability reporting; retired staging exceptions.
- [x] Verified no self-hosted runners or repository secrets, read-only workflow tokens,
  no persisted checkout credentials and the two approved SHA-pinned actions.
- [x] Passed the standard-hosted Ubuntu/Windows × Python 3.12/3.13 matrix.

The [launch record](public-launch.md) gives the exact source, tree and job evidence.
These dated results apply to the recorded commit, not automatically to later revisions.

## Current solo-maintainer policy — 2026-10-28

After the source launch, the owner removed mandatory independent GitHub reviewer
approval. Pull requests remain mandatory. All four up-to-date GitHub Actions checks,
administrator enforcement, resolved conversations, stale-review dismissal and the
force-push/deletion restrictions remain in place. All other security controls are
unchanged. The [dated policy change](public-launch.md#subsequent-solo-maintainer-policy--2026-10-28)
records the distinction from the launch-time controls above.

## Checks for subsequent changes

- Verify the exact source revision, content manifest and any built distribution bytes.
- Check disclosure scope, ownership, notices and third-party provenance. Keep private
  engineering records outside the public source.
- Run lint, formatting, tests, distribution checks, wheel/source smoke demonstrations
  and dependency audits. Confirm all four required hosted jobs for the relevant revision.
- Check documentation links, source installation and the synthetic demonstration.
  Describe available capabilities and validation results accurately.
- Integrate through the protected PR process. Independent GitHub approval is not
  mandatory. Preserve all four required checks, administrator enforcement, conversation
  resolution, force-push/deletion restrictions, private reporting, runner isolation
  and the pinned-action allowlist. Do not add access or bypass protection to satisfy a check.

Passing these checks does not establish support for live autonomous execution.
The [capability boundaries](capabilities.md) apply regardless of repository or
distribution status. The workflow has no publishing or deployment steps.
