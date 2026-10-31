# Desktop packaging dependency remediation

Product-review candidate, 31 October 2026. This is a separate dependency repair
based on merged main `f4e69032f31d6db27896ac231d0d9a5471c67307`.
Accepted M2.1A head `f4fc866e56eaec683f0145117ebbd93a8f91fd4d` and its
native source, contracts, evidence and qualification records are unchanged.
This candidate does not authorize merging, release, execution or M2.1B.

## Diagnosis before changing dependencies

A clean `npm ci --no-fund` using the original declarations and lockfile succeeded.
`npm ls --all --json` exited zero. `npm audit --audit-level=moderate --json`
exited one with five moderate package findings caused by two advisories.
The full graphs, package identities, audit responses and verification records are
in [structured evidence](evidence/desktop-dependency-remediation.json).

Baseline identities (SHA-256 of Git LF bytes, separate from Windows CRLF checkout):

| File | Git blob | SHA-256 |
| --- | --- | --- |
| desktop/package.json | `800b96dee64fa9c82064bafefd86b24e0361035d` | `48f8e51dece9305bc281acca45fd429a9f144180fd37509ae800006640bdb95c` |
| desktop/package-lock.json | `e710959f6953157252a1e18c474c6dfd0c842e24` | `7d27e8f0cb4fd9c34a42d9a3128f5faf5d691075b858a54dc1447b7976ff10a7` |

The baseline lock contains 53 packages, all marked development-only. All three
direct dependencies are devDependencies. The advisory paths are:

```text
@electron/packager 20.3.0
  +-- @electron/asar 4.3.1
  |     +-- glob 13.0.6
  |     |     +-- minimatch 10.2.6 (deduplicated)
  |     |     +-- path-scurry 2.0.2
  |     +-- minimatch 10.2.6
  +-- @electron/universal 3.0.6
        +-- @electron/asar 4.3.1 (deduplicated)
```

The three Electron packages receive transitive audit findings; there are not
five separate root vulnerabilities.

- [GHSA-3g3m-2fjr-6pw4](https://github.com/advisories/GHSA-3g3m-2fjr-6pw4):
  affected glob 9.0.0 through 14.0.1, patched at 14.0.2. An aborted directory walk
  can continue reading directories after cancellation. DAF's build calls
  Packager, ASAR and the async `glob()` crawler, so the library is reached during
  packaging. The fixed build supplies no AbortSignal and makes no claim that a
  glob signal bounds packaging work. The specific cancellation trigger is not
  enabled by the current build.
- [GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249):
  affected minimatch before 11.0.1, patched at 11.0.1. Crafted patterns can amplify
  preprocessing at optimization level 2. Glob selects that optimization level.
  ASAR also directly uses minimatch for optional unpack patterns. DAF stages only
  named assets, uses ASAR's fixed `/**/*` suffix, and supplies neither unpack
  patterns nor user-controlled glob options. No route from imported plans to
  packaging patterns was found. Crafted patterns could matter to other consumers
  of this development toolchain; development-only status does not waive the audit.

The installed libraries are reachable at build time, but these findings are not
evidence of a new desktop runtime execution route. The staged runtime manifest
has no dependency declarations. Packaging dependencies are not copied into the
application. Existing packaged-content tests enforce the named asset boundary.

## Options and selected repair

Official npm registry metadata was queried on 31 October 2026:

| Package | Latest published release | Relevant constraint |
| --- | --- | --- |
| @electron/packager | 20.3.0 | ASAR ^4.0.1, universal ^3.0.1 |
| @electron/asar | 4.3.1 | glob ^13.0.2, minimatch ^10.0.1 |
| @electron/universal | 3.0.6 | ASAR ^4.0.0 |
| glob | 14.0.3 | minimatch ^11.0.2, path-scurry ^3.0.0 |
| minimatch | 11.0.3 | nonrecursive-glob-match ^1.0.3 |

No supported Packager/ASAR release currently permits the patched majors.
Refreshing versions inside ASAR's declared ranges cannot repair both advisories.
Waiting for an upstream ASAR release is defensible but leaves desktop validation
blocked. npm's suggested Packager 18.4.4 downgrade was rejected: Product forbids
downgrading merely to silence the audit, and it would change a broader dependency
surface. Audit suppression, threshold changes, forks and force-fix were rejected.

The candidate uses only the official published packages, with this exact scope:

```json
"overrides": {
  "@electron/asar@4.3.1": {
    "glob": "14.0.3",
    "minimatch": "11.0.3"
  }
}
```

The exact ASAR selector limits the exception to the reviewed parent version.
Both Packager's direct and universal's deduplicated ASAR paths resolve to the same
patched tree. This is a reviewed consumer override, not an upstream declaration
that these majors are universally compatible.

Only four lockfile package records change:

| Package | Before | After | Why |
| --- | --- | --- | --- |
| glob | 13.0.6 | 14.0.3 | Patched cancellation; paired with minimatch 11 |
| minimatch | 10.2.6 | 11.0.3 | Patched expansion and current upstream fixes |
| path-scurry | 2.0.2 | 3.0.0 | Required by glob 14 |
| @isaacs/nonrecursive-glob-match | absent | 1.0.3 | Required by minimatch 11 |

The other 50 package records are unchanged, including Electron 45.1.0,
Packager 20.3.0, ASAR 4.3.1, universal 3.0.6 and Playwright 1.64.1.
All 54 resulting packages remain development-only. Before/after graphs and every
resolved URL/integrity value are retained in the structured evidence and lockfile.

## Compatibility and package integrity

This crosses two overridden majors and one required transitive major. Version
numbers and an audit pass alone were not accepted as compatibility proof.

- The published type/source comparison shows that minimatch 11 removes `makeRe`,
  `AST`, debug and some internal matching methods/options. ASAR uses the retained
  named `minimatch(path, pattern, options)` API, with `matchBase` where needed;
  it uses none of the removed APIs. ASAR's crawler uses the retained named async
  `glob(pattern, options)` API with `windowsPathsNoEscape`, dot-file enumeration,
  sorting and file-type inspection.
- Glob 14 uses the corresponding new matcher interface and requires path-scurry
  3 itself. These dependencies are upgraded together. Node engine requirements
  remain compatible with the existing >=22.12 runner check.
- Glob 14 ships a bundled default entry point. Its source map contains the
  patched minimatch expansion guard. Tests exercise the actual exported bundle,
  not just unbundled source, including cancellation and its expansion limit.
- SHA-512 of each of the four changed official npm tarballs matches the lockfile
  and registry metadata. Every regular installed file from those tarballs was
  independently compared byte-for-byte: 149 files total. None of the four has
  preinstall/install/postinstall scripts.
- `npm audit signatures` verified all 54 installed registry signatures and 13
  available attestations. This is package-origin/integrity evidence, not a claim
  of universal code safety.

Five focused packaging tests were added to the existing npm test command:
exact ASAR inventory/content (hidden, Unicode, spaces and literal special names);
unpack and unpackDir matching; rejection of an escaping directory link;
cancellation stopping recursive reads; and bounded direct/bundled pattern
expansion. They run in the unchanged hosted desktop workflow on both OSes.

The unchanged baseline passed the three ASAR compatibility/security checks and
failed both advisory regression probes. Its cancelled walk made four reads,
versus one for the candidate. Its minimatch preprocessing produced 256 parts
despite a requested cap of 16; the candidate produced 16. Both graphs generated
the same synthetic Windows ASAR bytes, SHA-256
`d3ba6cc120186f2cebe8c5cbbe5610b69b9dbef4fa2ac4eb00828214574bbb7c`.

An initial test-authoring run used POSIX-separated extraction names on Windows
and failed two round-trip assertions. The probe was corrected to use the native
path format expected by ASAR, then run against both graphs. That diagnostic
mistake is not a dependency failure or a passing baseline advisory test.

## Reproduction and validation boundary

The lockfile was generated in an isolated copy of the exact baseline lock using
npm 11.12.1, then reproduced unchanged with
`npm install --package-lock-only --ignore-scripts --no-fund`. Clean installation
and all real tests run with normal scripts enabled; `--ignore-scripts` is only
used for lockfile generation.

The clean local Windows validation uses a separate source snapshot and separate
output/extraction directories under ignored `dist/desktop-dependency-remediation`.
It does not overwrite either existing M1.2 archive or its extracted application.

Local results: clean npm ci and moderate audit passed (zero vulnerabilities);
all 9 existing boundary tests and 5 new packaging checks passed; all 58 simulation
tests passed; distribution checks, production build, Windows archive/extraction
and all 14 packaged journeys passed with zero skips. The isolated candidate ZIP
SHA-256 is `739626e75782d2ff832febdf1a85dd6619aa28ebd6f51d6e645c96039f2490f2`.
It remains local and is not a release or replacement for the existing candidate.

Candidate Git-LF SHA-256 identities:
- package.json: `0be96b20e112e53ab3f95e3dc7fbb124ec5e16fd9cd7069333a66cc03f1cde2e`
- package-lock.json: `634f4a42be84fa2c468efbf6c05d7934cd20ff710f774c71203a27aede46d510`

Hosted completion is recorded in the draft PR's checks and final validation
handover against the exact candidate commit. Required results are all four
Windows/Linux Python 3.12/3.13 jobs and both Windows/Linux desktop jobs, including
clean npm ci, unchanged moderate audit threshold, all 9 existing boundary tests,
these 5 packaging tests, all 58 simulation tests, production builds and all 14
packaged journeys per OS. Local tests do not substitute for those results.
The existing workflows, distribution checks and no-upload behavior are unchanged.

## Preserved boundaries and residual risks

Only dependency declarations/lockfile, maintainer packaging tests and this review
record change. The native foundation, its accepted evidence and contracts, all
security policies, desktop runtime/IPC/planning code and build scripts are
unchanged. The foundation remains disconnected from Electron. Fresh LPAC and
restricting SID isolation, ambient-write denial, explicit positive controls,
sealed identities/objects, low integrity/token limits, Job Object restrictions,
cancellation/parent-death cleanup, independent wall supervision, bounded
contracts, identity verification, producer/verifier separation and fail-closed
evidence remain exactly as accepted.

The ambient-read and periodic CPU-enforcement exceptions still apply only to the
fixed native operation. No admission, grants, worker launching, production
journal, Stop/recovery, AI/script execution or patch application is introduced.
An import, package fix, passing test or digest grants no execution authority.

Residual risk: the override exceeds ASAR's declared semver ranges and is qualified
for DAF's current Windows/Linux x64 packaging paths, not every third-party ASAR
consumer, macOS/universal packaging or arbitrary patterns. Reassess and remove
the override when ASAR publishes a compatible supported dependency update.
Keep the full audit and these regression tests enabled. No hard global resource
bound for arbitrary glob patterns is claimed.

Main, PR #14, PRs #11–#13, existing desktop candidates and v0.1 are preserved.
No merge, release, tag or binary upload is authorized. Stop for Product review.
M2.1B remains separately gated and unauthorized.
