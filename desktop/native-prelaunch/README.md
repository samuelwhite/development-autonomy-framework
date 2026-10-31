# M2.1B prelaunch qualification — stopped, not qualified

**A3 feasibility follow-up:** the separate Product authorization permits only
`a3_qualify.py --a3-case-01 BUILD WORKERS FRESH_EVIDENCE`. The new native entry
point accepts only `case-01 probe`. Case 01 inspects the suspended process and
terminates it without resume. A five-second inspection supervisor and a
three-second termination wait are separate from the unchanged runtime watchdog;
the helper has a 30-second outer attempt limit and cleanup shares a 35-second
parent budget. The A1 claim, validator, source snapshots and failed evidence are
retained. No other matrix case or execution authority is enabled. See the
[A3 report](../../docs/m2.1b-a3-feasibility.md).

**A1 diagnostic follow-up:** separate Product authorization permits a bounded
probe repair and exactly one fresh `handles` / `probe` case. See the
[A1 design and evidence report](../../docs/m2.1b-a1-diagnostic.md). Both entry
points now refuse the other cases. The historical command below is no longer
accepted; A1 requires `qualify.py --a1-single BUILD WORKERS FRESH_EVIDENCE`.
M2.1B, full Gate A qualification and Gate B remain gated. The following records
the original stopped state and is not changed by a subsequent A1 result.

Standalone maintainer tooling only. **Do not package or connect this directory to
Electron.** The first Windows inherited-handle case timed out. Product's mandatory
stop condition applies; no repair, retry or subsequent gate was attempted.

See [the blocker report](../../docs/m2.1b-prelaunch-blocker.md) and its immutable
evidence for exact identities, limitations, cleanup and outstanding gates. A green
regression workflow cannot turn this failed qualification into execution authority.

`gate-host.cpp` includes the unchanged accepted M2.1A maintainer harness and wraps
its process-creation call for diagnostics. It preserves the existing restricted
token, LPAC, Job Object, desktop, environment, supervision and cleanup machinery.
It is not the proposed production supervisor. Its synthetic handle probes and
fault-injection cases must never become a renderer-accessible interface.

`identity.h` is an unqualified candidate for pinning files and parent directories,
checking exact bytes and file identities, and checking the suspended process's
OS-reported image paths and mapped-image allocation. The first case reached these
checks, but all binary-substitution and race cases remain unrun. This is not proof
of gate B, filesystem race resistance, or production suitability.

`handle-probe.cpp` checks its three standard pipes, then attempts fixed synthetic
file, mapping, event and process-handle operations. The first unauthorized-handle
operation produced no result before the wall deadline. Numeric handle reuse and
synchronous probe calls require investigation; there is no established bypass or
root cause. The original probe and exact failed build remain preserved.

`qualify.py` uses the existing closed preparation/response contracts. It creates
fresh fixtures and immutable start/result/completion records, stops at the first
failure, and retains digests instead of unknown child output. This is test evidence
tooling, not an implemented production execution journal or recovery mechanism.

The following commands identify the single historical execution, not permission
to rerun it. Existing output directories are refused:

```powershell
./desktop/native-prelaunch/build.ps1 -OutputDirectory dist/m21b-gates-build-02
python desktop/native-prelaunch/qualify.py dist/m21b-gates-build-02 dist/m21a-persistence-01 dist/m21b-gates-run-01
```

The exact executed qualifier is retained in the build snapshot. Its checked-in
version differs only by Ruff formatting; their parsed Python ASTs were compared
and match. The C++ and build sources have not changed since the failed test.

Any further diagnostic changes or native attempts await separate Product review.
