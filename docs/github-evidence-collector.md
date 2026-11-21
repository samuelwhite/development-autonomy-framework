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
