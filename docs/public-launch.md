# Verified public source launch — 2026-10-28

The [DAF repository](https://github.com/samuelwhite/development-autonomy-framework)
is public. [PR #2](https://github.com/samuelwhite/development-autonomy-framework/pull/2)
integrated the independently cleared source with a normal merge commit. The original
standalone root and both preparation commits remain in history; no private repository
history was imported.

| Source identity | Value |
| --- | --- |
| Independently cleared head | `a8d9deba632460ca932a2ce4c0020e69e0ce5f15` |
| Public launch commit | `a9181e7b84ecdff74e3e1afb4db52460ddf63f57` |
| Approved and integrated tree | `99c8c1783904f0ab1d570559c29243f8cc057bea` |
| Approved candidate ZIP SHA-256 | `f01201fced82a0d0b1704832ba6eb7c6462a3071de14d3ead47259681303bb13` |

All 47 integrated files matched the approved candidate byte for byte, including an
anonymous source download after the visibility transition. The ZIP hash identifies
the reviewed candidate archive, not GitHub's differently wrapped source download.
Later presentation changes have their own commit and content manifest; they do not
replace this preserved baseline.

## Hosted CI evidence

[Run 40711106819, attempt 1](https://github.com/samuelwhite/development-autonomy-framework/actions/runs/40711106819)
completed successfully through `workflow_dispatch` on the exact launch commit above.
Actual checkout identity and standard-hosted runner identity were verified.

| Standard GitHub-hosted runner | Python | Tests | Result |
| --- | --- | --- | --- |
| Ubuntu | 3.12 | 145 passed | [PASS](https://github.com/samuelwhite/development-autonomy-framework/actions/runs/40711106819/job/122896334655) |
| Ubuntu | 3.13 | 145 passed | [PASS](https://github.com/samuelwhite/development-autonomy-framework/actions/runs/40711106819/job/122896335320) |
| Windows | 3.12 | 145 passed | [PASS](https://github.com/samuelwhite/development-autonomy-framework/actions/runs/40711106819/job/122896335483) |
| Windows | 3.13 | 145 passed | [PASS](https://github.com/samuelwhite/development-autonomy-framework/actions/runs/40711106819/job/122896335357) |

Every job passed dependency installation, Ruff lint/format, coverage tests,
distribution boundary checks, wheel/source builds, fresh-environment wheel
demonstration, source-package rebuild demonstration and a strict dependency audit.
Audits reported no known vulnerabilities at run time; this is not a security
certification or a guarantee against future advisories.

## Verified repository safeguards

- Protected `main`, including administrators: independent approval, stale-review
  dismissal, last-push approval and resolved conversations; no force pushes or deletion.
- All four strict/up-to-date matrix checks bound to the GitHub Actions app.
- Private vulnerability reporting enabled; private-staging exceptions expired.
- Zero repository self-hosted runners and Actions secrets; read-only workflow defaults
  with workflow-token PR approval disabled.
- Only the two approved, full-SHA-pinned checkout/setup-python action references allowed;
  credential persistence disabled and no publishing or deployment workflow steps.

See [Issue #1](https://github.com/samuelwhite/development-autonomy-framework/issues/1)
for staging closure. No formal GitHub Release, version tag or package registry release
is available. The product remains an offline Developer Preview with synthetic data
only; green offline CI does not establish support for live execution or deployment.
