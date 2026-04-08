# Build & Deploy Hardening

How MemoryHub components build, push, and roll out container images on OpenShift -- and the failure modes that have repeatedly bitten the project.

**Status: skeleton.** Captures the failure family identified across retros #9, #12, #14, and #18 (2026-04-06 through 2026-04-07). Concrete remediation lives in the umbrella issue this doc references.

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

### Manifestation 4 -- Pinned digest in spec (Retro #18, concept-close-doc-refresh-and-55)

**Symptom:** UI deploy script runs cleanly. `oc rollout restart` runs. New pod comes up on a 23-hour-old image. `oc get deploy -o yaml` reveals the image is pinned to a specific `@sha256:...` digest, not the imagestream tag.

**Cause:** `memoryhub-ui` Deployment spec hard-codes a digest instead of `imagestream:latest`. `rollout restart` re-creates the pod on the same pinned digest.

**Fix proposed:** Use `imagestream:latest` with `imagePullPolicy: Always` in all Deployment specs. Tracked as **#83**.

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
5. **Tool-count regression check** (MCP servers only) -- query the running server's tool list and assert the expected count:
   ```bash
   # Pseudo: mcp-test-mcp list-tools | wc -l == EXPECTED_TOOL_COUNT
   ```
   Originally proposed in retro #11, finally landed in `65bca6c`. Must remain in every MCP deploy script.
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
- [ ] (MCP only) Deploy script asserts tool-count post-deploy
- [ ] Deploy script returns non-zero on any verification failure

## Component status

| Component | BuildConfig OK | Deployment OK | Deploy script OK |
|---|---|---|---|
| memory-hub-mcp | TBD (audit) | TBD (audit) | TBD (audit) |
| memoryhub-ui | TBD (audit -- #83 partially covers) | NO (digest pinned, #83) | NO (no rollout step, #83) |
| memoryhub-auth | TBD (audit) | TBD (audit) | TBD (audit) |

The umbrella issue this doc references will fill in the audit results and produce per-component fixes.

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
- `docs/operator.md` -- the future operator will adopt this contract
