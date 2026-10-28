# Repository soft launch and release checklist

DAF v0.1 is an **offline Developer Preview**. Public repository visibility, hosted
validation and a formal release announcement are separate decisions. This checklist
defines the gates; it does not claim they have already passed. Record exact commits,
artifact hashes and results in the review record, not inferred from repository visibility.

Ownership is confirmed: **Copyright 2026 Samuel James White**, personally owned,
with authority to license and redistribute the reviewed source under **Apache-2.0**.
The third-party inventory covers separately installed development tools; no external
runtime dependency, tool environment or private execution history is distributed.

## Before changing visibility

- Review all tracked files, every Git-history commit, Issues and their edits/comments,
  pull requests, releases/tags, repository metadata and any other public-facing content.
- Verify redistribution rights, notices and the intentional copyright attribution.
  Confirm no credentials, private infrastructure, operational records or imported
  private repository history are present. Review exact distribution bytes again
  after any source change.
- Complete all available local tests, package smoke tests and dependency/security
  checks; record hosted tests accurately as pending if they have not run.
- Obtain independent clearance of the exact final commit and disclosure inventory.
  The owner's conditional soft-launch authority takes effect only after that clearance.
  If a disclosure check fails, stop while the repository is still private.

## Approved visibility transition and hosted validation

1. Verify the exact cleared commit and keep Actions disabled throughout the transition.
2. Change visibility only for this standalone repository under the owner's authorisation.
3. Configure public branch protection and private vulnerability reporting. Verify
   both, owner/admin access, absence of self-hosted runners and private secrets,
   read-only workflow permissions and the approved pinned-action restrictions.
   Private-staging exceptions do not carry over. If any control fails, keep Actions
   disabled and stop; do not announce the project.
4. Enable only the approved `preview-quality` workflow on standard GitHub-hosted
   runners. No paid services, larger runners, artifact publication or deployment.
5. Manually dispatch the reviewed ref after the workflow is on the default branch.
   Verify the actual checkout commit and all four matrix jobs: Ubuntu and Windows,
   each on Python 3.12 and 3.13. Require tests, wheel/source builds, installed-wheel
   demonstration, source-archive rebuild demonstration and dependency audit to pass.
   Update any branch-protection check names to the verified job identities.
6. Record findings and outstanding limitations. A public repository can still have
   pending or failed validation; never describe that as green CI or production support.

## Formal v0.1 announcement — separate decision

Green hosted CI and public visibility do not authorise a version tag, formal GitHub
Release, package registry upload, external announcement, deployment or live workers.
The owner must separately approve the formal v0.1 announcement. Live autonomous
execution remains unsupported by this preview regardless of publication status.

Private engineering evidence may contain operational details. Keep it outside the
public repository; publish only the approved disclosure-safe review and CI summaries.
