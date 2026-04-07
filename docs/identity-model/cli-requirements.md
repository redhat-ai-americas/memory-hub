# Agent Generation CLI — Requirements

## Purpose

A CLI that takes a manifest describing the demo's agent fleet and produces
everything needed to deploy, identify, and drive those agents:

- Kubernetes Secrets (one per agent) carrying API keys
- The users ConfigMap with one entry per agent
- Project membership data wired into each user record
- A demo-harness manifest describing how to invoke each agent and what
  `driver_id` to use when invoking them
- Optional: Kubernetes Deployment manifests for each agent's container

This document describes what the CLI must accept, what it must produce, and
the conventions it enforces. Wes is implementing the CLI; this captures the
contract so the rest of the demo work can be designed against it.

## Inputs

### The fleet manifest

A YAML file (proposed: `demo/fleet.yaml`) describes the agent fleet
declaratively:

```yaml
fleet:
  name: ed-discharge-demo
  year: 2026
  default_identity_type: service

projects:
  - id: ed-discharge-workflow
    name: ED Discharge Workflow
    description: Coordinated discharge planning across the ED care team
  - id: medication-reconciliation
    name: Medication Reconciliation
    description: Cross-encounter medication safety checks
  - id: cardiology-consult
    name: Cardiology Consult
    description: Cardiology subspecialty consults during ED visits

roles:
  - id: ed-triage-nurse
    name: ED Triage Nurse
    instances: 5
    project_memberships:
      - ed-discharge-workflow
      - medication-reconciliation
  - id: ed-attending
    name: ED Attending
    instances: 3
    project_memberships:
      - ed-discharge-workflow
      - medication-reconciliation
      - cardiology-consult
  - id: pharmacist
    name: Pharmacist
    instances: 4
    project_memberships:
      - medication-reconciliation
  # ... etc, totaling ~50 agents across roles
```

The manifest is the single source of truth. Editing the YAML and
re-running the CLI is the supported workflow for adjusting the fleet.

### Required vs optional fields

| Field | Required | Notes |
|---|---|---|
| `fleet.name` | yes | Used as a prefix in API keys and resource names |
| `fleet.year` | yes | Embedded in API keys per existing convention (`mh-svc-<role>-<n>-<year>`) |
| `fleet.default_identity_type` | no | Defaults to `service` for fleet agents |
| `projects[].id` | yes | Stable identifier; used as `owner_id` for project-scope memories |
| `projects[].name` | yes | Human-readable, for the harness UI |
| `roles[].id` | yes | Used as a prefix in agent identifiers |
| `roles[].instances` | yes | How many agents of this role to generate |
| `roles[].project_memberships` | yes | List of project IDs the role's agents belong to |

## Outputs

### 1. The users ConfigMap

A `users-configmap.yaml` matching the schema in
`memory-hub-mcp/deploy/users-configmap.yaml`, with one entry per generated
agent:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: memoryhub-users
data:
  users.json: |
    {
      "users": [
        {
          "user_id": "ed-triage-nurse-01",
          "name": "ED Triage Nurse 01",
          "api_key": "mh-svc-ed-triage-nurse-01-2026",
          "identity_type": "service",
          "scopes": ["user", "project"],
          "project_memberships": [
            "ed-discharge-workflow",
            "medication-reconciliation"
          ]
        },
        ...
      ]
    }
```

The `project_memberships` field is the new field defined in
[authorization.md](authorization.md). The CLI populates it from the role's
membership list in the manifest.

### 2. Per-agent Kubernetes Secrets

One Secret per agent containing the API key:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: agent-ed-triage-nurse-01-credentials
  labels:
    memoryhub.redhat.com/agent-id: ed-triage-nurse-01
    memoryhub.redhat.com/role: ed-triage-nurse
    memoryhub.redhat.com/fleet: ed-discharge-demo
type: Opaque
stringData:
  MEMORYHUB_API_KEY: mh-svc-ed-triage-nurse-01-2026
  MEMORYHUB_AGENT_ID: ed-triage-nurse-01
  MEMORYHUB_ROLE: ed-triage-nurse
```

The agent reads these env vars at startup and calls
`register_session(api_key=os.environ["MEMORYHUB_API_KEY"])`. The
`MEMORYHUB_AGENT_ID` is for self-identification in logs and never sent over
the wire — it's redundant with what the API key resolves to but useful for
debugging.

The Secret's labels let the demo harness query "all agents in this fleet"
or "all agents in this role" via standard kubectl selectors.

### 3. The demo harness manifest

A separate file (proposed: `demo/harness.yaml`) describing how the CLI
harness invokes each agent and what `driver_id` to use when driving:

```yaml
harness:
  fleet: ed-discharge-demo
  driver_prefix: claude-code-cli

agents:
  - agent_id: ed-triage-nurse-01
    role: ed-triage-nurse
    api_key_secret: agent-ed-triage-nurse-01-credentials
    invoke:
      command: ["python", "-m", "demo.agents.ed_triage_nurse"]
      env:
        AGENT_INSTANCE: "01"
    driver_id_pattern: "{driver_prefix}-{run_id}"
  ...
```

The harness, when launching agent #07 in test run #14, computes
`driver_id = claude-code-cli-run-14` and either passes it as
`--driver-id claude-code-cli-run-14` to the agent's CLI or sets
`MEMORYHUB_DRIVER_ID=claude-code-cli-run-14` in the environment. The agent
then calls
`register_session(api_key=..., default_driver_id=os.environ.get("MEMORYHUB_DRIVER_ID"))`
at startup.

When no `MEMORYHUB_DRIVER_ID` is set (the agent is running autonomously,
not driven by the harness), `default_driver_id` is omitted and the agent
operates in autonomous mode where `driver_id == actor_id`.

### 4. (Optional) Per-agent Deployment manifests

If desired, the CLI can also emit Kubernetes Deployments that mount the
Secret and run the agent container. Whether to scope this in is Wes's call;
it's marked optional because some demo flows may want to launch agents from
the harness directly rather than as long-running pods.

## Conventions enforced

- **API key format**: `mh-svc-<role>-<instance>-<year>` for service agents.
  Existing convention from `docs/governance.md`.
- **Agent ID format**: `<role>-<instance>` (e.g., `ed-triage-nurse-01`).
  Used as `user_id` and as a label value.
- **Instance numbering**: zero-padded 2-digit (01, 02, ..., 99). Numbering
  starts at 01.
- **Identity type**: `service` for all fleet agents unless overridden in the
  manifest.
- **Required scopes**: `["user", "project"]` for fleet agents. They write
  private memories at user scope and shared memories at project scope.
  Organizational and enterprise scopes are explicitly not granted.
- **Project IDs**: lowercase, hyphen-delimited, stable. Used as `owner_id`
  for project-scope memories so they appear naturally in queries.
- **Membership symmetry**: every project an agent has in
  `project_memberships` must exist in the manifest's `projects` list. The
  CLI must validate this.

## Idempotency

Re-running the CLI against the same manifest must be idempotent: same
manifest in, same files out, byte-for-byte. This is important for git
review of fleet changes — a one-line manifest edit should produce a
small, reviewable diff in the generated artifacts, not a complete rewrite.

Specifically:

- The order of users in `users.json` must be deterministic (sorted by
  `user_id`).
- Generated Secret names must be deterministic and stable across runs.
- Timestamps and generated IDs must not appear in any output file unless
  explicitly required.

## Validation

Before emitting any files, the CLI must validate:

- Every `roles[].project_memberships` entry refers to a project that
  exists in `projects[]`.
- No two roles produce colliding agent IDs.
- The total number of agents does not exceed a sane upper bound (suggest
  500 as a safety check; the demo targets 50).
- API keys do not collide with existing entries in any pre-existing
  `users-configmap.yaml` if updating in-place.
- All identifiers conform to the format conventions above.

Validation errors must be reported with the offending manifest path and
line number where possible.

## Driver ID handling in the harness

This is the part most relevant to the identity model: how the harness
propagates `driver_id` when driving agents.

Decisions captured during design discussion:

- **One driver per invocation.** Each test run gets a unique driver ID like
  `claude-code-cli-run-14` or `wjackson-cli-run-2026-04-07-1530`. Agents
  invoked during that run all carry the same driver ID. This makes "show me
  everything that happened in test run 14" a single indexed query.
- **Fully autonomous mode**: when no driver is supplied (agent runs as a
  cron job, scheduled task, or long-running pod with no human input), the
  agent omits `default_driver_id` from `register_session`, MemoryHub
  defaults `driver_id = actor_id`, and queries can distinguish autonomous
  from driven operations by checking `driver_id == actor_id`.
- **Long-lived agents serving multiple drivers**: not part of the demo, but
  the per-request `driver_id` parameter supports it. A future chatbot agent
  serving multiple clinicians would call `write_memory(content="...",
  driver_id="dr-smith-2026")` and pass a different value for each
  clinician.

## What the CLI does NOT do

Out of scope:

- Generating MemoryHub deployment manifests, Routes, or Services. The CLI
  generates *fleet* artifacts; MemoryHub itself is deployed separately.
- Running agents. The CLI is a code-gen tool, not a process supervisor.
- Talking to MemoryHub at runtime. All outputs are static files.
- Managing project lifecycles beyond what's in the manifest. There is no
  "delete project" or "archive agent" operation; manifest edits + re-run
  is the only workflow.
- Provisioning JWT-based identities. That's Phase 2 work; the CLI is
  Phase 1 (API key) only.

## Open questions

- *Should the CLI emit one combined `users-configmap.yaml` per fleet, or
  merge into an existing ConfigMap?* For the demo, one fleet → one
  ConfigMap is simplest.
- *Where should the CLI live in the repo?* Suggest a sibling to
  `memoryhub-cli/` or under `demo/cli/`. Wes's call.
- *Should the CLI emit a markdown or HTML "fleet roster" for the demo
  presenter to reference?* Nice-to-have, not required for the contract.
