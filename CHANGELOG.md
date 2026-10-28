# Changelog

## 0.1.0.dev1 — public Developer Preview source (2026-10-28)

- Standalone offline progression engine and durable synthetic execution journals.
- Separate bounded reservation, dispatch and checkpoint experiments.
- Static synthetic Mission Control walkthrough and read-only evidence display.
- Portable packaging, adversarial tests and standard GitHub-hosted CI configuration.
- Controlled manual validation on standard GitHub-hosted runners.
- Public source launch with all four hosted Windows/Linux × Python 3.12/3.13 jobs
  passing, 145 tests per job; see [exact evidence](docs/public-launch.md).

## Documentation

- README introduction, synthetic JPEG screenshot, quick start and CI badge.
- Publication wording updated to reflect the completed public source launch.
- Source notes and background on the challenges of building Victoria that led to DAF.
- Current security guidance reflects the solo-maintainer policy adopted after the
  source launch; the dated launch controls and evidence remain preserved.

No live autonomous execution, production identity, deployment or notification delivery
is enabled. Package metadata is `0.1.0.dev1`; [GitHub Releases](https://github.com/samuelwhite/development-autonomy-framework/releases)
lists published release records. No package registry release is available. Passing
offline CI does not establish production readiness or security certification.
