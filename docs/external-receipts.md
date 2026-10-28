# Offline supervised receipt bridge

This completes the offline slice of [Issue #6](https://github.com/samuelwhite/development-autonomy-framework/issues/6).
It exports a proposed task and compares supplied evidence. It does not launch
Codex, access GitHub or HomeCI, discover credentials, mutate a repository, admit
an attempt, reserve money, retry, merge, or enter the synthetic DAF engine/Store.
The runtime has no third-party dependencies. These contracts are not a sandbox.

## Evidence states and authority

| State | Meaning |
| --- | --- |
| `proposed_supervised_task` | A deterministic task bundle; no authenticated approval or recorded execution admission. |
| `externally_supplied_unverified` | Every accepted external receipt, PR/CI record and reconciled result. |
| `locally_observed` | Only a comparison performed here, or a digest of bytes explicitly supplied locally. |
| Verified external provenance | Unavailable. A caller cannot select this state. |

An entirely fabricated but internally consistent input passes comparison and stays
unverified. Validator IDs and source labels are claims, not authenticated identities.
A digest proves neither who produced bytes nor whether their contents are true.
`all_required_checks_claimed_passed` describes claims only; it cannot approve work.
An exit code of zero means comparison succeeded, including consistent failed or
pending checks. No result is written to the DAF journal.

## Run the synthetic walkthrough

From the repository's `src` directory, use Python 3.12+:

```text
python -m daf.receipt_bridge prepare daf/examples/receipts/request.json
python -m daf.receipt_bridge validate daf/examples/receipts/receipt.json
python -m daf.receipt_bridge reconcile daf/examples/receipts/bundle.json daf/examples/receipts/receipt.json daf/examples/receipts/evidence.json --artifact homeci-result daf/examples/receipts/artifact.json
```

The committed `bundle.json` is the deterministic output of the first command.
To inspect refusal, copy the examples to a disposable directory and change the
receipt head SHA, task digest, artifact bytes or a claimed changed path. Run again:
the CLI returns exit 2 and a fixed reason code. Restore the fixture before trying
a different mutation. Do not use a consumer repository or real credentials.

After installing the package, `daf-receipts` exposes the same subcommands.
Commands read only explicitly named local files and emit JSON on stdout.
Use an explicitly chosen, new file if redirecting output; the shell owns that
write. The proposal includes the supplied instruction verbatim as JSON data:
keep secrets and private material out of public examples and reports. There is
no graphical UI, provider execution, status server or background service.

## Request and bundle contract

See [request.json](../src/daf/examples/receipts/request.json) and
[bundle.json](../src/daf/examples/receipts/bundle.json) for complete examples.

The strict schema-1 request contains a plan SHA-256, milestone ID, recorded-attempt
label, repository, baseline SHA-1, instruction, exact allowed file paths and
required checks. Each required check pins its name, validator label, source label,
workflow path and workflow SHA-256, plus an artifact name or null. HomeCI-labeled
checks require an artifact. The plan digest and attempt label are supplied
references; this module does not establish that a plan was approved or an attempt
was admitted. Consumers must retain their source-owned plan and admission records.

`prepare_task` hashes canonical JSON of the **entire request**, including scope
and validator/workflow requirements. The bundle carries `execution_authority:
false` and `execution: supervised_codex`. Validation recomputes the fingerprint;
changing only a stored digest or embedded request is refused. A caller able to
rewrite and rehash the whole proposal still gains no authority.

File scopes use exact portable ASCII relative filenames, not globs or directory
prefixes. Traversal, absolute paths, backslashes, repeated separators, reserved
Windows names, alternate data streams, trailing dots, Git metadata and
case-colliding duplicates are refused. Required workflow files cannot appear in
the proposed edit scope. These are lexical comparisons, not filesystem isolation
or a complete policy for a future worker.

## Receipt and reconciliation contract

Schema-1 `external_receipts.py` remains a standalone unverified claim validator.
It checks exact fields, lowercase 40/64-character digests, IDs, same-repository
GitHub PR/run links, duplicate check names and known execution/result labels.
Malformed enum values now raise `Refused`, including JSON arrays and objects.

`reconcile_receipt` additionally compares the receipt against the proposed task
and a normalized, operator-supplied evidence document. This document is **not raw
GitHub API JSON**. Its complete example is
[evidence.json](../src/daf/examples/receipts/evidence.json).

- Plan, milestone, attempt, repository, baseline and task digest must match.
- PR URL and head/baseline revisions must agree across supplied documents.
- Every claimed changed file must be in scope. Include both old and new names for
  renames. Completeness of the change list is not proven.
- Required check names must be present exactly once. Validator/source labels and
  workflow path/digest must match the proposal.
- Each check names a positive run ID, run attempt and job ID. Jobs cannot be
  duplicated; checks sharing a run cannot mix attempts or workflow provenance.
  The output derives attempt-specific and job-specific links from these IDs.
- Only completed/success maps to claimed passed. Skipped, neutral, cancelled and
  other non-success conclusions map to failed; unfinished checks map to pending
  and must have no conclusion. Contradictory receipt results are refused.
- Named artifacts have an ID and SHA-256 nested under a specific check, head,
  run and attempt. Each required file must be explicitly supplied with
  `--artifact NAME LOCAL_FILE`; missing, extra, duplicate or changed inputs are
  refused. The hash covers the exact local file bytes, with no newline conversion
  and no archive extraction.

Artifact comparison does not authenticate a download, parse HomeCI result
semantics, prove job membership, or establish that the named runner was trusted.
Run URLs alone are not immutable snapshots; retain the input JSON, attempt/job
IDs and content digests. No remote response or artifact is fetched.

JSON and artifact files are limited to 2 MiB each; at most 32 checks/artifacts and
256 paths are accepted. Duplicate JSON keys, non-finite numbers, linked input
files/directories and non-regular files are refused. Fixed refusal codes do not
echo document contents or filenames. Filesystem checks are best-effort hygiene;
same-user races or malicious changes to this Python process are outside the boundary.

## Assessment and next review gates

The minimum useful next milestone is a **separate, read-only GitHub evidence
collector**, after an explicit threat review and owner approval. Keep it outside
this offline runtime. It should bind the expected repository and PR, fetch every
page, capture the actual PR head/base and checkout revision, and independently
resolve the workflow, run attempt, job IDs, required check names, status and
conclusion. Detect head changes during collection. Record observation time,
response digests and provider identity separately from supplied claims. Reconcile
PR merge-ref runs separately from exact-head runs: a green check attached to a PR
head does not prove that head was the checkout tested.

HomeCI verification should first consume already-produced, authorized artifacts
through that read-only collector: verify immutable run/job/attempt membership,
artifact identity, expiry, content digest and the producer's result schema.
Runner trust and workflow policy require independent evidence. HomeCI dispatch,
cancellation and private runner access are separate later approvals. This public
repository must continue using only its existing GitHub-hosted CI matrix.

A real supervised Codex adapter requires a reviewed task/admission identity,
isolated workspace/process and credential handling, explicit human supervision,
bounded retry/recovery behavior, and independently enforced cost/stop policy.
OpenAI documents sandbox permissions and approval decisions as distinct controls;
a proposal fingerprint cannot substitute for either. See the
[official agent approvals and security guidance](https://learn.chatgpt.com/docs/agent-approvals-security),
consulted 2026-10-28. No Codex flags, configuration, credentials or process launcher
are installed here.

Keep source-owned review and CI authority. The offline suite does not certify
real execution, remote cancellation, billing limits, malicious-worker containment,
or authenticated acceptance. Independent code review and owner authorization are
still required before merging this PR; later adapters need their own review.
