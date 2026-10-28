# M1.1 — Commit-pinned public GitHub planning ingestion

**Proposal only. No authenticated approval, Codex invocation, deployment or live execution.**

This is an incremental read-only planning input for DAF built on its existing schema-1 plan validator and PR #7's offline supervised task bundle. It does not start workers, dispatch CI, obtain credentials, access private repositories or change GitHub content.

## Boundary

The packaged `daf.github_planning` module is **offline** and preserves the existing distribution guard. The opt-in source-checkout script `scripts/github_public_ingest.py` makes exactly two unauthenticated HTTPS GETs to the fixed `api.github.com` host: one Git commit and one contents file at that commit. It follows no redirects, performs no retries and reads bounded responses. The CLI requires `--public-read`. Private GitHub authentication is a later, separately approved capability.

The source JSON has exactly `schema_version`, `plan` and `tasks`. The `plan` is validated using DAF's existing synthetic schema-1 contract (ordered dependencies, acceptance criteria, protected files, budget shapes, merge/deploy disabled). Each `tasks` entry specifies a milestone, instruction, exact allowed paths and required checks. Paths must fit the plan's code prefixes, avoid protected prefixes and acceptance files, and reference the same workflow path/digest and required check names as the plan.

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

No unpinned branch, tag or user-supplied URL is accepted. The GitHub commit SHA must match the returned commit object. The source file must be ordinary base64 file content with a matching Git blob SHA and size (not a symlink/submodule). The returned record includes the repository, commit, file path, source blob/content hashes, DAF plan digest, dependent milestone IDs, acceptance criteria and a deterministic PR #7 task bundle. The bundle's `proposal-...` attempt label is **not** a real admitted worker attempt. All external data remains observed/unverified, and `execution_authority` is always `false`.

## Idempotent, fail-closed storage

The ingestion ID hashes **repository + commit + source path + milestone ID**, never a timestamp or mutable content. Repeating an identical input returns `already_present` with no new record. Different content under the same pinned identity returns `ingestion_conflict` without overwriting the original. A complete temporary file is fsynced and atomically hard-linked into an existing directory; if hard-link creation is unsupported, the write refuses. This store is not DAF's execution journal or a rollback-resistant security boundary.

Data and output sizes are bounded. Duplicate JSON keys, malformed GitHub metadata, out-of-scope paths, conflicting checks, and symlinked storage paths are refused. Neither the GitHub public API response nor the file checksum authenticates owner approval. Same-user filesystem tampering and local process isolation remain outside M1.1.

## Agreed M2/M3 refinements remain unchanged

**M2 — Bounded local Codex:** before unattended operation, independently enforce spend/token exposure, stop controls, worker uniqueness, scope/isolation, crash recovery and bounded retries. A task instruction or DAF fixture budget is not an enforcement boundary.

**M3 — Autonomous progression:** Codex → local tests → independent HomeCI → exact-revision evidence → GitHub PR → next *authorised* milestone, with safe stopping for exceeded scope, exhausted budgets or required owner decisions. No implicit merge, deployment, permission expansion or Oracle activation.

Remaining M1 gates are genuine owner approval and independently authenticated GitHub/CI evidence. This source-only pilot does **not** change DAF's live admission, budget, journal, worker, CI, public exposure or security configuration. PR #7 is the separate unmerged foundation for this stacked change.
