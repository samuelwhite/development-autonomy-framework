# External supervised execution receipts — scope and safety

This experimental module is a **portable offline evidence-input validator**, not a Codex adapter or a credentialed GitHub bridge.

`validate_external_receipt` validates an operator-supplied milestone/attempt, baseline/head SHA, task digest, execution label, PR link and zero or more CI-check claims bound to the same head SHA. It refuses mismatched revisions, unknown statuses, duplicate checks and cross-repository links. `receipt_sha256` computes a deterministic content digest; it **does not** prove a claim was made by GitHub or Codex.

Every accepted receipt remains `externally_supplied_unverified` even if a caller claims a check passed. The module does not enter the DAF engine, authorize an attempt, reserve live tokens, touch `Store`, contact a network, dispatch a process, mutate source, merge a PR or promote evidence to authoritative status. There are no credentials or provider requests.

## Next adapter gates (not yet implemented)

1. Independent GitHub read-only verifier fetches the PR head and exact workflow/job status with approved delegated identity, binds each claim to the actual exact commit, captures provider response digest and marks validated observations separately.
2. A supervised Codex task adapter executes only an explicitly scoped, authenticated, owner-reviewed task, with OS/process isolation, hard provider-cost exposure caps, bounded retries and untrusted-output handling.
3. HomeCI runner integration dispatches only allowlisted existing workflow targets with immutable SHA and exact artifact reconciliation; never cancel unrelated jobs.
4. DAF needs a reviewed admission/identity/cost policy bridging existing synthetic milestone engine and bounded transport experiments **before unattended continuation**.

No fixture approval marker grants real execution authority. Keep framework changes separate from any customer's repository and review all security-sensitive work.
