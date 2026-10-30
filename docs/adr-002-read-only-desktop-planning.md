# ADR 002: a bundled, short-lived planning process

30 October 2026. M1.2 draft implementation; Product review required.

## Decision

Keep the approved Electron UI and add a separate read-only planning page. Bundle
CPython 3.14.10 and invoke a fixed entry point for one operation over stdin/stdout.
No server, daemon, credentials, provider SDK or arbitrary command/file interface.
Reuse M1.1's complete-document validator and deterministic proposal identities;
factor its source reader into a reusable complete-file operation.

Windows uses the official [embeddable distribution](https://docs.python.org/3.14/using/windows.html#the-embeddable-package).
Linux uses [Astral's standalone build](https://github.com/astral-sh/python-build-standalone/releases/tag/20261026).
Exact archives and SHA-256 checksums are pinned in `desktop/python-runtime.json`.
This adds runtime bytes but avoids a freezer, system Python, first-run installation
and interpreter discovery. Linux remains experimental. Updating a runtime requires
a reviewed rebuild; there is no updater or download capability in the application.

## Native and protocol boundary

The renderer is sandboxed and context-isolated, without Node integration. The
custom protocol serves an exact asset allowlist. CSP blocks connections, frames,
objects and workers; Chromium networking, remote navigation, permissions,
downloads and new windows remain denied. Source strings are text nodes, never
HTML, Markdown, executable links or code.

The preload exposes four methods only on `daf://app/planning.html`:

| Method | Input | Capability |
| --- | --- | --- |
| `importPublicPlan` | repository, exact commit, relative JSON path | One native-confirmed public read |
| `listImports` | none | Bounded local history, revalidated |
| `getImport` | 64-hex snapshot ID | Complete-source local revalidation |
| `cancelImport` | none | Terminate the owned child and await exit |

Each handler verifies the owning BrowserWindow, exact main frame and planning
URL. Main owns request IDs, process arguments, environment, working directory and
storage root. The native dialog identifies the exact source and defaults to Cancel.
Even a compromised renderer cannot silently bypass it. Closing, reload or Cancel
invalidates pending consent; a late positive answer cannot start a read.

`planning-protocol.json` defines the version-1 JSON Schema contract;
`planning.d.ts` describes its compile-time types. Main and Python independently
validate its small schema subset. Unknown fields, types and operations refuse.
The child reads one JSON line (4 KiB maximum), emits one terminal line (1 MiB)
and exits. Main rejects malformed UTF-8, duplicate keys, nonfinite numbers, extra
messages, mismatched operation/ID/source and invalid dependency order. Stderr is
bounded at 8 KiB and never rendered. Python validates the view before persistence.

Main launches only the bundled executable and fixed entry point with
`-I -S -B -u`, `shell:false`, hidden Windows console, no detached child and a
minimal environment. No user PATH, Python config, proxy variables, provider tokens
or user packages are passed. Windows `._pth` excludes `import site`. The single
instance app permits one active planning process. This is a capability restriction,
not an OS sandbox against compromised native code or same-user app modification.

## Public source and validation

Only explicit import permits certificate-verified HTTPS GET to `api.github.com`.
No auth discovery, caller headers, redirects, retries, branch/tag resolution,
linked downloads, Git clone, CI dispatch, repository writes or provider requests.
The child has a 30-second hard deadline and main kills at 35 seconds; each HTTP
operation has at most eight seconds and its remaining overall budget.

M1.1 checks the exact commit, bounded tree chain, regular-file mode, blob SHA and
source bytes. Limits: 16 path components, 18 GETs, 192 KiB per response, 64 KiB
source, 100 tasks/milestones. Every task, dependency, instruction/check binding,
acceptance field and portable protected path is checked before save/display.
Truncated trees and unsupported sizes refuse rather than broadening access.

GitHub remains the planning authority. The source commit pins the imported file;
the plan's declared baseline is separate metadata. Workflow/protected-file hashes,
budgets and checks are source requirements, not verified evidence or credit.
Import, review and successful validation never grant approval, execution or spend.

## Persistence and cancellation

Main chooses the local profile's `planning-v1` directory. The renderer supplies
IDs, never filesystem paths. UNC/device roots, symlink/junction ancestors and
nonregular records refuse. Snapshot identity hashes repository + commit + path;
existing M1.1 per-milestone proposal IDs remain unchanged.

Each immutable record contains exact full source bytes (base64), source references,
Git blob/content/plan hashes and every proposal bundle. Loading reconstructs the
entire plan, revalidates all tasks, recomputes identities and compares the strict
envelope. Approval must be null, execution/spending authority false, and verification
an unverified local observation. Supplied trust fields refuse. Self-consistent
same-user tampering is not authenticated by matching hashes.

A bounded staging file is flushed/fsynced, then published by a no-overwrite hard
link. Identical repeats reuse bytes; conflicts preserve the original. Unsupported
filesystems fail closed. Interrupted staging files never appear as complete
imports. If publication raced Cancel, the UI asks the user to check local history;
it does not claim rollback. Power-loss durability is not guaranteed on every
filesystem. Damaged records refuse when reloaded.

History is capped at 100 snapshots / 32 MiB. Unexpected/staging files count toward
storage caps. Corrupt records are reported individually while intact imports stay
available; the app never silently deletes evidence. No execution journal, budget
ledger, stop state or receipt trust status is touched. There is no local roadmap
editor or GitHub write-back.

Cancel, navigation and quit kill only the owned process and await its exit. A
child watchdog exits on parent-pipe closure even while I/O blocks. The child
cannot spawn workers. Tests exercise actual parent death and cancellation. Late
success is ignored and no automatic retry follows.

## Limits

Public schema-1 planning JSON only; no Markdown interpretation, private sources,
owner authentication, independent CI verification or execution. Signing, clean
Windows acceptance and screen-reader qualification remain distribution gates.
Future execution requires a separate design/security review and authority model.
