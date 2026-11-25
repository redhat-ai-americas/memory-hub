# Role resolution: cluster verification

Phase 1 of [`human-role-resolution.md`](human-role-resolution.md) (#744).
The design depends on platform behaviour that only a live cluster can
confirm. This page lists what to check, how, and records the results.

Status: **pending a run on `mcp-rhoai`.** The results tables below are
empty until then. Until they are filled in, `MEMORYHUB_UI_RBAC_CHECK`
stays at its default (`self`) only because the design prefers it; if the
run shows `self` does not work, deploy with `delegated`.

## A. Platform behaviour (script)

```bash
memoryhub-ui/deploy/verify-role-resolution.sh --context mcp-rhoai
```

Needs `oc` logged in as cluster-admin. The script creates a scratch
namespace, scratch Roles, a scratch Group and a short-lived OAuth token
scoped like oauth-proxy's (`user:info user:check-access`), and removes all
of them on exit. It never prints the token.

| # | Question | Decides |
|---|---|---|
| 1 | Can a scoped token read `users/~` and get an unrestricted `SelfSubjectAccessReview` answer for `memoryhub.io/dashboard`? | `self` vs `delegated` mode |
| 2 | Does `TokenReview` return the person's groups; does a `SubjectAccessReview` without groups miss group bindings? | delegated mode and the auth refresh re-check must resolve groups |
| 3 | Does removing a person from a `Group` affect a token that already exists? | revocation timing for direct Group changes |
| 4 | Does deleting a RoleBinding affect an existing token? | revocation timing for bindings |
| 5 | Does cluster-admin pass the `admin` verb? | #744 semantics |

Results (paste the script's table here):

| Check | Result | Expected |
|---|---|---|
| _not run yet_ | | |

## B. Dashboard end to end (deployed)

Deploy the branch with `MEMORYHUB_UI_ROLE_SOURCE=openshift-rbac`, then:

| # | Step | Expected | Result |
|---|---|---|---|
| B1 | Sign in as a member of a group bound to `memoryhub-dashboard-user` | dashboard opens, `/api/me` role `user` | |
| B2 | Same person, binding moved to `memoryhub-dashboard-admin` | role `admin` within 30 s, no restart | |
| B3 | Delete the binding while the session is open | `403` within 30 s | |
| B4 | Person with no binding signs in | proxy refuses (`--openshift-sar`) before the BFF; BFF log shows nothing for them | |
| B5 | `curl` the pod port 8080 directly with forged `X-Forwarded-User` | `401` (not loopback) | |
| B6 | Scale the API out of reach (NetworkPolicy deny egress to API) | `503`, never an allow | |
| B7 | cluster-admin signs in | role `admin`, still no personal data visible | |
| B8 | Pod logs | no `X-Forwarded-Access-Token` value or bearer token anywhere | |
| B9 | `--openshift-sar` key `resourceAPIGroup` | proxy honours the API group (B4 passes and B1 is not refused) | |

## C. Broker and refresh (memoryhub-auth)

Deploy with `AUTH_ENTITLEMENT_MODE=openshift-rbac`:

| # | Step | Expected | Result |
|---|---|---|---|
| C1 | `tests/integration/test_pkce_e2e.py` as an entitled user | passes | |
| C2 | Same with an unentitled user | `access_denied` at the callback | |
| C3 | Refresh after the person's binding is deleted | `401 invalid_grant`; token not rotated; works again after re-granting | |
| C4 | Refresh with the API unreachable | `503 temporarily_unavailable`, no new tokens | |
| C5 | `client_credentials` for a personal agent whose owner lost access | refused; client still exists | |
| C6 | `client_credentials` for a service agent | unaffected | |

## Decisions taken from the run

Record here which mode was chosen and why, with the date and the cluster
version.
