# DAF web Mission Control

Mission Control brings GitHub planning and HomeCI validation into one read-only browser workspace. It runs separately from the Python preview and Electron desktop application.

## Run locally

From the repository root with Node 24 or newer:

```sh
node web/server.mjs
```

Open `http://127.0.0.1:8080`. The default setup reads DAF's public GitHub issues, milestones, PRs, pinned M1.2 proposal and Actions runs and jobs. A repository can legitimately return zero GitHub milestones. Pinned DAF proposals have their own section because they come from a plan file at a specific commit.

The Docker example publishes to IPv4 loopback and requires viewer authentication for every repository configuration. With Docker Engine 28+ and Compose v2, set `DAF_VIEWER_PASSWORD_SOURCE` to the absolute path of a private password file outside the repository, readable by container UID 1000. Run `docker compose up --build --wait` from `web/` and open `http://127.0.0.1:18080` using the `daf` viewer account. For access from another machine, follow the [deployment and rollback procedure](docs/deployment.md).

## Configure sources

`DAF_REPOSITORIES_FILE` points to a private JSON file that replaces the defaults. Entries explicitly allow each `owner/name` and declare its `visibility` as `public` or `private`. `planning: true` enables milestones, issues and PRs. An optional `plan` gives a full lowercase `commit` SHA and a repository-relative JSON `path`. Actions reads are enabled for every listed repository, including CI-only entries. An empty list disables GitHub reads.

```json
[
  {"repository":"example/public-project","visibility":"public","planning":true},
  {"repository":"example/private-validation","visibility":"private","planning":false}
]
```

The server requires `DAF_VIEWER_PASSWORD_FILE` on a wildcard listener or when any private source is configured. Compose sets this path from its mandatory secret. With a password configured, the service challenges every read route except `/healthz` with HTTP Basic authentication for username `daf`. Use a randomly generated password of at least 24 printable non-space ASCII characters and terminate TLS at the trusted proxy before accepting viewer traffic. Use this local HTTP setup only over loopback. Anyone who can authenticate can see all configured repositories. Leave `DAF_GITHUB_TOKEN_FILE` unset to show a credential-missing state without making any requests to private repositories.

Private CI needs a separately provisioned, expiring fine-grained GitHub token restricted to selected repositories, with Metadata and Actions read access. Enable Issues and Pull requests read only where planning is needed, and Contents read for a pinned plan. The app sends the token only to explicitly private entries and never to public entries, browser requests or logs. The operator must verify the scopes and rotate credentials. [GitHub fine-grained token permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens)

## What the UI shows

- **Dashboard** shows configured repositories, recent PRs and validation, source problems, open issues and Product decisions surfaced from open issues labelled `product decision`, `product-decision`, `decision required` or `decision-required`.
- **Development** shows GitHub milestones, pinned proposal summaries, issues, PRs and recent validation evidence. Proposal text is a claim from a GitHub file. The app does not interpret it as approval or verify requirements listed in it.
- **HomeCI** shows four recent runs per repository and up to twenty jobs per exact run attempt. The job's runner name and self-hosted label are GitHub observations. Live runner health is unknown. Workflow, commit, job log and artifacts links go directly to GitHub. Artifacts may be missing, expired or require GitHub access. Retained evidence is the link and its provenance, not a copy of the artifact or log.

The app reads the first twelve items per planning endpoint. GitHub returns issues and PRs together on the issues endpoint, so the visible issue list can be shorter. Source observations show their own timestamps. Old completed jobs can still be valid historical records. The browser checks the server every five minutes while visible. The server shares one refresh across viewers and caches results for five minutes with private-only sources, or fifteen minutes per public source to stay within GitHub's anonymous API budget. On a refresh failure it can serve stale data in memory for up to 24 hours. Authentication and access failures clear the affected source. Browser disconnects mark the last received data stale. Restarting the service clears the server's cache.

## Validate

```sh
node --test web/tests/server.test.mjs
npm ci --prefix desktop --ignore-scripts --no-fund
npx --prefix desktop playwright install chromium
node --test web/tests/browser.test.mjs
```

The browser tests reuse the desktop lockfile's Playwright dependency. Use `DAF_WEB_BROWSER_CHANNEL=msedge` to run against installed Microsoft Edge. To capture public data with the optional live browser test, start the public default server and set `DAF_WEB_LIVE_URL` to its loopback origin and `DAF_WEB_SCREENSHOTS` to your output directory before running the browser suite. Capture public evidence only.
