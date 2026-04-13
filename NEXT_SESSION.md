# Next session: Enforce allowed_group + deploy TLS hardening (#179)

## What was completed (2026-04-13)

- Merged `feat/pkce-broker-flow` (14 commits) to main
- Shipped Playwright e2e test for the full PKCE broker flow (#81)
- Fixed deployment bugs discovered by e2e: wrong user-info URL, missing TLS config, IDP selection
- Hardened deployment: internal service URLs, combined CA bundle, TLS verification re-enabled, cluster-specific URLs derived dynamically by `deploy.sh`

## Deploy the TLS hardening

The `openshift.yaml` and `deploy.sh` changes from this session have NOT been deployed yet (committed but not applied to the cluster). They introduce:

- `service-ca-bundle` ConfigMap with CA injection annotation
- Init container that combines cluster CA + service CA into a single bundle
- Internal service URLs for token exchange and user-info (cluster-generic)
- Placeholder substitution in `deploy.sh` for cluster-specific URLs (AUTH_ISSUER, OAuth authorize URL)

To deploy:
```bash
cd memoryhub-auth && ./deploy.sh
```

After deploy, re-run the e2e test to verify TLS hardening didn't break the flow:
```bash
pytest memoryhub-auth/tests/integration/test_pkce_e2e.py -v --timeout=60
```

## #179: Enforce `openshift_allowed_group`

The `openshift_allowed_group` config field exists in `src/config.py` but is never checked. Anyone who can log into OpenShift gets a MemoryHub JWT. This is the natural follow-up to the PKCE broker — the auth plumbing is proven end-to-end.

### What to implement

In `src/routes/openshift_callback.py`, after `_resolve_openshift_user()` returns the username:
1. If `settings.openshift_allowed_group` is non-empty, call the OpenShift Groups API to check membership
2. Reject with 403 if the user isn't in the group
3. The Groups API is at `https://kubernetes.default.svc/apis/user.openshift.io/v1/groups/{group_name}` — check if the user is in `.users[]`

### Design considerations

- The group check uses the user's opaque token (same one used for user-info), so no extra auth needed
- Consider caching group membership briefly (groups don't change often)
- Add unit tests that mock the group API call
- Update the e2e test to verify the group check (if the test user is in the group)

## #176: Multi-user usage tracking

The PKCE flow was the prerequisite. Now that browser-based users get per-user JWTs with `sub=<username>`, usage can be tracked per-user. This is a larger effort — scope it before starting.

## Retro

Run `/retro` to capture lessons from this session:
- E2e tests against the real cluster are the only way to validate the OAuth redirect chain
- Three deployment bugs (wrong user-info URL, IDP selection, TLS config) were invisible to unit tests
- Internal service URLs (`kubernetes.default.svc`, `oauth-openshift.openshift-authentication.svc`) are portable across clusters; external Route URLs are not

## Cluster state

- Auth server: `auth-server` in `memoryhub-auth` (Running, TLS verify currently disabled via env override — deploy.sh run will fix)
- OAuthClient CR: `memoryhub-auth-broker` (grantMethod=prompt)
- DB: `memoryhub-pg-0` in `memoryhub-db`, Alembic at revision 001
- MCP: `memory-hub-mcp` in `memory-hub-mcp` (Running)
- e2e test client: `e2e-test` (public, registered via admin API)
