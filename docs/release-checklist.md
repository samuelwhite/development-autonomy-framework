# Developer Preview release checklist

DAF v0.1 is an **offline Developer Preview**. The source is public and the initial
four-job hosted validation matrix passed. Package metadata is `0.1.0.dev1`; no
formal GitHub Release, version tag or package registry release is available.

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

## Checks for subsequent changes

- Verify the exact source revision, content manifest and any built distribution bytes.
- Check disclosure scope, ownership, notices and third-party provenance. Keep private
  engineering records outside the public source.
- Run lint, formatting, tests, distribution checks, wheel/source smoke demonstrations
  and dependency audits. Confirm all four required hosted jobs for the relevant revision.
- Check documentation links, source installation and the synthetic demonstration.
  Describe available capabilities and validation results accurately.
- Integrate through the protected PR process with an eligible independent reviewer.
  Preserve required checks, review rules, private reporting, runner isolation and the
  pinned-action allowlist. Do not add access or weaken protection to satisfy a check.

Passing these checks does not establish support for live autonomous execution.
The [capability boundaries](capabilities.md) apply regardless of repository or
distribution status. The workflow has no publishing or deployment steps.
