# Build & Deploy Hardening

How MemoryHub components build, push, and roll out container images on OpenShift -- and the failure modes that have repeatedly bitten the project.

**Status: shipped (#88 closed 2026-04-08).** Captures the failure family identified across retros #9, #12, #14, and #18 (2026-04-06 through 2026-04-07) and the project-wide template every component now satisfies. The Phase 2 fixes landed in the same session that landed this doc; the Component status table at the bottom shows the post-fix state.

## Why this exists

Across four retros in two days, the project hit four distinct manifestations of the same root problem: **a deploy script reports success but the running pod is still on old code.** Each retro proposed a partial fix (`noCache: true`, `ImageChange` trigger, manifest re-apply, rollout restart, digest unpinning). None of them generalized across components, so the next deploy of a different component hit the same family of bugs in a new form.

This doc establishes the project-wide pattern that all MemoryHub components (mcp-server, ui, future operator, future curator) must follow, so the failure family closes once instead of being re-discovered per component.

## The failure family

### Manifestation 1 -- BuildConfig caching (Retro #9, dashboard-memory-graph)

**Symptom:** Source files change, `oc start-build` runs, build "succeeds," pod restarts, old code is still running. Required 3+ redeploys per session to land changes.

**Cause:** BuildConfig had no `noCache: true`, so layer caching reused stale layers from prior builds even when source changed.

**Fix proposed:** Add `noCache: true` to all BuildConfigs.

### Manifestation 2 -- Missing rollout trigger (Retro #12, rbac-enforcement)

**Symptom:** Build completes with new image pushed to imagestream. `:latest` tag updates. Existing pod keeps running old image because nothing tells the Deployment to roll.

**Cause:** Deployment lacked an `ImageChange` trigger. `oc start-build` doesn't restart deployments by itself.

**Fix proposed:** Add `ImageChange` trigger to Deployment, OR explicit `oc rollout restart` step in the deploy script.

### Manifestation 3 -- Image-resolution race (Retro #14, wave1-4-mcp-fixes)

**Symptom:** Build pushes new image. Deploy script immediately runs `oc rollout restart`. New pod comes up on the *previous* digest because the `:latest` imagestream tag hasn't propagated yet.

**Cause:** Race between build completion and imagestream tag update. `oc start-build --follow` returns when the build is done, not when the tag is fully resolved by the cluster.

**Fix proposed:** Re-apply the Deployment manifest (`oc apply -f openshift.yaml`) after `--follow` returns, before `oc rollout restart`. This forces the cluster to re-resolve the imagestream tag.

### Manifestation 4 -- Stale digest in live spec via resolve-names (Retro #18, concept-close-doc-refresh-and-55)

**Symptom:** UI deploy script runs cleanly. `oc rollout restart` runs. New pod comes up on a 23-hour-old image. `oc get deploy -o yaml` reveals the image is pinned to a specific `@sha256:...` digest, not the imagestream tag.

**Cause:** The *manifest* uses `image: memoryhub-ui:latest`, but the Deployment carries the `alpha.image.policy.openshift.io/resolve-names: '*'` annotation. OpenShift rewrites the tag to a concrete digest at apply time, then never re-resolves on its own. When `oc apply -f openshift.yaml` runs *before* `oc start-build`, the live spec gets pinned to whatever `:latest` pointed at *before* the build. `rollout restart` then re-creates the pod on that stale digest.

This is the same root mechanism as Manifestation 3 -- the resolve-names annotation, not a hard-coded digest in source. The two manifestations differ only in how the staleness becomes visible: #3 was caught mid-session because the new digest was minutes old; #4 went unnoticed for 23 hours.

**Fix proposed:** Use `imagestream:latest` with `imagePullPolicy: Always` in all Deployment specs (already true across components -- this is a discipline to preserve, not a fix to apply), and **re-apply the manifest after `oc start-build --follow` returns** so the resolve-names annotation re-resolves to the just-pushed digest. Originally tracked as **#83**; now subsumed by this issue.

## The project-wide template

Every MemoryHub component's BuildConfig + Deployment + deploy script must satisfy all of the following:

### BuildConfig

- `spec.strategy.dockerStrategy.noCache: true` (or `spec.strategy.<type>.noCache: true` for other strategies)
- `spec.output.to.kind: ImageStreamTag` pushing to a project-local imagestream
- `spec.runPolicy: Serial` (prevents concurrent builds clobbering each other)

### Deployment

- `spec.template.spec.containers[].image` references the imagestream tag, **never** a `@sha256:` digest:
  ```yaml
  image: image-registry.openshift-image-registry.svc:5000/<namespace>/<imagestream>:latest
  ```
- `spec.template.spec.containers[].imagePullPolicy: Always`
- An `image.openshift.io/triggers` annotation OR an explicit `oc rollout restart` step in the deploy script (one or the other; both is fine but redundant)

### Deploy script

After `oc start-build --follow` returns:

1. **Re-apply the Deployment manifest** -- forces re-resolution of the imagestream tag against the just-pushed image:
   ```bash
   oc apply -f deploy/openshift.yaml -n <namespace>
   ```
2. **Rollout restart** -- triggers a new pod even if the manifest didn't change:
   ```bash
   oc rollout restart deployment/<name> -n <namespace>
   ```
3. **Wait for rollout** -- fail loudly if the new pod doesn't come up:
   ```bash
   oc rollout status deployment/<name> -n <namespace> --timeout=180s
   ```
4. **Verify the running image** -- diff the actual running digest against the imagestream's current `:latest`:
   ```bash
   RUNNING=$(oc get deploy/<name> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].image}')
   LATEST_DIGEST=$(oc get is/<imagestream> -n <namespace> -o jsonpath='{.status.tags[?(@.tag=="latest")].items[0].image}')
   echo "Running: $RUNNING"
   echo "Latest:  $LATEST_DIGEST"
   ```
   If the script can resolve `RUNNING` to a digest, assert it matches `LATEST_DIGEST`. Fail the script otherwise.
5. **Tool-count regression check** (MCP servers only) -- two halves, both required:

   - **Static preflight, in the deploy script.** Before the build runs, parse `src/main.py` and the `src/tools/` directory to assert that every tool file is imported AND added to `mcp.add_tool(...)`. Catches the registration silent-failure class (file ships but is not registered, no error in pod logs). Landed in `65bca6c`. Lives in `deploy.sh` because it's pure source-side static analysis. Must remain in every MCP deploy script.
   - **Runtime check, operator-side.** After the deploy script completes, the operator runs `mcp-test-mcp` against the deployed route to assert the expected tool count and spot-check at least one tool. This catches runtime issues the static check can't see: build context missing files, runtime decoration errors, dependency import failures, JWT auth misconfiguration. The deploy script can't shell out to `mcp-test-mcp` because `mcp-test-mcp` is itself an MCP server (not a CLI), so the runtime check lives in the operator's slash-command workflow rather than the bash script. The `/deploy-mcp` slash command's Step 4 ("Verify deployed tools with mcp-test-mcp") is the canonical operator-side equivalent and MUST be run after every memory-hub-mcp deploy.
6. **Healthz check** -- existing pattern, keep it.

## Audit checklist

Apply this to every existing component (mcp-server, ui, auth, future operator, future curator):

- [ ] BuildConfig has `noCache: true`
- [ ] BuildConfig has `runPolicy: Serial`
- [ ] Deployment uses imagestream tag, not pinned digest
- [ ] Deployment has `imagePullPolicy: Always`
- [ ] Deploy script re-applies manifest after `--follow`
- [ ] Deploy script does `rollout restart` + `rollout status`
- [ ] Deploy script verifies running digest == imagestream `:latest` digest
- [ ] (MCP only) Deploy script runs static-preflight tool-count check (registration silent-failure)
- [ ] (MCP only) Operator runs `mcp-test-mcp` post-deploy (runtime registration check)
- [ ] Deploy script returns non-zero on any verification failure

## Component status

Audit completed 2026-04-08 as part of #88 Phase 1; Phase 2 fixes shipped and validated by real deploys the same day. Per-cell status:

| Component | BuildConfig | Deployment | Deploy script |
|---|---|---|---|
| memory-hub-mcp | OK — `noCache: true` and `runPolicy: Serial` set | OK — imagestream tag, `imagePullPolicy: Always`, `resolve-names` annotation, `app.kubernetes.io/name` label on Deployment metadata | OK — re-apply, `rollout restart`, `rollout status`, hardened deploy-state checks (fail non-zero), running-digest verification, static-preflight tool-count check; runtime tool-count check is operator-side via `mcp-test-mcp` per `/deploy-mcp` Step 4 |
| memoryhub-ui | OK — `noCache: true` and `runPolicy: Serial` set | OK — imagestream tag in manifest, `imagePullPolicy: Always`, `resolve-names` annotation; oauth-proxy sidecar uses an external image with `IfNotPresent` (intentional, not under #88 scope) | OK — re-apply after `--follow`, `rollout restart`, `rollout status`, running-digest verification |
| memoryhub-auth | OK — `noCache: true` and `runPolicy: Serial` set | OK — imagestream tag (sed-rewritten to fully-qualified registry path by deploy script), `imagePullPolicy: Always`, `resolve-names` annotation; placeholder Secret stanzas removed and now managed entirely out-of-band by deploy script | OK — re-apply after `--follow`, `rollout restart`, `rollout status`, running-digest verification AFTER both rollouts (initial restart + AUTH_ISSUER env-set); the broken `grep | awk` filter that was silently producing malformed Deployment manifests was removed during Phase 2 |

#88 closed 2026-04-08. The umbrella issue subsumed #83 (`memoryhub-ui` deploy script gotcha), which closed as part of the same Phase 2 ship.

## Out of scope for this doc

- ArgoCD / GitOps migration -- separate future effort
- Tekton pipelines -- separate future effort
- ImageChange triggers via the operator (vs explicit script step) -- the operator can adopt this pattern when it builds its reconciler; the doc just specifies the contract

## Related

- **#83** -- memoryhub-ui deploy script (manifestation 4)
- Retro #9 (`retrospectives/2026-04-06_dashboard-memory-graph/`) -- manifestation 1
- Retro #12 (`retrospectives/2026-04-07_rbac-enforcement/`) -- manifestation 2
- Retro #14 (`retrospectives/2026-04-07_wave1-4-mcp-fixes/`) -- manifestation 3
- Retro #18 (`retrospectives/2026-04-07_concept-close-doc-refresh-and-55/`) -- manifestation 4
- `../planning/operator.md` -- the future operator will adopt this contract
