# M1.1 — Commit-pinned public GitHub planning ingestion

**Proposal only. No authenticated approval, Codex invocation, deployment or live execution.**

This is an incremental read-only planning input for DAF built on its existing schema-1 plan validator and PR #7's offline supervised task bundle. It does not start workers, dispatch CI, obtain credentials, access private repositories or change GitHub content.

## Boundary

The packaged `daf.github_planning` module is **offline** and preserves the existing distribution guard. The opt-in source-checkout script `scripts/github_public_ingest.py` makes bounded unauthenticated HTTPS GETs to the fixed `api.github.com` host: one exact Git commit, one non-recursive tree per source-path component, and one contents file at that commit. Paths have at most 16 components (18 requests maximum); every response is capped at 192 KiB and the source document at 64 KiB. Truncated or oversized trees refuse instead of broadening access. It follows no redirects, performs no retries and reads bounded responses. The CLI requires `--public-read`. Private GitHub authentication is a later, separately approved capability.

The source JSON has exactly `schema_version`, `plan` and `tasks`. The `plan` is validated using DAF's existing synthetic schema-1 contract (ordered dependencies, acceptance criteria, protected files, budget shapes, merge/deploy disabled). Every milestone must have exactly one `tasks` entry with an instruction, exact allowed paths and required checks. The complete document is validated before any selected proposal is returned: invalid unselected tasks, incomplete dependency coverage or conflicting checks refuse the import. All tasks must reference the same workflow path/digest and required check names as the plan.

Scope comparison uses case-folded path components on every platform. Allowed paths must be descendants of a code prefix and must avoid protected directory entries/descendants and exact protected files. `Private/` therefore blocks `private/file.py`, while `private-not/file.py` remains distinct. Exact Git spelling and plan bytes are preserved; fetch paths are never lowercased. Case-colliding protected declarations and inconsistent spellings of one task file are refused. Reusing the same exact file in successive milestones is permitted. Traversal, backslashes, alternate streams, trailing dots/spaces, device names, short-name aliases and unsafe source paths remain refused.

The public [sample plan](../src/daf/examples/planning/public-m1.json) contains **synthetic task instructions and illustrative workflow/protected-file hashes**. M1.1 validates these supplied fields syntactically; it does not independently verify workflow or protected-file bytes. This is not a real approval, execution attempt, budget reservation or CI verification.

## Usage

From a checkout containing the source script, create an **existing, empty local output directory** and supply the exact commit SHA containing the source record:

```text
python scripts/github_public_ingest.py \
  --repository samuelwhite/development-autonomy-framework \
  --commit <exact-40-character-source-commit> \
  --path src/daf/examples/planning/public-m1.json \
  --milestone F1 \
  --output-dir <existing-local-directory> \
  --public-read
```

No unpinned branch, tag or user-supplied URL is accepted. The GitHub commit SHA must match the returned commit object. The importer follows the exact commit tree through directory entries (`040000`) to a regular blob (`100644` or `100755`), rejecting symlink/submodule modes at any component. The returned contents blob must match that tree entry as well as its byte hash and size. Executable file mode is metadata only: no source file is executed. GitHub documents that the [Contents API can dereference symlinks](https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28#get-repository-content), which is why checking its `type` alone is insufficient; [tree modes](https://docs.github.com/en/rest/git/trees?apiVersion=2022-11-28#get-a-tree) provide the additional binding. The returned record includes the repository, commit, file path, source blob/content hashes, DAF plan digest, dependent milestone IDs, acceptance criteria and a deterministic PR #7 task bundle. The bundle's `proposal-...` attempt label is **not** a real admitted worker attempt. All external data remains observed/unverified, and `execution_authority` is always `false`.

## Idempotent, fail-closed storage

The ingestion ID hashes **repository + commit + source path + milestone ID**, never a timestamp or mutable content. Repeating an identical input returns `already_present` with no new record. Different content under the same pinned identity returns `ingestion_conflict` without overwriting the original. A complete temporary file is fsynced and atomically hard-linked into an existing directory; if hard-link creation is unsupported, the write refuses. This store is not DAF's execution journal or a rollback-resistant security boundary.

`validate_ingest_record` enforces exact record/source keys, schema version, proposal status, false execution authority, null approval, digest formats and repository/plan/milestone/bundle bindings. Unknown trust or spending flags are refused. `load_ingest_record` applies this validation to bounded regular local files; repeated storage revalidates the existing record before comparing bytes. Records cannot promote themselves to approved or verified status. Valid existing records retain the same identity, payload and idempotent behavior.

These checks establish shape and internal consistency, not authenticity. The stored projection does not contain the full source plan, so loading alone cannot re-prove dependency closure or scope against that plan. M1.2 must retain/revalidate the complete pinned source when projecting a whole plan, use the validated loader, and keep imported data separate from approval, execution and verification. No stored receipt or hash is execution authority. Proposed edit-path symlinks and workflow/protected-file contents are not inspected in a checkout; any future execution boundary must independently resolve and enforce them.

Data and output sizes are bounded. Duplicate JSON keys, malformed GitHub metadata, out-of-scope paths, conflicting checks, and symlinked storage paths are refused. Neither the GitHub public API response nor the file checksum authenticates owner approval. Same-user filesystem tampering and local process isolation remain outside M1.1.

## Agreed M2/M3 refinements remain unchanged

**M2 — Bounded local Codex:** before unattended operation, independently enforce spend/token exposure, stop controls, worker uniqueness, scope/isolation, crash recovery and bounded retries. A task instruction or DAF fixture budget is not an enforcement boundary.

**M3 — Autonomous progression:** Codex → local tests → independent HomeCI → exact-revision evidence → GitHub PR → next *authorised* milestone, with safe stopping for exceeded scope, exhausted budgets or required owner decisions. No implicit merge, deployment, permission expansion or Oracle activation.

Remaining M1 gates are genuine owner approval and independently authenticated GitHub/CI evidence. This source-only pilot does **not** change DAF's live admission, budget, journal, worker, CI, public exposure or security configuration. PR #7 was merged as `ecd08912c4a809cc14faba4ca3de9ca4d2d04d92`. PR #8 is retargeted to main and remains draft for its separate Product review. See [integration validation](m1-integration-validation.md).
