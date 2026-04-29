# Provisioning an MCP API key in `memoryhub-users`

This runbook covers adding a new API key to the `memoryhub-users` ConfigMap so an external CI consumer or human operator can authenticate against the deployed MCP server via `register_session(api_key=...)`.

If you are looking for OAuth 2.1 `client_credentials` provisioning instead — used by SDK consumers and dashboards — see [`docs/auth/README.md`](../auth/README.md). API keys are the dev-path shim; OAuth is the durable mechanism. Both work today.

## When to use this

- Adding a new API key for an external CI test job (e.g., `kagenti-ci`) that needs to exercise the MCP server end-to-end.
- Adding a new operator user who should authenticate via the dev-path API key flow rather than OAuth.
- Rotating a compromised API key (delete the old entry, add a new one with a fresh key).

Do **not** use this for SDK consumers, dashboards, or anything that needs a refreshable JWT — those should go through `memoryhub-auth` and OAuth `client_credentials`.

## Where the data lives

| | |
|---|---|
| ConfigMap | `memoryhub-users` |
| Namespace | `memory-hub-mcp` |
| Cluster context | `mcp-rhoai` |
| Key inside ConfigMap | `users.json` |

The MCP server reads this ConfigMap at startup and on every `register_session` call. After you patch the ConfigMap, the running pod still has the old data cached — you must restart the deployment for the change to take effect.

## `users.json` shape

```json
{
  "users": [
    {
      "user_id": "kagenti-ci",
      "name": "Kagenti CI",
      "api_key": "mh-dev-<16 hex chars>",
      "scopes": ["user", "project"]
    }
  ]
}
```

Fields:

- `user_id` — short identifier. Used as the actor in audit logs. Lowercase, hyphen-separated.
- `name` — human-readable label. Shown in dashboards.
- `api_key` — bearer token. Format: `mh-dev-<16 hex chars>`. Generate with `openssl rand -hex 8` (16 hex chars = 8 bytes of entropy after the prefix).
- `scopes` — array of MemoryHub scopes the user is granted. Standard choices: `["user", "project"]` for CI test users; broader scopes (`["user", "project", "role", "organizational", "enterprise"]`) for full operators.

## Steps

Set context variables once so you do not paste the cluster + namespace into every command:

```bash
CTX=mcp-rhoai
NS=memory-hub-mcp
```

### 1. Generate the API key

```bash
NEW_KEY="mh-dev-$(openssl rand -hex 8)"
echo "$NEW_KEY"   # copy this — you cannot recover it later
```

The MCP server stores keys in the ConfigMap as plaintext (it is the source of truth). Treat the value the same as a database password: copy it once, hand it to the consumer over a secure channel, and do not commit it.

### 2. Read the current ConfigMap

```bash
oc get configmap memoryhub-users --context $CTX -n $NS -o json \
  | jq -r '.data["users.json"]' > /tmp/users.json

cat /tmp/users.json
```

Verify the existing user list looks sane before editing. If the ConfigMap is missing entirely, see [`memory-hub-mcp/deploy/users-configmap.example.yaml`](../../memory-hub-mcp/deploy/users-configmap.example.yaml) — that is the template the cluster install uses.

### 3. Merge in the new user

```bash
jq --arg key "$NEW_KEY" \
   --arg uid "kagenti-ci" \
   --arg name "Kagenti CI" \
   '.users += [{"user_id": $uid, "name": $name, "api_key": $key, "scopes": ["user", "project"]}]' \
   /tmp/users.json > /tmp/users.new.json

cat /tmp/users.new.json   # eyeball before applying
```

If you are rotating an existing key instead of adding a new user, replace the `+=` step with a `map` that updates the matching entry:

```bash
jq --arg key "$NEW_KEY" \
   --arg uid "kagenti-ci" \
   '.users |= map(if .user_id == $uid then .api_key = $key else . end)' \
   /tmp/users.json > /tmp/users.new.json
```

### 4. Patch the ConfigMap

```bash
oc create configmap memoryhub-users \
  --from-file=users.json=/tmp/users.new.json \
  --dry-run=client -o yaml \
  | oc apply --context $CTX -n $NS -f -
```

`oc create --dry-run` + `oc apply` is the idiomatic update pattern for ConfigMaps that wrap a single file.

### 5. Restart the MCP deployment

```bash
oc rollout restart deployment/memory-hub-mcp --context $CTX -n $NS
oc rollout status deployment/memory-hub-mcp --context $CTX -n $NS
```

Wait for `successfully rolled out` before testing.

### 6. Smoke test the new key

Get the public route once:

```bash
ROUTE=$(oc get route memory-hub-mcp --context $CTX -n $NS -o jsonpath='{.spec.host}')
echo "https://${ROUTE}/mcp/"
```

Then hit `initialize` with the new bearer token:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  -X POST "https://${ROUTE}/mcp/" \
  -H "Authorization: Bearer ${NEW_KEY}" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
```

Expected: `200`. Anything else means the rollout has not completed, the ConfigMap merge dropped the new entry, or the key was not formatted correctly.

A wrong/missing key returns `401`; a working key returns `200` and an SSE-style body. The body is not what we are testing here — we just want the HTTP status.

### 7. Hand off the key

Send the key to the consumer over a private channel (encrypted DM, password manager share, or the consumer's secret-management surface — e.g., GitHub repo secrets for `kagenti-ci`). Do not paste it into an issue, PR description, or chat that will end up archived publicly.

## Cleanup / rotation

To remove a user:

```bash
jq --arg uid "kagenti-ci" \
   '.users |= map(select(.user_id != $uid))' \
   /tmp/users.json > /tmp/users.new.json
```

Then re-run steps 4 and 5. The next `register_session(api_key=...)` call from the removed user returns `401`.

## Pitfalls

- **The pod caches.** Always rollout-restart after patching. A patched ConfigMap with no restart will silently look like the change was lost.
- **Plain `oc edit configmap` mangles the JSON.** The embedded `users.json` is a YAML literal block and is fragile to indentation drift. Use the jq + `oc create --dry-run | oc apply` pattern above; do not edit by hand.
- **Do not commit `users-configmap.yaml`.** Only the `*.example.yaml` template is checked in. The real ConfigMap with real keys is regenerated from the template + secrets at install time.
- **Cluster-scoped vs namespace-scoped.** The ConfigMap is namespaced. Make sure you have `--context $CTX -n $NS` on every command — leaving them off can target the wrong cluster or namespace.
