# RHOAI Dashboard Demo

Integrate MemoryHub as a native-looking component in the Red Hat OpenShift AI dashboard.

## Goal

For the demo, MemoryHub appears as a tile in the RHOAI dashboard's **Applications > Enabled** page. Clicking it opens a PatternFly-based landing page that showcases memory governance capabilities.

## Documents

| Document | Contents |
|---|---|
| [odh-application-cr.md](odh-application-cr.md) | OdhApplication CR to register the tile |
| [landing-page-design.md](landing-page-design.md) | Content spec for the landing page (7 panels) |
| [ui-architecture.md](ui-architecture.md) | Two integration options: standalone app vs. dashboard plugin |

## Prerequisites

- MemoryHub MCP server deployed and healthy
- A Route serving the landing page UI
- Access to create resources in `redhat-ods-applications` namespace
