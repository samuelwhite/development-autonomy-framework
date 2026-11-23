# Bounded GitHub evidence collection

The offline package and receipt CLI remain transport-free. The separate source-checkout
adapter reads one explicitly allowed repository over GitHub HTTPS. It does not establish
owner approval, admission, runner trust, execution authority or spending authority.

| Boundary | Design |
| --- | --- |
| Credential and network | An explicit local token file and exact allowlist entry are required. Use a fine-grained credential limited to the selected repository, with Metadata, Pull requests, Contents and Actions read. The adapter cannot inspect token grants. It uses fixed GitHub GET endpoints, no ambient proxy, no redirects, no log downloads and no retries. |
| PR and files | Operator selects the PR and full expected head. The PR head and base must both belong to the selected repository and match the head and task baseline. Files must fit one complete page and the allowed paths, including both sides of renames. |
| CI | The operator selects a workflow ID, run ID and attempt for each required workflow. Only same-repository push and manual runs with an exact workflow path are accepted. The workflow bytes at the head must match the proposal digest. Synthetic PR merge runs, other workflow sources and changed attempts are refused. |
| Completeness | An advertised next page, count mismatch, duplicate, missing check, stale run or malformed response refuses acceptance. PR and run identities and workflow outcomes are reread before the receipt comparison. This bounds observed drift and does not create a transactional GitHub snapshot. |
| Request budget | Up to 24 workflows fit within 99 GETs for artifact-free observation: three PR and file reads, plus four reads per workflow. Artifact lookups count toward the same cap. The existing 90-second collection budget and single-page limits still apply. |
| Artifacts | The adapter checks run-level artifact name, ID, repository, head and expiry. GitHub's run-level artifact list does not bind the producer job and attempt. For artifact-required checks the adapter therefore stops before receipt reconciliation even if metadata matches. It neither downloads nor promotes artifact bytes. |
| Authority and disclosure | Authenticated GitHub GETs identify the transport used by this process, not a signed portable attestation. The nested offline comparison remains externally supplied and unverified. Output retains bounded IDs, statuses, conclusions and fixed reasons, with no credentials, file contents, raw upstream errors or runner information. Keep output for private repositories in private operator storage. |

Use a source checkout with Python 3.12 or newer:

```text
python scripts/github_evidence.py --allow-repository OWNER/REPO --token-file PRIVATE_TOKEN_FILE bundle.json receipt.json selection.json
```

The selection document has exactly these keys, with one entry per required workflow:

```json
{
  "repository": "owner/repo",
  "head_sha": "0123456789abcdef0123456789abcdef01234567",
  "pr": 123,
  "runs": [{"workflow_path": ".github/workflows/checks.yml", "workflow_id": 1, "run_id": 2, "attempt": 1}]
}
```

The result records `execution_authority: false` in all cases. It reports overall outcomes in
`workflow_runs` and required job outcomes in `checks`. An incomplete run must have an explicit
null conclusion, and a completed run must have a supported terminal conclusion. Only successful
overall runs are eligible for receipt comparison. A completed run with a still-pending required
job is refused. Even with a successful overall run, the separate, unverified comparison can
report failed required jobs. Refused or partial collections return a nonzero exit status and can
include observed snapshots. See GitHub's [workflow runs](https://docs.github.com/en/rest/actions/workflow-runs),
[attempt jobs](https://docs.github.com/en/rest/actions/workflow-jobs)
and [artifact listings](https://docs.github.com/en/rest/actions/artifacts).

## Next supervised milestone

Select one bounded documentation task and record the exact issue, plan digest, baseline,
allowed file and workflow identity. Require a separately authorised owner approval and
qualified isolated execution path before any worker starts. Cap time, attempts and spending
explicitly and exercise stop and recovery before accepting a candidate. Have a separate
operator run approved HomeCI verification and retain exact PR/commit/run/attempt/job evidence.
Qualify independent artifact producer binding before requiring artifact-backed acceptance.
End at Product review without merge or deployment. PR #16 and its native qualification gate
are outside this collector.

## Artifact-free documentation candidate verification

`scripts/homeci_candidate.py` is a separate operator command for a one-file Markdown
candidate. It uses the supervised bundle and a private approval record for the exact
draft PR, head, reviewed validator workflow and runner. The existing same-repository
collector remains read-only and artifact-backed receipt rules still apply.

After task approval and separate workflow activation, prepare a private JSON record
with `task_sha256`, `candidate_pr`, `candidate_sha`, `validator_repository`,
`workflow_id`, `workflow_revision`, `workflow_sha256`, and `runner`. The operator
must verify the approval against those values. The file and command cannot establish
the approver's identity. Use a single persistent private journal for the attempt.

```text
python scripts/homeci_candidate.py bundle.json approval.json --allow-validator OWNER/REPO --journal LOCAL_DIR --dispatch --wait-seconds 900
```

The supervised operator uses their existing authenticated GitHub CLI session. The
command reads the draft PR and its complete file list, then reserves the task in
the journal before requesting the private workflow. Repeating the command observes
the original run. If dispatch may have succeeded and GitHub has no matching run,
the result stays unknown. Preserve the journal and investigate the original request
before considering a new approval. Omit `--dispatch` for a read-only inspection.
The pilot does not install a service credential or change Mission Control's access.

The observation compares the workflow bytes, revisions, run, original attempt,
job, runner and required step results. It reports the checkout based on GitHub's
result for the pinned workflow's exact-checkout step. This is a GitHub observation
of the runner's assertion. Independent producer provenance remains unavailable.
The operator command retains observations in the journal, including failures and
incomplete attempts. Mission Control's optional private `homeciCandidate` setting
binds the HomeCI display to a reviewed `workflowId`, `workflowRevision` and
`runner`. It displays GitHub's job evidence for that workflow. Approval and the
interruption journal are checked by the operator command.
