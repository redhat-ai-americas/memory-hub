# Shared Runtime for MemoryHub Agent Plugins

**Issue:** #581
**Design PR:** #595
**Related:** OpenClaw integration (merged PR #490); OpenCode integration (PR #549)
**Reviewed:** 2026-10-20
**Scope:** Refactor the existing OpenClaw and OpenCode TypeScript plugins so they share MemoryHub behavior while retaining each host's runtime adapter.

This plan is limited to those two runtime plugins. Other agent integrations and instruction-file generation are separate work.

**Baseline status (updated 2026-10-22):** OpenCode was confirmed working after selecting the correct MemoryHub context. OpenClaw was deployed to an authorized cluster runtime; the plugin's MemoryHub tools and auto-recall were exercised successfully. The managed Mac installation attempts were terminated by the system, so local Mac installation remains unavailable, but OpenClaw runtime verification is no longer pending.

## 1. Goal

Remove duplicated MemoryHub client behavior from the OpenClaw and OpenCode plugins. A fix to shared behavior should be implemented once, while each host keeps the code needed to register tools, receive events, shape results, and inject context through its own SDK.

The refactor should preserve current behavior unless a difference is explicitly reviewed and accepted. It does not change MemoryHub's MCP tool surface or wire protocol.

## 2. Current implementation

Both plugins expose six `memoryhub_*` tools and call the MCP server's `memory` tool with an action and action-specific arguments. They also implement session setup, auto-recall, configuration, and inject the same `memoryhub-rules.md` content.

| Area | OpenClaw | OpenCode | Refactor boundary |
|---|---|---|---|
| Plugin lifecycle | `definePluginEntry`, registered service, `api.on` | Plugin factory, returned hooks, `dispose` | Keep host-specific |
| Tool registration/schema | Individually registered TypeBox tools | Zod tools returned from a hook | Share definitions and MCP mapping; adapt schemas and result shapes per host |
| Event and context injection | `before_prompt_build`; returns prompt context | `chat.message` search and message/system transform hooks | Keep event timing and host payload mutation per host |
| Recall | Search in prompt build; omits configured `projectId`; timeout timer is not cleared | Search on chat message; includes `projectId`; clears timeout; injects transformed message content | Share search/format/budget/error behavior; send configured `projectId` from both; keep trigger and injection per host |
| MCP connection | Concurrent calls can create multiple transports; reset does not close stale transport | Single-flight connect; closes failed/stale transports | Share lifecycle implementation |
| Session recovery | Lazy registration; tool calls retry recognized auth/session errors, but auto-recall catches its own errors so expired-session failures there are not retried | Lazy registration, one retry, and a generation guard in `session.ts`; tools and recall use it | Share one bounded recovery path and invoke it for both tools and recall |
| Configuration | Reads plugin options | Reads plugin options, environment, credentials INI, and legacy API-key file | Share normalized fields/defaults where they overlap; preserve each host's source lookup |
| Protocol text | Loads and injects `memoryhub-rules.md` | Loads and injects the same file through a different hook | Embed one canonical copy in both bundles; keep injection host-specific |
| Logging | OpenClaw host logger | Integration logger | Pass a small logger interface to shared code |

These are observations of the checked-in implementations. The MCP server currently emits “Authentication required” and “Session expired”; it does not currently emit “session not found,” although both plugins recognize that phrase. Keep or remove that compatibility match only after checking whether a supported older server needs it. OpenClaw's auto-recall error handling currently prevents its outer retry wrapper from seeing session errors.

## 3. Proposed package boundary

Add a small shared TypeScript module under `integrations/common/`. It should own only host-neutral behavior:

- MCP transport and connection lifecycle
- Session registration and bounded recovery
- Shared tool definitions and mapping to the MCP `memory` action
- Recall query construction, result formatting, untrusted-data framing, timeout, and token budget
- Shared configuration types, defaults, and validation for the overlapping fields
- The canonical protocol instructions embedded from one Markdown source

The OpenClaw and OpenCode packages remain responsible for:

- Their plugin entrypoints, SDK calls, hook registration, lifecycle, and disposal
- Converting shared tool definitions to TypeBox or Zod
- Translating host arguments and result shapes
- Selecting host events and inserting recalled content into host messages
- Host logging and host-specific configuration input

Do not target a specific adapter line count. Keep code in an adapter when it translates host APIs; share it when it implements the same MemoryHub behavior.

### Package distribution decision

**Decision:** Keep the shared module inside this repository and bundle it into each plugin's build output. Do not create a runtime dependency on a separately published `@memory-hub/common` package, and do not put repository-relative `file:` dependencies in the plugin manifests. A JavaScript workspace may help local development, but it must not be required by consumers installing a plugin.

This avoids making the refactor depend on npm organization access or a separate package release. Publishing the shared code as its own npm package can be reconsidered later if other consumers need it. The implementation must verify each packed plugin can be installed and loaded without access to this repository.

## 4. Decisions before extraction

The following behavior contract is the Phase 0 default. Record any change to it in the implementation PR before moving modules:

1. **Recall request:** Send the configured `projectId` as `project_id` in auto-recall for both plugins. OpenCode already does this; OpenClaw's auto-recall should be aligned. Keep host event timing and injection mechanics separate.
2. **Configuration:** Preserve each plugin's current source lookup in this refactor: OpenClaw uses its plugin options; OpenCode keeps plugin options, environment, credentials INI, and legacy key-file lookup. Share normalized types/defaults/validation for fields both actually use. Do not add credential sources to OpenClaw or drop its declared host-specific fields silently.
3. **Session recovery:** Register lazily and retry an operation at most once on recognized authentication/session-expiry errors. Use one concurrency-safe recovery path for tools and auto-recall. Match the current server phrases; retain the extra `session not found` match only if compatibility evidence supports it.
4. **Tool contract:** Compare all six tool names, descriptions, required/optional fields, defaults, and `memory` action mappings. Keep TypeBox/Zod conversion and host result wrappers in adapters.
5. **Recall failures:** Keep the 15-second timeout and graceful degradation. Clear timeout resources. A timeout should not claim to cancel an in-flight MCP call unless the transport supports cancellation.
6. **Protocol asset:** Use one canonical copy and confirm both npm packages include it in their published artifacts.
7. **Versioning:** Internal code movement alone does not require a major plugin version. Choose versions based on public compatibility changes and document any intentional behavior change.

## 5. Work sequence

### Phase 0: Freeze and agree on behavior

1. Use §2 as the code inventory and verify the MCP errors and request mappings against the server implementation.
2. Keep the decisions in §4 as the behavior contract; record any deliberate exception in the implementation PR.
3. Map each shared behavior to common tests and each host integration point to adapter tests.
4. Record which baseline checks have run: OpenCode live check succeeded; OpenClaw live check succeeded on an authorized cluster runtime. Automated tests cover both adapters with mocked MCP responses, alongside the live-host checks.

**Exit:** Contract, bundling approach, and verification matrix are agreed before extraction.

### Phase 1: Build the shared module

1. Create `integrations/common/` with a module API limited to the agreed shared behaviors.
2. Add common unit tests for connection lifecycle, session recovery, tool mapping, recall formatting/timeout, and configuration behavior that is actually shared.
3. Define the shared conformance cases; run them through both adapters after migration in Phase 2.
4. Confirm both plugin build configurations can inline shared TypeScript modules and the canonical Markdown asset. Packed plugin checks happen after adapters import the shared module in Phase 2.

**Exit:** The shared module API and behavior tests are in place. Both plugin build configurations can bundle it without a published common-package dependency.

### Phase 2: Migrate adapters

1. Move OpenClaw to the shared module; retain its plugin registration, TypeBox conversion, hooks, logger, and result translation.
2. Run OpenClaw adapter and conformance tests; perform a live-host smoke check on an authorized runtime when available.
3. Move OpenCode to the shared module; retain its plugin factory, Zod conversion, hooks, logger, and result translation.
4. Run OpenCode adapter and conformance tests, plus a live-host smoke check where available.
5. Compare both adapters with the Phase 0 contract and document any deliberate behavior changes.
6. Pack and install both plugins in clean temporary projects; confirm the shared runtime and protocol are present and no repository-relative or common-package dependency is required.

Migrate one adapter at a time so failures can be localized and each package remains reviewable.

**Exit:** Both adapters use the shared implementation, packed artifacts install outside the checkout, and all available automated and live checks are reported accurately.

### Phase 3: Release and documentation

1. Release updated OpenClaw and OpenCode plugin packages with migration notes for any user-visible changes. A maintainer with publishing access can perform the npm releases if the implementer does not have it.
2. Document shared-module development, build, test, and release steps.

The shared module does not need its own npm release. Revisit separate publication only if it becomes useful to consumers beyond these two bundled plugins.

Additional host integrations, templates, and instruction generation belong to separate work (including #310 where applicable).

## 6. Verification strategy

### Shared behavior tests

- Connection: concurrent connects share one attempt; failed setup cleans up; reset and close release stale transports.
- Session: lazy registration; one bounded recovery for recognized failures; concurrent failures do not cause duplicate registration or retries.
- Tools: all six definitions map to the agreed `memory` action and arguments; invalid host input is rejected by the adapter schema.
- Recall: request fields match the contract; output formatting and untrusted framing are stable; token budget and timeout are enforced; timers/resources are cleaned up.
- Configuration: per-field precedence, defaults, missing values, invalid types/URLs, and context selection match the agreed contract.
- Errors: MCP failures produce useful bounded errors and do not crash or hang a host turn.

### Adapter tests

- OpenClaw: plugin registration, TypeBox schemas, `before_prompt_build` inputs/outputs, service lifecycle, and result shape.
- OpenCode: plugin factory, Zod schemas, hook wiring, message/system transforms, disposal, and result shape.

### Packaging and host checks

- Pack and install each plugin in a clean temporary project with no repository-relative dependencies.
- Verify the protocol asset and runtime entrypoint are present in each package.
- Verify that each host loads the plugin, exposes the six tools, performs recall, and can complete a write against a test MemoryHub user.
- If a host cannot be run in the available environment, report that check as pending; unit or adapter tests do not substitute for live host verification.

Do not use a production user's memory for live checks. Use an identifiable test user and clean up any test memories.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Shared changes regress both hosts | Establish the behavior contract first; keep adapter tests and migrate one host at a time |
| A plugin artifact omits shared runtime code or assets | Inspect packed artifacts and install them in a clean temporary project outside the checkout |
| Host-specific behavior is flattened into generic code | Keep lifecycle, hooks, schema conversion, logging, and results in adapters |
| OpenClaw behavior changes unintentionally | Document config and recall decisions; compare against its current behavior |
| Server errors drift from retry matching | Verify and test against the server's current error contract |
| Live-host coverage is unavailable | Mark the exact check pending and run it later on an authorized host before claiming full verification |

## 8. Out of scope

- Building Claude Code, Codex, or other host integrations
- Generating host instruction/configuration files (#310)
- Changing MemoryHub MCP tools or wire protocol
- Adding automatic memory capture or unrelated product behavior
- Reworking either host's hook model

## 9. Success criteria

- One shared module owns the agreed host-neutral MemoryHub behavior and is bundled into both plugin artifacts.
- OpenClaw and OpenCode retain thin, understandable host adapters without losing required host-specific behavior.
- Common behavior and adapter tests cover the agreed contract.
- Both plugin artifacts install without repository-relative paths or a separately published common package, and contain the runtime/protocol assets they need.
- User-visible changes are either absent or documented with appropriate migration and versioning.
- Automated and live-host verification results, including unavailable checks, are reported accurately.
