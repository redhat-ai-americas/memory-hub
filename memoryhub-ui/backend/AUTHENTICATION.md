# Dashboard authentication

Local accounts use `MEMORYHUB_UI_LOCAL_ACCOUNTS=true`. Development API-key login uses `MEMORYHUB_UI_DEV_API_KEY`. Both modes ignore incoming `X-Forwarded-User`, `X-Forwarded-Preferred-Username`, `X-Forwarded-Email`, and `X-Forwarded-Groups` identity headers.

An OAuth-proxy deployment must explicitly set `MEMORYHUB_UI_TRUST_PROXY_HEADERS=true` and leave local accounts and development API-key login disabled. The proxy must replace client-supplied identity headers, and the backend must be reachable only through that trusted proxy. The OpenShift manifest enables this setting for its OAuth sidecar. Requests without a proxy identity are rejected in this mode.

With all three authentication settings disabled, the dashboard retains its existing open development mode.

## Upgrading local sessions

Migration `0004_account_sessions` adds `memoryhub_ui_accounts.session_version`. The standard startup migration applies it automatically. Deployments that manage migrations separately should run `alembic upgrade head` from this directory before serving the updated backend.

Existing local-account and development API-key cookies must sign in again after this update because the signed cookie format now includes a session version. Each local-account request checks the current tenant, account status, role, and session version in the database. Changing a role or status increments the version; re-enabling an account does not revive an earlier cookie.

## Incident access in the browser

The browser refreshes authorization every 15 seconds and on focus, visibility changes, and incident changes from another tab. At the grant's expiry time it immediately discards cached screen content, including when the network is unavailable. A changed identity, role, grant, or write capability remounts the screen with fresh requests. If authorization cannot be verified, the screen stays hidden until verification succeeds.
