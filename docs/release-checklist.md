# Developer Preview release checklist

DAF v0.1 is an **offline Developer Preview**. The public source launch and initial
hosted validation are complete. Formal release and announcement remain pending
Product review and separate owner approval.

## Completed public source launch — 2026-10-28

- [x] Independently review the exact source, history and disclosure inventory.
- [x] Confirm Samuel James White's ownership and redistribution authority under
  Apache-2.0; preserve LICENSE, NOTICE and third-party provenance checks.
- [x] Integrate reviewed source without rewriting history and verify anonymous access
  to all 47 approved files.
- [x] Establish administrator-enforced branch protection, independent PR review,
  conversation resolution and four strict checks bound to GitHub Actions.
- [x] Enable and verify private vulnerability reporting; retire staging exceptions.
- [x] Verify no self-hosted runners or repository secrets, read-only workflow tokens,
  no persisted checkout credentials and the two approved SHA-pinned actions.
- [x] Run the standard-hosted Ubuntu/Windows × Python 3.12/3.13 matrix successfully.

The [launch record](public-launch.md) gives exact source, tree and job evidence.
These are dated results; check the current proposal's own CI before integrating it.

## Product review — proposed materials

- [ ] Review the README, synthetic screenshot, installation and demonstration flow.
- [ ] Review [repository description, topics and LinkedIn draft](portfolio.md).
- [ ] Approve the [v0.1 release-note draft](release-notes-v0.1.md), including offline
  limitations and unchanged `0.1.0.dev1` package version.
- [ ] Review the documentation diff, regenerated manifest and exact branch validation.
  Keep runtime, tests, dependencies, workflow permissions and licence notices unchanged
  in this presentation change.
- [ ] Integrate through the protected PR process with an eligible independent reviewer.
  Do not add access or weaken protection just to satisfy this step.

## Future publication — separate authority required

No Release, version tag, registry upload, deployment or external announcement is
authorised by this checklist or by passing CI. After Product review, the owner must
separately approve any such action and its exact content, version and source commit.
Do not execute these steps as part of presentation preparation.

Before later publication, recheck source and distribution bytes, disclosure inventory,
ownership/notices, dependency advisories, safeguards and CI results. Live autonomous
execution remains unsupported. Private engineering evidence stays outside the public
repository; only disclosure-safe summaries and synthetic assets belong here.
