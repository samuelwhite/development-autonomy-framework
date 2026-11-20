# Local accounts rollout

Keep Basic Auth on the current deployment until the UI-03 candidate is independently verified through HTTPS. Review and accept UI-01 and UI-02 first. Account administration covers sign-in only. GitHub and HomeCI remain read-only.

## Stage beside the current deployment

Use one container per account database. Prepare a dedicated host directory outside the checkout with mode `0700`, owned by the app UID/GID 1000. Back up the existing Compose files, Basic viewer secret, image identity and ingress settings through the private operator procedure.

Use a separate, approved Compose project, an unused IPv4 loopback port and a verified private HTTPS test hostname. Set these variables in the private operator shell or environment file. The paths and origin contain no credentials.

- `DAF_AUTH_STATE_SOURCE` points to the dedicated host directory.
- `DAF_PUBLIC_ORIGIN` is the exact HTTPS origin, without a trailing slash. Forward `Origin` and cookies through the trusted proxy without rewriting them. The app accepts mutating requests only from this configured origin and does not infer it from request headers.
- `DAF_PUBLISHED_PORT` is the staged project's verified loopback port.
- `DAF_VIEWER_PASSWORD_SOURCE` remains defined for the base Compose interpolation and emergency rollback. The accounts override removes the legacy secret mount.

Use a current Compose v2 that supports the `!reset` override and validate the combined configuration. From `web/`, substitute the approved project name for `daf-accounts-check`. The following example builds the candidate and starts a one-off bootstrap container without publishing service ports.

```sh
docker compose -p daf-accounts-check -f compose.yaml -f compose.accounts.yaml config --quiet
docker compose -p daf-accounts-check -f compose.yaml -f compose.accounts.yaml build
docker compose -p daf-accounts-check -f compose.yaml -f compose.accounts.yaml \
  run --rm --no-deps mission-control node bootstrap.mjs
docker compose -p daf-accounts-check -f compose.yaml -f compose.accounts.yaml up --wait --no-build
```

Enter the administrator username and password in a private interactive terminal. Password entry is hidden. Bootstrap refuses noninteractive input and an existing database. Supply a unique passphrase, for example 15 or more characters. The product minimum is 10 characters. The maximum is 256 Unicode characters. There are no composition rules and the application checks common breached and context-derived passwords locally.

The staged project uses the same read-only image, loopback publishing, non-root UID, dropped capabilities and resource limits. Only the dedicated account state directory is writable. Verify outside-LAN and outside-tailnet denial before adding a private GitHub feed. The GitHub token remains a separate server-side read-only mount. [Forge-HomeCI acceptance](homeci-acceptance.md)

## Verify before cutover

1. Confirm a fresh anonymous HTTPS browser is sent to sign-in and that a direct anonymous feed request returns HTTP 401. Sign in as the first administrator. Confirm the domain-scoped `__Host-daf_session` cookie is Secure, HttpOnly and SameSite Strict, and HTTPS forwarding passes the canonical origin. The cookie has no Domain attribute and expires after 24 hours.
2. Create a Viewer, sign in as that viewer in a separate browser, confirm Settings is hidden and direct administration requests return HTTP 403. Change the viewer password, then verify their old session and password fail. Reset and disable a test viewer and confirm session revocation, safe re-enabling and last-admin protection.
3. Restart only the staged container. Verify both accounts, a retained valid session and continued rejection of revoked sessions. Exercise wrong-password and cross-site requests. Check the old Basic-authenticated instance is still healthy. Capture results privately.
4. Obtain owner acceptance before routing the intended private HTTPS origin to accounts mode. Recheck the origin, TLS, network controls, sign-in and dashboard. Keep the former image and Basic secret ready for rollback. Never route to an anonymous listener.

## Backup, restore and rollback

Use a cold backup. Stop the accounts container before copying its private state directory with permissions retained. Protect the backup as credential material. For a restore, stage and check a copy privately while the affected project is stopped. Revoke sessions in the restored directory before serving it, since a backup can contain sessions that were later invalidated:

```sh
docker compose -p daf-accounts-check -f compose.yaml -f compose.accounts.yaml \
  run --rm --no-deps mission-control node bootstrap.mjs --revoke-sessions
```

Type the requested confirmation in the trusted terminal. Verify restored administrator access and that old sessions fail. Roll back by restoring the previous Basic-authenticated upstream or restarting the approved prior image with only the base Compose configuration and original Basic secret. Check anonymous HTTP 401 and authenticated dashboard access. Keep account state private for recovery. Do not delete it during rollback.

## Security notes

Passwords are individually salted with Node's scrypt at N=32768, r=8, p=3. Two hashes can run concurrently within the existing memory limit. Sessions store only a digest of the random cookie value. Logout, password change/reset, disabling a user and restoring a backup revoke affected sessions. The server uses a username limit and a process-wide limit that do not rely on proxy IP headers. Rate-limit counters reset on process restart. SQLite transactions persist users and revocations and reject an invalid or uninitialised store. Use a local filesystem, never a network-shared volume. [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)

The offline blocklist is a filtered, normalised SHA-256 set derived from the 100,000-entry Xato file in SecLists at commit `1a89b46c204032247592a1626e29f841cb0fe2a5`, with the upstream MIT notice included. It covers common breached passwords at the supported length. It does not provide complete breach coverage and never sends passwords to a third party. [Pinned list](https://github.com/danielmiessler/SecLists/blob/1a89b46c204032247592a1626e29f841cb0fe2a5/Passwords/Common-Credentials/xato-net-10-million-passwords-100000.txt)
