# Kubernetes-General MemoryHub: From OpenShift AI Component to Community Project

**Status:** Design (portability audit grounded in repo state 2026-07-16)
**Date:** 2026-07-16
**Author:** @rdwj (designed with Claude in Cowork)
**Builds on:** `planning/personal-edition.md` (the ladder this completes),
`planning/git-transport-mode.md`, `strategy/client-supplied-intelligence.md`

## 1. Why

Community adoption requires that `helm install memoryhub` work on any
conformant Kubernetes — kind, k3s, EKS, GKE, AKS — with no OpenShift
prerequisites. The org playbook is upstream/downstream (the ODH -> RHOAI
motion): **MemoryHub the community project** runs K8s-general; **MemoryHub
the OpenShift AI component** is the downstream packaging with the
enterprise integrations. Nothing about the current architecture prevents
this — the data plane (PostgreSQL+pgvector, MinIO-or-any-S3, Valkey, TEI)
is vanilla; the coupling is confined to the deploy/build/expose layer.

This also completes the adoption ladder:
**personal (pip, SQLite)** -> **git-team (git transport)** ->
**k8s-community (helm, any cluster)** -> **OpenShift AI (product)**.
Every rung uses the same tool surface, SDK, and semantics; `memoryhub
join` moves users up the ladder with provenance intact.

## 2. Portability audit (grounded — file citations, not assumptions)

| Coupling | Where (verified) | K8s-general replacement | Effort |
|----------|------------------|------------------------|--------|
| `oc` CLI throughout script layer | `scripts/deploy-full.sh`, `check-prereqs.sh`, `run-migrations.sh`, `cluster-setup-github-idp.sh`, others | `kubectl` everywhere it's 1:1; isolate genuinely-OpenShift ops behind a detected `IS_OPENSHIFT` flag | Medium (mechanical, wide) |
| OpenShift Routes | `deploy/reranker/route.yaml`, `deploy/embedding/route.yaml` (no Ingress manifests exist) | Ingress (+ IngressClass) or Gateway API; Route retained as an overlay for the downstream | Small |
| `anyuid` SCC grants ×3 | `scripts/deploy-full.sh:240,342,346` (DB, MinIO, Valkey service accounts); `deploy/postgresql/README.md` documents the random-UID issue | Root-cause fix, not a translation: set explicit `securityContext` (runAsUser/fsGroup) or use images that tolerate arbitrary UIDs; on plain K8s use Pod Security Standards. Fixing this properly REMOVES the SCC need on OpenShift too | Small-Medium |
| BuildConfig/ImageStream | benchmark infra only (`benchmarks/evalhub-adapter/manifests/buildconfig.yaml`, `scripts/deploy-evalhub.sh`, `uninstall-full.sh`) | GitHub Actions -> ghcr/quay (release workflow already exists for PyPI with attestation — extend to images) | Small; benchmark-only, not product path |
| GitHub IdP / auth setup script | `scripts/cluster-setup-github-idp.sh` | Downstream-only; community auth = the existing self-contained auth service (API key + OAuth 2.1), no cluster IdP dependency | None (scope decision) |
| No Helm chart | `deploy/` is per-component kustomize + deploy-full.sh orchestration | **The centerpiece deliverable:** a Helm chart encoding everything deploy-full.sh knows (secret generation, cross-namespace copies, migration job, idempotency) — see Section 3 | Large |
| Positioning language | CLAUDE.md epic statement, README, ARCHITECTURE.md ("on OpenShift AI") | "Kubernetes-native, packaged for OpenShift AI" — docs sweep | Small |
| UBI base images, FIPS posture | everywhere | KEEP — UBI is freely redistributable; FIPS becomes an optional value ("hardened by default") not a prerequisite | None |
| Granite models via TEI | `deploy/embedding`, `deploy/reranker` | Already portable (TEI is upstream HF; models Apache 2.0). GPU optional: CPU profile reuses the personal edition's ONNX path | Small |
| EvalHub/TrustyAI | benchmark infra | Stays RHOAI-side; community CI uses the personal-edition harness path (no cluster needed) | None |

**Unverified items for the implementing session** (capability-claims
rule): whether the PG image swap or securityContext fully removes the
anyuid need (test on kind with restricted PSS); whether anything in
memoryhub-auth assumes OpenShift OAuth (believed self-contained —
verify); operator plans (`planning/operator.md`) — kopf/operator-sdk are
K8s-general already, confirm no Route/SCC assumptions in that design.

## 3. The Helm chart (the real work)

`deploy-full.sh` encodes hard-won operational knowledge that MUST NOT be
lost in translation — it is the spec, per the CLAUDE.md reproducibility
checklist:

- Secret generation with generate-if-missing idempotency
- Cross-namespace secret copies (or better: collapse the community
  chart to ONE namespace — the multi-namespace split is an enterprise
  concern; sub-charts with a `namespaceOverride` for downstream)
- Alembic migration as a pre-install/pre-upgrade Job (replaces
  `run-migrations.sh`)
- Ordered readiness (auth before MCP — the race fixed on 07-14)
- The golden test, ported: `helm uninstall` (values-gated DB retention)
  + `helm install` must round-trip with zero manual steps — this
  becomes the community CI gate on kind, replacing nothing and
  protecting everything

Profiles via values: `minimal` (single namespace, CPU/ONNX models, no
MinIO — 100KB inline threshold makes S3 optional for small installs, no
Valkey until agents are enabled) through `full` (GPU TEI, S3, Valkey,
agents). `minimal` must run on kind on a laptop — that is the community
first-touch, and it doubles as the CI environment.

## 4. What stays downstream (OpenShift AI packaging)

Routes overlay, IdP integration, SCC handling if any remains, RHOAI
console/operator integration, FIPS-verified builds, support lifecycle.
The downstream consumes the community chart + overlays — one codebase,
two distributions, same as the model the org already runs elsewhere.

## 5. Sequencing (new epic or personal-edition sibling, ~5 sessions)

1. **K1 — securityContext root-cause fix** (removes SCC need everywhere;
   verify on kind with restricted PSS). Smallest, highest-leverage.
2. **K2 — Route->Ingress + `oc`->`kubectl` sweep** (Route as overlay;
   `IS_OPENSHIFT` detection for the residue). Loop-shaped: grep-zero
   exit predicate on `oc ` outside the openshift/ overlay dir.
3. **K3-K4 — Helm chart** (minimal profile first, then full; migration
   Job; golden test on kind in CI).
4. **K5 — docs/positioning sweep** + community quickstart ("kind +
   helm + Claude Code in 15 minutes") + artifacthub listing.

Dependencies: none on the dreaming epic. K1/K2 are quota-free,
attention-light sessions — ideal counter-programming for
benchmark-blocked weeks, same as personal-edition P1.

## 6. Open questions

1. Namespace topology for community chart: one namespace (lean) vs
   preserving the 3-namespace split (parity with downstream). Leaning
   one, with sub-chart overrides.
2. Community CI budget: kind-based golden test per PR vs nightly.
3. Chart hosting: repo-local + artifacthub vs a charts monorepo.
4. Does the community edition ship the agents (Curator etc.) at launch
   or land them when Phase 6 stabilizes? Leaning: values-gated, off by
   default.
5. Naming/branding for upstream vs downstream (defer; "early customer
   preference"-style sensitivity applies to community positioning too).
