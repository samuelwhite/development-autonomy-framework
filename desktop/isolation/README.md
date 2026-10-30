# M2.1 standalone isolation experiment — blocked

This is a maintainer-only diagnostic harness, **not a production sandbox or a
desktop execution capability**. It is excluded from the application's explicit
packaging allowlist. Do not reuse it as a launch broker. The gate failed; no
unsandboxed fallback or wider execution implementation is present.

The native helper launches only the adjacent bundled Python and fixed probe.
Its fixed modes are `baseline`, `sealed`, `memory`, `cpu`, `hold` and `debug`.
It creates a unique temporary AppContainer, fake credential, fake HKCU key and
synthetic files. It modifies only those test resources and copied runtime ACLs.
The probe attempts network access to loopback and TEST-NET, plus DNS resolution
of `example.com`. It does not enumerate real credentials or private projects.
The intentionally writable ambient fixture is the adversarial counterexample.

## Reproduce on a Windows development machine

The build script currently records this machine's Visual Studio Build Tools 18,
MSVC 14.50.35717 and Windows SDK 10.0.26100.0 paths. These are **maintainer build
prerequisites**, not requirements for ordinary DAF users. Use the existing M1.2
package's CPython 3.14.10 runtime at the path below. Run as the ordinary interactive
user, not an elevated administrator. Do not use real secrets or repository work.

From the public DAF checkout:

```powershell
./desktop/isolation/build.ps1 -OutputDirectory 'dist/m21-isolation-review'
& './dist/m1.2-desktop/DAF-win32-x64/resources/planning/runtime/python.exe' `
  -I -S -B desktop/isolation/run.py dist/m21-isolation-review
```

Use a fresh output directory each time. Normal completion produces
`gate-result.json`, `lifecycle-results.json` and per-case JSONL traces. **Exit 2
means the diagnostic completed but isolation is not qualified.** Exit 0 from an
individual helper means only that its probe ran, never that confinement passed.
The runner always leaves qualification false; removing the demonstrated blocker
would still require a complete independent qualification, not an automatic pass.

The parent/helper-death cases deliberately terminate their own test processes.
The runner retains process handles before termination to avoid PID reuse and
removes only profiles named in the freshly generated ownership marker. Cleanup
errors must be investigated, not ignored. The harness is a controlled experiment:
it does not implement production crash-safe ownership records, admission or
recovery. It has not been qualified against malicious same-user marker changes,
binary replacement or profile setup races. Do not ship it.

## Result

In sealed mode, writes to the worker's own profile, TEMP and registry were denied.
Nevertheless, the worker appended to `ambient-shared.txt`: a synthetic
low-integrity file exposed to `ALL_RESTRICTED_APPLICATION_PACKAGES`, with no
per-attempt AppContainer SID grant. This models permissions outside DAF's control,
which another application or administrator could establish before DAF starts.
It does **not** assert that a particular sensitive file on a stock machine is
writable, or that LPAC violates its documented access model.

The approved boundary requires a child that cannot write outside admitted stdio
and broker-owned publication. LPAC plus own-profile ACLs and a Job Object did not
establish that boundary. Product's stop condition applies.

See [review and evidence](../../docs/m2.1-isolation-review.md). The existing
M1.2 desktop bundle, simulation, source repository and v0.1 runtime are unchanged.
