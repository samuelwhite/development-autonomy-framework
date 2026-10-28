# DAF v0.2 offline UI prototype

Double-click `index.html` in a current browser on Windows or Linux. No install,
server, account, real project access or credentials. All connections, tasks,
approvals, checks and usage are **simulated**. The source ZIP contains this folder;
the v0.1 Python packages do not.

Read [the Product proposal](../docs/v0.2-product-proposal.md) for the proposed journey,
integration research, limitations and implementation sequence.

For Product review, try:

1. Codex + Review only: connect, verify, prepare and start the sample task.
2. Claude Code + Supervised edits: approve once, or deny and stop.
3. Failed verification: Continue remains disabled until a successful fixture check.
4. Mission Control → Try a failure scenario: budget refusal, lost connection or
   failed independent check (edit mode).
5. Stop while running or waiting for approval. Nothing resumes automatically.
6. Reload during active work: reconcile the same attempt before starting another
   simulation. Unknown outcomes retain a reservation and cannot be reset from the UI.

State is tab-scoped, best-effort session storage, never authority. The demo displays
your task text but always uses the same README fixture. Restarting setup clears
fixture history. The v0.1 engine, journals, stop gate and ledger are untouched.

## Development checks

Node is optional for development tests and not required to use the prototype:

```text
node --check prototype/app.js
node --test prototype/simulation.test.cjs
python -m pytest
```

The Python suite invokes the Node fixture tests when Node is present (as on the
existing hosted CI runners). Source-package tests skip this separate prototype.
Optional end-to-end QA uses an existing Playwright installation and Chromium:

```text
node --test prototype/browser.test.cjs
```

Set `DAF_PLAYWRIGHT_PATH` to an existing package path if it is not in module
resolution; `PLAYWRIGHT_BROWSERS_PATH` selects an existing browser cache. No packages
or browsers are downloaded by the test. Optionally set `DAF_UI_ARTIFACT_DIR` to an
ignored output directory for screenshots. The browser runs offline and asserts zero
external resource requests, alongside approval, stop/reload, XSS escaping, failed
verification, mobile overflow and unavailable-storage cases.

These are UI/fixture checks, not live-provider or installer conformance tests.
