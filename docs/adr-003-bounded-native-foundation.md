# ADR 003: bounded native foundation for the single M2.1 correction

Date: 30 October 2026. Decision: narrowly approved by Product; implementation
acceptance **blocked at evidence persistence after the cancellation repair**.
[Measured status](m2.1a-native-validation.md).

Product accepts the WRITE_RESTRICTED LPAC ambient-read exposure and periodically
enforced two-second Job Object user-CPU limit for this fixed, first-party,
deterministic native Markdown replacement only. Neither strict per-attempt read
isolation nor a hard two-second CPU ceiling is claimed.

The packaged producer and separate verifier accept bounded byte frames, never
paths, commands, interpreters, plugins, scripts or provider settings. The host
owns source preparation and filesystem operations. No worker intentionally reads
ambient files, opens source files, writes candidate files, accesses credentials
or networks, or supplies approval/security authority. Each receives a fresh LPAC
identity and fresh per-attempt restricting SID. No broad restricting SID,
administrator privileges, machine-wide ACL edits or unsandboxed fallback is allowed.

Retain low integrity, registryRead only, sealed profile/package/TEMP/registry,
OWNER RIGHTS controls, protected generated runtime/workspace objects, explicit
bounded IPC handles, prohibited child creation, one process per job, no breakaway,
128 MiB process memory and kill-on-close. Independently supervise ten wall seconds
per worker. Keep 30-second attempt and 35-second parent deadlines for later
controller integration. Record observed resources and termination latency.
Unexpected output is bounded and rejected before persistent evidence; exit zero
and a success claim are insufficient.

GitHub remains the planning authority. The genuine plan defines task scope only;
local replacement bytes are separately identified. Neither plan import, these
contracts, a build digest nor successful verification grants launch authority.
Future M2.1B must implement host-owned admission, exact-byte native approval,
single-use expiring volatile grants, durable history, Stop/recovery and desktop
integration. This slice does not implement them.

Research PRs [11](https://github.com/samuelwhite/development-autonomy-framework/pull/11),
[12](https://github.com/samuelwhite/development-autonomy-framework/pull/12) and
[13](https://github.com/samuelwhite/development-autonomy-framework/pull/13) remain
unchanged, draft and unmerged. Only reviewed isolation primitives and fixed probes
are reused. No CPython worker, loader tracing or diagnostic dependency investigation
is imported into the production binaries.

The original cancellation failure is retained as historical evidence. The exact
CRLF mismatch was reproduced and narrowly repaired. A complete 55-case run passed,
but the final source revision's repeat stopped after 54 passes when evidence
publication failed before the fifth parent-death case. Both unqualified evidence
files are retained; no further native launch followed. Do not infer qualification
from the earlier run or CI, weaken the gate or describe M2.1A/M2.1 as complete.

This exception does not extend to M2.2, M3, Python workers, arbitrary or generated
executable code, repository scripts, Codex/Claude or autonomous development. General
AI execution needs a separately qualified strict-isolation architecture. Signing,
clean Windows acceptance and screen-reader qualification remain separate gates.
