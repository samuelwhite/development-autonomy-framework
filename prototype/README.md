# DAF v0.2 offline UI prototype

Double-click `index.html` in a current browser on Windows or Linux. No install,
server, account, real project access or credentials. All connections, tasks,
approvals, checks and usage are **simulated**. The source ZIP contains this folder;
the v0.1 Python packages do not.

Read [the Product proposal](../docs/v0.2-product-proposal.md) for the proposed journey,
integration research, limitations and implementation sequence.

Follow the [complete short walkthrough with screenshots](../docs/v0.2-ux-walkthrough.md).
For Product review, try:

1. Choose Codex or Claude (no default), try its demo connection, pick an example
   project, and keep **Just give me suggestions**. Checks happen automatically.
2. Choose a suggested task and **Start example task**. Watch progress and read
   Results; documentation, review and planning each have a different prepared result.
3. Choose **Make changes, but ask me first** with the documentation task: allow
   the example change once, or decline and stop. Review and planning never edit.
4. **Explore a setup problem** on the permissions screen: Retry alone still fails;
   the explicit **Fix this** action changes the relevant setting and rechecks it.
   **Explore a task problem** on the starter screen offers failed result checks,
   budget refusal and interrupted connections.
5. Stop while running or waiting for approval. Nothing resumes automatically.
6. Reload during active work: **Check earlier work** inspects the same attempt.
   Unknown outcomes keep their allowance and block Start over. Settings →
   **Explore demo problems** also demonstrates time expiry and failed recovery.

State is tab-scoped, best-effort session storage, never authority. The demo displays
custom task text but uses the labelled sample documentation result for that option.
There is no background execution, notification or durable recovery. **Start over**
clears this tab's history after work stops; older prototype storage resets to welcome.
The v0.1 engine, journals, stop gate and ledger are untouched.

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
