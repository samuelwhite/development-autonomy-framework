# M1 integration and planning repair validation

29 October 2026. Source integration only; no public release or live execution.

## PR #7: merged foundation

Original source head `7b24b7ce84eb7a44d2179adcbd77c17d3bda8b52` was integrated with
approved main `c8c9146da81c7bd2fee219e39326f64649c9441f` by normal merge commit
`12f6880ccae4d2df6108d438e8f76e1054930bf4`. After validation, PR #7 was merged into
main normally as **`ecd08912c4a809cc14faba4ca3de9ca4d2d04d92`**. Its tree matches
the validated integration head: `3a8a3d920bdf1c3d76c9c69965fa4e1b08af9681`.

- [Fresh exact-head four-job CI](https://github.com/samuelwhite/development-autonomy-framework/actions/runs/40925524490/attempts/2): Ubuntu/Windows, Python 3.12/3.13 passed. Hosted jobs passed 299 tests, lint/format, runtime distribution guard, wheel/sdist smoke tests and strict dependency audit.
- Attempt 1 had a Windows/Python 3.13 timeout in the unchanged Node simulation subprocess (30 seconds), with 298 other tests passing. The failed job was rerun once at the same source without weakening checks or changing timeouts. It passed all 299 tests and subsequent packaging/audit steps. Both attempts remain available.
- [Fresh exact-head desktop CI](https://github.com/samuelwhite/development-autonomy-framework/actions/runs/40925529217): Windows and Ubuntu passed the 58 simulation tests and six packaged checks. Desktop/prototype sources are identical to v0.2.1.
- Local Windows/Python 3.14.4: 298 passed, one symlink-permission skip. Focused handoff/receipt tests: 151 passed, one skip; 100% statement coverage of the two pure contract modules. Wheel/sdist, lint/format, distribution guard and strict dependency audit passed.

Final source/security review confirmed that external claims remain
`externally_supplied_unverified`, including consistently fabricated matching
claims. Local comparisons do not authenticate evidence. Bundles retain false
execution authority. No execution store, budget, stop gate, dependency pin,
workflow or desktop behavior was changed by #7.

GitHub automatically removed the merged head branch; it was immediately restored
at `12f6880ccae4d2df6108d438e8f76e1054930bf4`. No history was rewritten and no
repository policy was changed. PR #8 retains its original ancestry and reviews.

## PR #8: repaired draft

PR #8 was retargeted to main after #7 merged. Main was merged normally into the
existing branch; there was no rebase or force-push. The repair remains a draft
for separate Product review and is not authorized to merge in this milestone.

The repair covers:

- Case-folded component comparisons for code scope, protected directories and protected files; original source/path spelling is retained. Prefix neighbors remain valid, and ambiguous case aliases refuse.
- Complete-document validation of every task, instruction, check binding and milestone coverage before returning any proposal.
- Exact-schema stored-record validation on write/load/repeat, requiring null approval, false authority and consistent source/bundle identities. Unknown trusted/spending fields and forged status are refused; no supplied record becomes authenticated evidence.
- Pinned tree-entry checks for source directories and regular-file modes, with exact blob binding. Symlinks, submodules, malformed/truncated trees and unsafe or unpinned endpoints refuse. The runtime remains offline; only the explicit source-sidecar reader performs bounded public GETs.

Local full suite: **413 passed, two symlink-permission skips**. Focused planning
and reader suite: **115 passed, one skip**, including 90 added adversarial and
positive regressions. The planning module has 99% statement coverage in the full
local run. These checks run on both platforms in the hosted matrix; the actual
fixed-head revision and final hosted results are recorded in
[PR #8](https://github.com/samuelwhite/development-autonomy-framework/pull/8).

The repaired sidecar also performed real public GitHub reads of the existing
sample at exact commit `075ae7d67ebdecea20e3a0de4bfe5939ffae22f1`, including its
tree chain. Reimporting F2 returned `already_present` against the pre-repair
record, preserving ingestion ID
`a1f961f34c01cab548991bb431358e9f3ce66d543e0859aabc98de86bbd7afaa` and its original
bytes. The sample content remains synthetic; this demonstrates real transport
and deterministic ingestion, not real task execution.

## Remaining boundaries and M1.2 readiness

M1.2 can use the repaired validators as the foundation for read-only desktop
planning after Product accepts and separately authorizes merging #8. It must
retain/revalidate complete source snapshots, use strict typed process operations,
and keep source observations, proposals, approval and execution separate. A
stored per-milestone projection cannot re-prove the full plan's scope/dependency
closure by itself. Same-user tampering, authenticated approvals, independently
verified CI evidence, worker isolation and spending enforcement are not provided.

No bridge, arbitrary command interface, provider, worker, repository mutation or
spending authority was added. The existing execution/security/cost controls,
v0.1 release and private infrastructure are unchanged. Public distribution still
requires code signing, clean Windows acceptance and screen-reader qualification.
