# Second standalone Windows isolation investigation

**Failed feasibility gate. Maintainer reproducer only. Do not merge or ship.**
The composed token denies the ambient write in native checks, but the actual
bundled CPython cannot initialize. No production sandbox or execution authority
is provided. See [findings and design options](../../docs/m2.1-restricting-sid-review.md).

This is a separate investigation from immutable
[PR #11 at 42a1ca7](https://github.com/samuelwhite/development-autonomy-framework/tree/42a1ca7118d4f56361328e1b8acb4fb843683a70/desktop/isolation).
The native harness and Python probes derive from that maintainer reproducer.

## Maintainer prerequisites and reproduction

Windows 11 x64, an ordinary non-elevated host user, MSVC 14.50.35717 and Windows
SDK 10.0.26100.0 at the paths in `build.ps1`. The actual M1.2 embedded CPython
3.14.10 must already be at
`dist/m1.2-desktop/DAF-win32-x64/resources/planning/runtime`.
The build checks its `python.exe` hash and copies it; it does not modify the
application runtime. These are investigation build prerequisites, not new
requirements for DAF users. No administrator token, driver or service is used.

From the public repository root in PowerShell:

```powershell
./desktop/isolation-v2/build.ps1 -OutputDirectory dist/restrict-write
$bundledPython = './dist/m1.2-desktop/DAF-win32-x64/resources/planning/runtime/python.exe'
& $bundledPython -I -S -B desktop/isolation-v2/run.py dist/restrict-write write-restricted

./desktop/isolation-v2/build.ps1 -OutputDirectory dist/restrict-full
& $bundledPython -I -S -B desktop/isolation-v2/run.py dist/restrict-full full-restricted
```

Use fresh output folders for each run. The expected diagnostic result on the
recorded machine is exit **2**, `qualified: false`. Do not interpret absent
Python output as denied access or a passing test. The first case stops the suite
if Python cannot start, fails, or does not finish its probe. The ambient write
also stops immediately in the native helper, Python probe and runner.

`build-manifest.json` records source, helper, object and every copied runtime-file
hash plus toolchain/OS identities. `gate-result.json`, `sealed-native.jsonl` and
`sealed.jsonl` record results. All output stays under ignored `dist/`; publish
only reviewed evidence, never the binaries or personal paths.

For fixed DLL-load diagnostics, create another fresh build and launch its
`feasibility.exe write-restricted debug`, redirecting stdout/stderr to files.
Use `Start-Process -WindowStyle Hidden` and wait for it. This launches only the
adjacent Python and fixed probe, with the same LPAC, restriction and job. The
debug mode is diagnostic and is not evidence of normal lifecycle behaviour.

## Boundary being tested

`CreateRestrictedToken(DISABLE_MAX_PRIVILEGE | WRITE_RESTRICTED)` adds one fresh
unmapped resource SID derived from a GUID. The alternative omits WRITE_RESTRICTED
and restricts reads too. There are no broad compatibility SIDs in the restricting
list and no SANDBOX_INERT flag. `CreateProcessAsUserW` composes this token with
the original LPAC opt-out, registryRead only, explicit stdio handles, prohibited
child creation and a Job Object assigned at creation. No alternative launch is
attempted if it fails.

The helper inspects the **final suspended child**, asserting its exact package
and restricting SIDs, low integrity, no elevation, only change-notify privilege,
exact capability, child-process mitigation and job limits. It duplicates that
token for independent AccessCheck calls and for impersonated CreateFile/WriteFile
operations. A dual-SID fixture must accept a write; the low-integrity ambient
fixture with only ALL_RESTRICTED_APPLICATION_PACKAGES must reject it with error 5.
The latter remains byte-identical to the original PR #11 negative fixture.
Native impersonation is **not** a substitute for running the Python tests.

Only freshly generated runtime copies, synthetic fixtures, a generated desktop,
the new token/process/thread objects and this attempt's new AppContainer profile
and registry storage receive ACLs. Existing window station/default desktop,
Windows files, registry parent and original application runtime ACLs are untouched.
Fixture links, junctions and hardlinks are refused. The generated token default
DACL and new process/thread DACL grant both principals for bootstrap diagnostics;
this is not a claim that all Windows bootstrap dependencies have been found.

The original sealed profile/TEMP/registry and owner-rights handling remains.
Jobs retain one active process, 128 MiB per-process memory, two seconds user CPU,
kill-on-close, no breakaway and a ten-second helper wall deadline. Original probe
cases for networking, credentials, process creation, resource limits and death
of either supervisor remain in source. They have **not passed under this new
composition** because bundled Python fails before the probe begins.

The helper restores and removes its own profile and synthetic credential/key.
Crash-test cleanup accepts only the exact generated profile marker. Unexpected
cleanup failures require inspection of that owned identity; do not repair them
by changing machine-wide permissions. This harness is not hardened production
recovery code and must not be wired into Electron.
