# OdhApplication CR for MemoryHub

## How it works

The RHOAI dashboard watches for `OdhApplication` custom resources in the
`redhat-ods-applications` namespace. Each CR becomes a tile on the
**Applications > Enabled** page. The dashboard resolves the `route` /
`routeNamespace` fields to find the target URL for the "Open application"
button.

CRs created directly (without `ownerReferences` to the Dashboard operator)
are left untouched by the operator — this is the same pattern ISV partners
use to register their applications.

## Manifest

```yaml
apiVersion: dashboard.opendatahub.io/v1
kind: OdhApplication
metadata:
  name: memoryhub
  namespace: redhat-ods-applications
  labels:
    app.opendatahub.io/rhods-dashboard: "true"
  annotations:
    opendatahub.io/categories: "Model development"
spec:
  displayName: MemoryHub
  description: >-
    Centralized agent memory with governance and curation
    for OpenShift AI workloads.
  category: Red Hat managed
  provider: "Red Hat"
  support: "red hat"
  route: memoryhub-ui
  routeNamespace: memory-hub-mcp
  docsLink: ""                    # TODO: link to published docs
  getStartedLink: ""
  getStartedMarkDown: |
    # MemoryHub

    Centralized, governed memory for AI agents running on OpenShift AI.

    ## Getting Started

    1. Click **Open application** to access the MemoryHub dashboard.
    2. Browse agent memories, review curation rules, and monitor
       contradiction reports.
    3. Use the MCP server endpoint to connect your agents.

    ## Prerequisites

    - The MemoryHub MCP server must be deployed in the `memory-hub-mcp` namespace.
    - Agents connect via the MCP server Route using OAuth 2.1 JWT tokens.
  img: |
    <!-- TODO: Replace with MemoryHub icon SVG -->
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36">
      <rect width="36" height="36" rx="4" fill="#ee0000"/>
      <text x="18" y="24" text-anchor="middle"
            font-family="RedHatDisplay,sans-serif" font-size="16"
            font-weight="700" fill="#fff">M</text>
    </svg>
```

## Applying

```bash
oc apply -f memoryhub-odh-application.yaml -n redhat-ods-applications
```

The tile appears immediately — no dashboard restart needed.

## Removing

```bash
oc delete odhapplication memoryhub -n redhat-ods-applications
```

## Long-term path

To make MemoryHub operator-managed (created/deleted as part of RHOAI
lifecycle), the OdhApplication manifest needs to be bundled into either:

- The upstream [ODH dashboard](https://github.com/opendatahub-io/odh-dashboard) manifests, or
- The RHOAI operator's reconciled resource set

This requires coordination with the RHOAI engineering team and is the
right path once MemoryHub is accepted as an official platform component.
