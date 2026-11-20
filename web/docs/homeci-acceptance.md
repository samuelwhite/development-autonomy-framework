# Forge-HomeCI operator acceptance

UI-02 builds on UI-01. Obtain separate owner acceptance of PR #18 before integration into main and separate approval before rollout on Jarvis. Use the [private hosting and rollback procedure](deployment.md). Verify the site is restricted to the intended private networks, viewer authentication covers the page, assets and API, and an outside client is denied at ingress before connecting any private feed.

## Configure the feed

In the private operator repository list, keep the existing DAF entry and append the following CI-only entry. This is an operator template, and the private feed is disabled by default.

```json
{"repository":"samuelwhite/Forge-HomeCI","visibility":"private","planning":false}
```

Provision a dedicated, expiring fine-grained GitHub personal access token with only Forge-HomeCI selected and Actions read plus the required Metadata read permission. Keep it separate from viewer authentication. Place the token and repository list in individual private read-only mounts accessible to container UID 1000. Point `DAF_REPOSITORIES_FILE` and `DAF_GITHUB_TOKEN_FILE` at their mounted paths in the private Compose override. Keep `DAF_VIEWER_PASSWORD_SOURCE` configured. The GitHub token stays server-side and is sent only for explicitly private entries. For this deployment, list only Forge-HomeCI as a private repository so its dedicated token is used only for that feed. Omit the token to test the unconfigured state without making a private API request. [GitHub fine-grained permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens)

## One real smoke observation

1. With explicit operator approval, use GitHub to manually start an existing, approved Forge-HomeCI smoke workflow on the already registered HomeCI runner. Record the workflow link and exact commit, run ID and attempt in private evidence. DAF has no dispatch route.
2. Open DAF as an authenticated viewer and select HomeCI. Wait for the next server fetch window if necessary, then refresh. A mixed configuration with one anonymous public repository can cache the snapshot for up to fifteen minutes.
3. Match the run, attempt, 40-character commit, conclusion and timestamp to GitHub. Expand jobs and verify job IDs, outcomes, log and artifact links where available, and the historical runner identity. Runner health should remain unknown. Preserve a failure as reported by GitHub. A previous failure can be used to check the failure view without starting an additional run.
4. Verify the unconfigured and inaccessible cases in an isolated operator configuration or the automated tests. Keep private logs, identifiers, screenshots and receipts in private operator records. Public review screenshots use public DAF only.

## Roll back the feed

Restore the prior private repository list, remove the GitHub-token mount and environment setting from the override, and recreate only Mission Control using the approved operator procedure. Verify authentication and public data, and revoke the dedicated token if retiring it. No runner, workflow or HomeCI host change is required.
