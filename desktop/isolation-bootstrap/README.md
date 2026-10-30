# Final bounded M2.1 bootstrap investigation

**Maintainer diagnostics only. M2.1 implementation remains blocked. Do not ship.**
See the [decision review](../../docs/m2.1-bootstrap-review.md) and
[compact measured evidence](../../docs/evidence/m2.1-bootstrap-windows.json).

This copies the security configuration from PR #12 at
`ea5f338877ef219ecd808f0d4fb23b2b87099762`. Neither PR #11 nor PR #12 is changed.
The new branch starts from main `5b6f5d4328854df66d7bc25ab7aa0504256e6e12`.

## Reproduce

Maintainer prerequisites: Windows 11 x64, ordinary non-elevated account, MSVC
toolset directory 14.50.35717 and SDK 10.0.26100.0 at the paths in `build.ps1`,
and the unchanged M1.2 candidate's embedded CPython 3.14.10. No administrator
token, driver, permanent service, IFEO change or system ACL change is used.

From the public repository root in PowerShell:

```powershell
./desktop/isolation-bootstrap/build.ps1 -OutputDirectory dist/bootstrap-review
$bundledPython = './dist/m1.2-desktop/DAF-win32-x64/resources/planning/runtime/python.exe'
& $bundledPython -I -S -B desktop/isolation-bootstrap/run.py dist/bootstrap-review
$LASTEXITCODE
```

Use a fresh output folder. The runner deliberately returns **2**, even when all
fixed diagnostics finish: `production_qualified` and `execution_authority` stay
false. It runs eleven fixed cases, creating separate runtime/fixture copies:
normal/traced CPython, minimal native startup, independent CNG dependency probe,
the native adversarial suite, full read-restriction startup, memory, CPU, wall
deadline, helper death and parent death. It never retries an ambient write with
weaker settings. Incomplete native startup or suite output stops progression.

The two supplemental measurements in the evidence are reproducible with the
same compiled launcher on fresh copies: repeat `write-restricted cpu native-static`
and trace `full-restricted debug python`. `run.ordinary` can create those copies;
the launcher accepts only the fixed policy/mode/target enumerations. For example,
after the matrix above, from the same repository root:

```powershell
@'
import json, pathlib, runpy
diagnostic = runpy.run_path('desktop/isolation-bootstrap/run.py')
root = pathlib.Path('dist/bootstrap-review').resolve()
for name, target, mode, policy in [
    ('cpu-repeat', 'native-static', 'cpu', 'write-restricted'),
    ('full-python-traced', 'python', 'debug', 'full-restricted'),
]:
    result = diagnostic['ordinary'](root, name, target, mode, policy)
    with (root / (name + '.json')).open('x') as output:
        json.dump(result, output, indent=2)
'@ | & $bundledPython -I -S -B -
```

These are maintainer diagnostics; no general command interface is exposed to DAF.

`build-manifest.json` hashes every copied runtime/source/binary and the relevant
Windows DLLs. `results.json` retains full observations. Each attempt retains
`child.jsonl`, `native.log` and its exact owned profile marker. The trace can
contain local paths and Windows account SIDs; publish the compact reviewed
evidence, not raw logs, PDBs or binaries. Source snapshots are retained for every
build, including preliminary diagnostics. The compiled source hashes can be
compared with `git show <revision>:desktop/isolation-bootstrap/<file>`.

Run the portable evidence-handling tests separately:

```powershell
python -m unittest discover -s desktop/isolation-bootstrap -p test_evidence.py -v
```

This command is for maintainers with a development Python. It does not change
the ordinary DAF application's installation requirements. These six tests check
tampered bytes, a reported write followed by byte restoration, a child failure
signal, missing/duplicate completion and malformed JSON. They do not qualify a
worker or authenticate a supplied receipt.

## Diagnostics and unchanged boundary

`launcher.cpp` retains PR #12's restricting-token creation, read-only profile
and registry ACLs, LPAC opt-out, registryRead-only capability, explicit stdio
handles, prohibited child creation, job-at-creation, no breakaway, 128 MiB memory,
two-second configured user-CPU limit and ten-second supervisor wall deadline.
The evidence contains exact equality checks for these source sections. Two
additional generated executable fixtures receive only read/execute grants for
both per-attempt principals. No ambient permission or broad restricting SID is
added. All final tokens are inspected before resume.

The 4 KiB minimal child uses only Kernel32 imports and a direct entry point with
no CRT startup. Its `/GS-` build is solely a minimal bootstrap diagnostic. The
157 KiB native suite uses `/MT`, normal compiler security checks, CFG, NX and
ASLR; its only static DLL import is also Kernel32. Neither is a task adapter.

In debug mode only, Microsoft symbols for the exact installed ntdll identify
`_PEB.NtGlobalFlag` by name. The trusted diagnostic host downloads that public
PDB into generated output using its local developer DbgHelp/SymSrv libraries.
The child receives no network capability. The host enables only the loader-snaps
bit in the newly created suspended child's PEB. It does not alter the executable
file, IFEO registry, machine flags or any access policy. Missing matching symbols
fail the diagnostic; there is no guessed-offset fallback.

Fixed NT-call breakpoints observe object names, access masks and return statuses
inside that diagnostic child. Each original instruction is restored and
single-stepped; peer threads are paused during that step. Arguments, return
values and control flow are not replaced. Normal native and CPython cases have
neither loader flags nor debugger breakpoints. Debugging changes timing and has
its own bounded event loop; resource and lifecycle conclusions use the ordinary,
untraced cases. This is not production IPC or recovery code.

The native suite re-exercises the prior sealed filesystem/profile/TEMP/registry,
credential/DPAPI, network and child-process attacks. Memory, CPU and supervisor
death are separate real cases. The ambient write is mandatory in both final-token
impersonation and the running native child, before any later native probes. A
successful write stops the investigation. Ambient **read** access is deliberately
reported separately and succeeds with WRITE_RESTRICTED.

Only generated fixture/runtime copies, the fresh desktop, child/token objects
and this attempt's owned profile/storage receive ACLs. Links/junctions/hardlinks
in the fixture tree are refused. Cleanup restores/removes only the generated
profile and deletes only the empty storage key it created. Crash cleanup uses
the exact marker identity and refuses nonempty registry storage. No existing
Windows resource permissions are repaired or relaxed.
