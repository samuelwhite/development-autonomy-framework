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

Prepare the private task bundle with one required check named
`DAF documentation candidate on HomeCI`. Set `source` to `github_actions`,
`validator_id` to the lowercase private validator repository, and `artifact_name`
to null. Pin `.github/workflows/daf-documentation-candidate.yml` and the SHA-256
of its canonical Git blob bytes. Use the Git object or GitHub's decoded blob
bytes to avoid checkout line-ending conversion.

1. Review and approve the task bundle and the private Forge workflow activation
   separately. After the workflow is activated, verify the actual Forge main
   revision and its workflow bytes against the reviewed source and task digest.
2. Keep DAF main at the task baseline. Create the one-file candidate from that
   baseline and open a draft PR. Use a separate checkout of the exact reviewed
   verifier head from DAF PR #27 to run the command. Keep DAF main pinned until
   verification completes. The command checks the live main ref before dispatch
   and before accepting the result.
3. Prepare the private approval record with `task_sha256`, `candidate_pr`,
   `candidate_sha`, `validator_repository`, `workflow_id`, `workflow_revision`,
   `workflow_path`, `workflow_sha256`, and `runner`. Bind the exact activated
   Forge revision, draft PR and candidate SHA. Verify the operator's approval
   against those values and use a single persistent private journal.

The command refuses any difference between the required check and the approved
validator, path, or workflow digest before reserving or dispatching the attempt.
Approval and journal files belong in private operator storage. The command does
not authenticate the approver.

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

### Recover a known HomeCI run

Use the same private journal and the exact approval for the draft. When the
draft was assigned by the publisher, get its `draft_pr` from the retained
`document-pilot.json`. Use that value as `candidate_pr` in the verifier approval
alongside the approved candidate SHA, task digest and Forge policy.

```text
python scripts/homeci_candidate.py bundle.json observe-approval.json --allow-validator OWNER/REPO --journal LOCAL_DIR
```

This form sends GitHub GETs only. It cannot publish a branch, create a pull
request or dispatch a workflow. For a reserved run, its `run_id` stays the
same across observations. Exit code 1 with `state: queued` or `state: running`
means the run is pending. Add `--wait-seconds 900` to wait while its metadata
is readable. A refusal returns exit code 2 and a `reason`, such as
`wrong_workflow_dispatch`. The command pauses on that refusal. Run the same
read-only command later with the existing journal. A result of
`verification: passed` and exit code 0 identifies the accepted original run,
attempt, job, runner and checkout. Retain the output with the operator
evidence. The read-only command leaves the original observation history intact.

The documentation pilot for PR #32 retained a first refusal and a later
accepted observation of the same run. The first response body was unavailable,
so the field that caused the rejection remains unknown.

The observation compares the workflow bytes, revisions, run, original attempt,
job, runner and required step results. It reports the checkout based on GitHub's
result for the pinned workflow's exact-checkout step. This is a GitHub observation
of the runner's assertion. Independent producer provenance remains unavailable.
The operator command retains observations in the journal, including failures and
incomplete attempts. Mission Control's optional private `homeciCandidate` setting
binds the HomeCI display to a reviewed `workflowId`, `workflowRevision` and
`runner`. It displays GitHub's job evidence for that workflow. Approval and the
interruption journal are checked by the operator command.

## Documentation pilot rehearsal

Run from the DAF source checkout with Python 3.12 or newer and Git.

```text
python scripts/rehearse_document_pilot.py PILOT_DIR
python scripts/rehearse_document_pilot.py PILOT_DIR
```

Choose a new local directory. The first invocation creates a Git source
repository and a disposable bare remote, checks the reviewed preview against
the exact commit bytes, publishes one task branch and uses simulated GitHub
responses for one draft and one HomeCI dispatch. On restart, the second
invocation returns the same candidate and observation. The JSON reports the
total writes in the simulated transport. GitHub and Alfred receive no requests.

To test an ambiguous response, add `--lose uncertain-draft` on the first
invocation in a new directory. Run again without the option to reconcile the
same draft. Use `uncertain-branch` or `uncertain-dispatch` at the other write
boundaries. The SQLite journal preserves intent and prior observations.
The latest read-only snapshot is in `PILOT_DIR/journal/document-pilot.json`.
Keep the directory intact after an interruption or an unknown outcome.

The orchestration function accepts a trusted transport with complete branch
and draft queries, create-only branch publication, draft creation, GitHub GETs
and one HomeCI dispatch. It binds the approval to the task, preview, author and
timestamp record, exact candidate, and verification policy. The rehearsal
command supplies only the local transport. Live publication and dispatch need
separate review and authority for those exact bindings.

## Approved live documentation pilot

After the transport is reviewed and the exact live pilot is authorised, run
the operator CLI from that reviewed source checkout. The repository argument
points to the local Git checkout containing the approved baseline. Git and the
existing authenticated GitHub CLI session handle publication and verification.

```text
python scripts/live_document_pilot.py REPOSITORY BUNDLE EDIT REVIEW APPROVAL --approval-sha256 APPROVED_DIGEST
```

Obtain `APPROVED_DIGEST` as part of the private approval decision. It is the
canonical DAF JSON SHA-256 of the complete approval record. That record has
`schema_version` set to 1, the explicit DAF `repository`, the absolute path
to the existing private `journal` directory, and `pilot` with these fields:

- `task_sha256`, `preview_sha256`, `review_sha256` and `candidate_sha`
- `verification` with `validator_repository`, `workflow_id`,
  `workflow_revision`, `workflow_path`, `workflow_sha256` and `runner`

The operator supplies the task bundle, literal edit and author/timestamp
review record from the approval decision. The command checks the same
pinned DAF and Forge revisions before writes and retains the original
interruption and dispatch journals. Git publishes only the exact task branch,
with a lease requiring an absent ref. The PR lookup includes closed PRs. A
closed, mismatched or ambiguous PR blocks progress. When GitHub assigns the
draft number, the verifier reads back its exact identity and scope before
reserving one dispatch on the approved workflow.

Use the same command and private journal to observe a queued run or recover an
ambiguous response. A recorded write intent is never sent again. If the
original result stays unknown, retain the same journal and investigate its
evidence. A new journal would lose the local intent history. Keep the DAF
default branch pinned until candidate verification finishes. The command
pauses at draft review and writes the same Mission Control snapshot as the
rehearsal.

## Supervised Python code rehearsal

From a source checkout with Python 3.12+ and Git, choose a disposable directory.

```text
python scripts/rehearse_code_pilot.py ../daf-code-demo
python scripts/rehearse_code_pilot.py ../daf-code-demo
```

The fixture proposes one edit to `src/label.py`. Its trusted focused test
already exists in the fixture baseline. Inspect `proposal.json`, `candidate.diff`,
and `approval.json` for the exact edit, baseline, candidate and simulated decision.
`validation.log` contains the local test result. The real Git branch lives in
the disposable bare remote. The draft and Forge request are simulated and
persisted beside the journal. Both commands report one branch publication,
one draft and one validation request for the same candidate.

Use a fresh directory for each scenario. First run `--scenario lost-response`
or `--scenario incomplete-metadata`, then run without the option against the
same directory to observe the original request. `changed-baseline` and
`extra-file` refuse publication. `wrong-run` refuses job evidence. `failed`
gives the trusted test harness a deliberately wrong expectation and retains
the resulting failed test. A blocked or failed rehearsal exits with code 1.

To see the transition in an isolated Mission Control instance, mount the
rehearsal's journal directory read-only and point `DAF_DOCUMENT_PILOT_FILE`
at `document-pilot.json`. Use the fixture repositories in the web README
and refresh Development or HomeCI after resuming the attempt.

The live documentation verifier requires a single Markdown path under `docs/`.
The code rehearsal uses the task fingerprint, exact Git scope, durable write
intents, dispatch reservation and run identity checks within its disposable
fixture. A live code pilot needs a reviewed code-edit policy that binds
the exact source path, baseline, candidate bytes and focused test identity,
and a private Forge workflow that enforces that scope and runs the trusted
test under the approved execution boundary. Activate that policy and workflow
only after validating their exact digests against the reviewed candidate.

## Two-task operator rehearsal

From a clean source checkout, use Python 3.12+ and Git. Choose a new disposable
workspace. No GitHub session or validator credential is needed.

```text
python scripts/rehearse_operator.py preview ../daf-operator-demo
python scripts/rehearse_operator.py run ../daf-operator-demo --approve docs=DOCS_SHA256 --approve python=PYTHON_SHA256
python scripts/rehearse_operator.py history ../daf-operator-demo
```

Review the exact diff and scope from `preview`. Substitute each task's own
`approval_sha256` into the `run` command. `preview` prepares local Git objects
and the disposable baseline. Candidate publication starts after explicit
admission. The fingerprint covers the plan, task, baseline, candidate, diff
and validator policy. Each simulated task has its own approval, simulator ledger
and receipt history. The Markdown task uses the documentation policy. The
Python fixture runs the existing trusted test against checked fixture bytes.
Success reports `review`, the snapshot path and one branch, draft and dispatch
write per task. Repeating `run` with the same workspace and approvals observes
the same branch, draft and run.

For example, use a fresh workspace to rehearse a lost Python dispatch response.

```text
python scripts/rehearse_operator.py preview ../daf-recovery --task python
python scripts/rehearse_operator.py run ../daf-recovery --task python --approve python=PYTHON_SHA256 --lose dispatch
python scripts/rehearse_operator.py observe ../daf-recovery --task python
python scripts/rehearse_operator.py history ../daf-recovery --task python
```

The initial call reports `dispatch_outcome_unknown`. `observe` reads the same
simulated run without a publisher or dispatch callback and leaves the original
refusal in the history. Substitute `--lose branch` or `--lose draft` to exercise
publication recovery. After observation, use `run` with the original approval
if the next approved operation still needs to start. The journal prevents a
second write for any action already reserved. An unobservable action stays
pending.

For Python, use `--scenario queued`, `incomplete-metadata`, `wrong-run` or
`failed` with an approved `run` in a fresh workspace. A queued run can be
observed again. Incomplete metadata reports the bounded identity fields that
failed. A contradictory run is blocked pending inspection. Terminal failure
stays in the journal for review. Use `history` to inspect accepted receipts
after a baseline moves. The acceptance is attached to the tested candidate.
For a real draft that has merged, compare the Git tree of the merge commit
with the tested candidate tree as a separate read-only observation. Tree
equality cannot change the run's recorded candidate. A different tree needs
its own validation evidence.
