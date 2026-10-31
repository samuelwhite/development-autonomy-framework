# M2.1A native foundation — candidate for Product acceptance

**Maintainer-only. Do not ship or connect to Electron.** After the bounded
persistence repair, two consecutive runs passed all 55 mandatory cases with
independently verified evidence. M2.1A is a candidate for Product acceptance only;
M2.1B and desktop execution remain separately gated.
See [the validation record](../../docs/m2.1a-native-validation.md) and
[security decision](../../docs/adr-003-bounded-native-foundation.md).

`producer.cpp` and `verifier.cpp` build independent fixed executables. Neither has
path, command, plugin or provider inputs. Both consume bounded stdin bytes and
return only a closed stdout frame; they emit no diagnostic text. `sha256.h` and
`wire.h` supply pure SHA-256, strict UTF-8 and framing; the transformation is linked
only into the producer. The verifier compares ranges with a separate algorithm.

`contracts.py` is a trusted maintainer host library, not a Python worker or
execution controller. It validates the complete existing GitHub plan and local
specification separately, checks protected baseline blobs and creates immutable
canonical manifest bytes. `harness.cpp`, `probe.c` and `probe-suite.h` are isolated
acceptance tooling, never production entry points or desktop commands. The harness
selectively retains PR #13's token/profile/registry/job primitives and fixed
adversarial probes, without its Python, symbol, device or loader investigations.

## Closed contracts

`policy.json` and `replacement.json` are closed, hash-pinned v1 contracts. The
build identity has exactly schema, adapter, role, sha256 and bytes. The preparation
has exactly schema, attempt, source, local_spec, producer, verifier, policy and
inventory. `source` contains repository, plan_commit, plan_path, plan_sha256,
baseline, path and blob. Hash canonical JSON with sorted keys, compact separators,
ASCII escapes and no nonfinite numbers, matching DAF's existing canonical encoder.

All native integers are unsigned little-endian 32-bit. Requests contain exactly:

| Offset | Field |
| --- | --- |
| 0 | Eight bytes `DAFN21A1` |
| 8 | Version = 1 |
| 12 | Role: producer 1, verifier 2 |
| 16, 20, 24, 28 | Source, old block, new block, candidate byte counts |
| 32 | 32-byte preparation digest |
| 64 | 20-byte exact plan-source commit |
| 84 | 20-byte exact baseline target Git blob |
| 104, 136, 168, 200, 232 | Plan, source, old, new, expected candidate SHA-256 |
| 264, 296 | Policy and selected executable SHA-256 |
| 328 | Source, old, new, candidate bytes in that order |

Candidate count must be zero for the producer and nonzero for the verifier.
EOF is required after exactly the declared bytes. Max request is 147,784 bytes.
The native code checks all pinned source/policy digests against `bindings.h` and
recomputes byte hashes. Manifest/build digests are opaque host bindings: the child
cannot authenticate itself, approval or its parent. The trusted harness hashes
copied binaries, queries the actual child image and inspects the final token.
These checks depend on the trusted-host threat model, not worker self-attestation.

Responses have eight bytes `DAFO21A1`, version, role, status, candidate size,
32-byte preparation digest and 32-byte candidate digest: 88 bytes total. Successful
producer responses append exactly the candidate bytes; successful verifier results
append nothing. Failures have zero size and zero digests, with no appended bytes.
Statuses are 0 ok, 1 frame, 2 limit, 3 text, 4 binding, 5 occurrence, 6 preimage,
7 candidate, 8 IO. Exit status alone never validates an outcome.

Host outcomes record exact case/role, image/token checks, fresh identity hashes,
creation time, observed exit, CPU, peak process memory, elapsed time, termination
reason/latency and cleanup. Termination reasons are 0 normal/kernel exit,
1 wall deadline, 2 parent death, 3 output rejection, 4 requested cancellation.
Unexpected stdout/stderr stays in bounded memory. Only validated response fields
and enumerated expected probe outcomes may be persisted. No raw child logs exist.
The runner saves an unconfirmed case before launch and sanitized observations
before assertions. Fresh run/case identities and the exact 55-case manifest bind
every result. Unique temporary files, immutable checkpoints, flush/fsync and exact
readback protect publication. A separate unique failure file records the original
errno/winerror and phase even when primary replacement fails; an unavailable
failure record is reported honestly with an unsuccessful exit. No exception path
or private filename is serialized. No publication is retried.

Final qualification revalidates every required observation and all 55 cases. The
result and completion receipt must be published and read back before removing the
active marker. `evidence.read_qualified(root, acceptance.validate_final_case)` is
the read-only verification entry point: a `qualified` field alone is insufficient.
Active, pending, failed, malformed, conflicting or incomplete records cannot pass.
An old run is never resumed. This is standalone maintainer evidence persistence,
not M2.1B execution journalling or recovery. Historical `results.pending` files
remain untouched, with both earlier repaired sequences retained in review evidence.

## Maintainer reproduction

Build prerequisites: Windows 11 x64, ordinary non-elevated account, MSVC
14.50.35717 and SDK 10.0.26100.0 at the fixed paths in `build.ps1`.
No installation, signing, release, administrator dependency or system ACL changes.

```powershell
./desktop/native-foundation/build.ps1 -OutputDirectory dist/m21a-review
python desktop/native-foundation/acceptance.py dist/m21a-review
```

The cancellation gate requires exact complete LF/CRLF readiness, reason 4,
successful job termination, retained-handle signalling and zero active processes.
The suite records five attempts each for cancellation and helper/parent death.
Both new runs completed the fifth parent-death case. The historical 54-pass run
never launched it and remains incomplete. Stop on mandatory failure; no automatic
rerun is performed. Historical
build attempts included an omitted C++17 flag and a
PowerShell argument-array defect. Both failed compilation. A preliminary host
launch then failed with error 203 before child creation because required standard
Windows bootstrap variables were missing. The measured build restored only the
fixed OS-derived environment from PR #13; no permissions were relaxed.

The harness copies fixed binaries and generated fixtures into fresh owned attempt
directories, rejects fixture links/reparse points, sets the reviewed restrictions,
and launches suspended with the job already assigned. Only three IPC handles are
inherited. The bounded host request file is read by the host, never the child;
candidate bytes appear only in generated verifier transport fixtures, not the
target document or tracked repository content. These transport fixtures are
removed in the final cleanup audit.

Build manifests retain compiler hash, flags, OS, exact source and binary hashes.
`dumpbin` imports/headers are inspected for KERNEL32-only worker imports, ASLR,
DEP/NX, high-entropy VA and CFG. Static CRT imports include generic filesystem and
loader APIs; the authored worker never calls them or consumes source paths.
No `/GS-`, custom insecure startup, bcrypt import or CPython dependency is used.

Portable tests run separately:

```powershell
python -m unittest discover -s desktop/native-foundation -p "test_*.py" -v
```

They validate contracts and bytes, not access decisions. The real Windows suite
uses actual token operations and generated negative/positive controls. Credential
RPC error 1702, profile recreation error 87 and DNS error 11003 are explicitly
observations, not proof of access denial. The two-second CPU limit is periodically
enforced; strict read isolation and a hard CPU ceiling are not claimed.
