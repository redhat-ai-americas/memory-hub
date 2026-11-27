# Redesigned User/Admin UI — live verification

Date: 2026-11-23. Branch: `ui-admin-user-roles`. Application source: `0f215c3`.

Status: **PASSED for the workflows below, with the credential-revocation limitation explicitly recorded.** The review, fixes, build, and deployment use the `memory-hub-ui-admin-user-roles` checkout. The `backend-admin-user-roles` branch remains at `1e9b051`; this deployment updates the UI/BFF image from the UI branch.

## Environment and method

- OpenShift API: `https://api.ocp.4nvv6.sandbox2317.opentlc.com:6443`.
- Primary UI: <https://memoryhub-ui-memoryhub-ui.apps.ocp.4nvv6.sandbox2317.opentlc.com/>.
- RHOAI launch route: <https://memoryhub-ui-redhat-ods-applications.apps.ocp.4nvv6.sandbox2317.opentlc.com/>.
- Existing Auth, MCP, PostgreSQL/pgvector, Valkey, MinIO, CPU embedding/reranking models, and RHOAI dashboard remain installed.

Two temporary accounts in the existing Keycloak provider sign in through real OpenShift OAuth. Their roles are assigned by the existing human ACL provisioning script. Browser checks call the deployed BFF, Auth, PostgreSQL, and embedding service; no API responses or authentication dependencies are replaced. An isolated entity fixture is inserted into PostgreSQL to exercise entity projections without an extraction LLM.

## Findings and fixes

### Review actions could not be inferred from redacted authors

The deployed redesigned UI showed **Mark resolved** on a report about the Admin's own project memory. All author fields were correctly null. Clicking the button returned 403 from the existing self-review guard.

The BFF now publishes `can_resolve` on each contradiction report. The list uses its existing authorized memory join to calculate this capability without revealing authors or issuing per-report queries. Mutation and projection share `Access.can_resolve_report`, including human and owned-agent aliases. The UI uses this capability instead of reconstructing permissions from identities. Personal memories remain excluded, and report authors remain redacted.

### Admin search exposed an unsupported owner filter

Search is reachable by direct link for Admin. Its owner selector offered individual filtering that the BFF refuses. The UI now omits both the selector and the `identity` request field when individual activity is unavailable, and does not load the identity directory for that screen.

### Credential deactivation messages promised unsupported revocation

The UI promised that tokens and MCP sessions would stop within five seconds. A real UI-created client disproved that claim: more than seven seconds after deactivation, new token issuance returned 401, but an issued JWT and an existing API-key session could still read memory; a new registration using the cached API key also succeeded.

The running MCP implementation caches remote API-key validation for 300 seconds and does not revoke issued JWTs or existing sessions when Auth marks a client inactive. UI confirmation, rotation, and success messages now describe that behavior accurately. **This change does not implement immediate credential/session revocation in MCP.** That remains a security capability requiring separate work if immediate revocation is a deployment requirement. Active sessions may extend their inactivity expiry.

### Privacy, rule, and agent descriptions were stale

Admin pages claimed personal memories appeared as metadata or contributed to counts; the BFF excludes them entirely. These labels now describe exclusion. `reject_with_pointer` was incorrectly labelled **Route to project**; it now reads **Reject with reference**. Personal rule descriptions follow the rule owner's identity, and agent screens describe independent client scopes and project memberships rather than automatic inheritance from the human owner.

## Validation

| Check | Result |
| --- | --- |
| BFF tests without PostgreSQL | 212 passed. |
| PostgreSQL privacy/integration tests | 5 passed, no skips; includes read capability versus mutation parity for independent reports, own memories, and own reports. |
| Browser regression tests | 19 passed, one intentionally skipped menu case; includes direct Admin search and credential lifetime messaging. |
| TypeScript and production frontend build | Passed. |
| Ruff and Git whitespace checks | Passed. |
| Real OAuth login | Distinct User and Admin menus and server capabilities, including entry through the RHOAI route. |
| User personal memory | Created through the UI; searchable and readable by User. Admin list, graph, counts, and attribution exclude the private record. |
| Project membership | Admin creates an invite-only project and adds User through the UI's member picker. Shared writes and reads succeed. |
| OAuth client and MCP | User creates a client in the UI. Its real credentials obtain a token and register/write/read through FastMCP. The bound human owner reads the agent's personal memory. |
| Client deactivation | UI updates the client to inactive; new token issuance returns 401. Existing token/session/cache behavior is explicitly documented above. |
| Personal rule | Created and edited through the UI, producing version 2; absent from the Admin's rule list. |
| Entities | Authorized User sees exactly two mention sources and zero hidden mentions, renames the entity through the UI, and the old name becomes an alias. |
| Final fixed review/search screens | On the selected image, own-memory and own-report capabilities are false and no resolve buttons appear. An independent report resolves successfully through the UI with its author still redacted. Admin search has no owner selector, runs successfully, and exposes neither personal nor agent-private canaries. |
| Memory detail and graph | User opens personal memory; Admin opens shared memory with redacted author fields. The final graph renders, carries the corrected privacy label, and excludes personal canaries. No console errors were observed in the final User/Admin screens. |

The GitHub run also exposed a race in the human-access script's test stub: both sides of `oc create --dry-run | oc apply` accessed a partially written shared JSON file. The stub now emits its dry-run manifest through the pipe and persists it only in `apply`, matching the real command sequence. This test-only correction does not change the deployed application or deployment script.

## Selected deployment

- Selected OpenShift build: `memoryhub-ui-7`, annotated with source commit `0f215c3`.
- UI/BFF image: `sha256:40cb254b8298f24399e09f027f34fc3947e01c2358ec6c38fde7b581aa35b625`.
- Deployment ready with one available replica; image matches the ImageStream's selected digest.
- SHA-256 comparisons: all three changed BFF modules in the running container match the committed source, and all ten compiled frontend assets match the local production build byte for byte.
- Primary and RHOAI routes run the redesigned UI through the OAuth proxy. Only the UI/BFF Deployment is updated; Auth and MCP images are unchanged.

## Cleanup and limits

Temporary QA accounts, OAuth tokens/authorizations, client, project, memories, entity, rules, and database fixtures were removed after verification. Final QA memory/client/rule/project counts are all zero. The QA entries were removed from the human ACL while preserving other entries, and the UI was restarted to apply it. The normal Admin `admin` remains authorized.

This checks the principal UI workflows and their backend permission boundaries. It does not claim immediate MCP credential revocation, load/failover testing, backup restoration, or validation of every possible rule configuration and browser combination.
