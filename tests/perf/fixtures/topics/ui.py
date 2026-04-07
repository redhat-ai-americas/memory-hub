"""UI-topic synthetic memories.

50 memories about React, PatternFly 6, the BFF backend, dashboard panels,
and component patterns used in memoryhub-ui.
"""

FOCUS_STRING = (
    "React PatternFly 6 dashboard UI, frontend components, BFF backend routes, "
    "panels, modals, EmptyState, filters, and form controls"
)

MEMORIES = [
    {
        "content": "memoryhub-ui uses PatternFly 6 (PF6), not PF5 or earlier. PF6 dropped several legacy components and renamed some. Don't copy patterns from PF5 docs without checking the migration guide.",
        "weight": 0.9,
    },
    {
        "content": "PatternFly 6 Label component uses 'yellow' as the color name, not 'gold'. Using 'gold' silently falls back to the default neutral color and looks broken.",
        "weight": 0.95,
    },
    {
        "content": "memoryhub-ui ships as a single container: FastAPI BFF + React frontend served by uvicorn. The React build output goes to backend/static/ and FastAPI serves it as static files.",
        "weight": 0.85,
    },
    {
        "content": "BFF endpoints live under /api/. The React app expects /api/curation_rules, /api/contradictions, /api/agents, etc. Don't break this prefix without updating the frontend fetch calls.",
        "weight": 0.85,
    },
    {
        "content": "Dashboard has six active panels: Memory Graph, Status Overview, Users & Agents, Client Management, Curation Rules, Contradiction Log. Observability is the seventh, currently disabled.",
        "weight": 0.85,
    },
    {
        "content": "Curation Rules panel has CRUD via /api/rules with inline Switch toggle for enabled state, tier and enabled filters at the top, and create/delete modals. The toggle calls PATCH; the form calls POST/DELETE.",
        "weight": 0.85,
    },
    {
        "content": "Contradiction Log panel has a stats bar (total/unresolved counts), filters by resolution and confidence, and resolve/unresolve buttons inline on each row. Uses /api/contradictions.",
        "weight": 0.85,
    },
    {
        "content": "Use PatternFly EmptyState for zero-result panels. Don't render an empty Table or DataList; the EmptyState provides an icon, title, and CTA that explain what should be there.",
        "weight": 0.85,
    },
    {
        "content": "PF6 Modal needs an explicit ModalVariant. Default is 'medium' but most data-entry modals look better as 'small' or 'large' depending on field count. The variant prop is required in PF6.",
        "weight": 0.8,
    },
    {
        "content": "React state for filters in dashboard panels should live in URL query params, not just useState. URL params let users share filtered views and survive tab reloads.",
        "weight": 0.8,
    },
    {
        "content": "Use react-query or SWR for data fetching, not raw useEffect+fetch. The cache layer prevents redundant API calls when panels mount and unmount as the user navigates the dashboard.",
        "weight": 0.85,
    },
    {
        "content": "PF6 DataList vs Table: DataList is better for cards-with-actions; Table is better for tabular data with sortable columns. Don't force tabular data into a DataList.",
        "weight": 0.8,
    },
    {
        "content": "memoryhub-ui's build context for OpenShift needs physical copies in a temp dir. The Containerfile expects backend/, frontend/build/, and a flat memoryhub/ symlink-resolved into the build context.",
        "weight": 0.85,
    },
    {
        "content": "BFF FastAPI app uses async route handlers. Don't mix sync and async — sync routes block the event loop and the dashboard freezes when /api/contradictions is slow.",
        "weight": 0.85,
    },
    {
        "content": "Use Pydantic models for BFF request and response bodies. The OpenAPI schema generated from the models is consumed by the frontend's TypeScript types via openapi-typescript.",
        "weight": 0.85,
    },
    {
        "content": "PF6 Form components need explicit FormGroup wrappers around each field. The FormGroup provides label, helperText, and error-state styling. Bare TextInput inside Form looks broken.",
        "weight": 0.8,
    },
    {
        "content": "React strict mode is on in development for memoryhub-ui. Effects fire twice on mount; design effects to be idempotent or use a ref guard.",
        "weight": 0.8,
    },
    {
        "content": "Use PF6 Toolbar with ToolbarContent + ToolbarItem for filter bars at the top of dashboard panels. ToolbarFilter handles filter chips; the manual approach gets unwieldy.",
        "weight": 0.8,
    },
    {
        "content": "BFF authentication: pass through the user's JWT to memory-hub-mcp via the Authorization header. The BFF doesn't store credentials; it acts as a thin proxy with shape transformation.",
        "weight": 0.85,
    },
    {
        "content": "Dashboard navigation uses PF6 Nav component with NavList and NavItem. Active state is driven by the route. Don't manage active state manually; the NavLink integration handles it.",
        "weight": 0.8,
    },
    {
        "content": "PF6 PageSection with variant='light' is the default for content panels. Use variant='darker' to highlight sections that need visual separation, like header bars.",
        "weight": 0.75,
    },
    {
        "content": "memoryhub-ui frontend lives at memoryhub-ui/frontend/ as a Vite + React + TypeScript project. Backend is at memoryhub-ui/backend/ as a FastAPI app.",
        "weight": 0.85,
    },
    {
        "content": "Use the BFF's openapi.json to regenerate frontend TypeScript types. The generated types catch breaking API changes at build time, not at runtime.",
        "weight": 0.8,
    },
    {
        "content": "PF6 useTableSort hook is the right way to add sortable columns to a Table. It manages sort state and provides the onSort handler. Don't reimplement sort manually.",
        "weight": 0.75,
    },
    {
        "content": "The Curation Rules create modal uses controlled form state. Each field has its own setter; the Save button is disabled until required fields pass validation.",
        "weight": 0.8,
    },
    {
        "content": "BFF ought to validate request bodies before forwarding to memory-hub-mcp. Catch errors early and return 400 with a helpful message, instead of letting the MCP server reject and surface a generic 500.",
        "weight": 0.85,
    },
    {
        "content": "Use PF6 Alert for transient notifications. Set variant='success' for confirmations, 'danger' for errors, 'warning' for confirmations of risky actions. Auto-dismiss success alerts after 3 seconds.",
        "weight": 0.8,
    },
    {
        "content": "Dashboard Status Overview panel polls /api/status every 30 seconds. Use a useInterval custom hook, not setInterval inside useEffect — the latter doesn't clean up reliably.",
        "weight": 0.8,
    },
    {
        "content": "PF6 Spinner should be wrapped in a Bullseye layout for centered loading states. Inline spinners belong inside button labels, not as the panel-level loading indicator.",
        "weight": 0.75,
    },
    {
        "content": "Frontend error boundaries catch React component errors and render a fallback UI. Wrap each dashboard panel in its own error boundary so one panel's crash doesn't blank the whole dashboard.",
        "weight": 0.85,
    },
    {
        "content": "BFF logging: log inbound requests with structlog at INFO, errors at ERROR with the originating request ID. The dashboard shows the request ID on error toasts for easy log lookup.",
        "weight": 0.8,
    },
    {
        "content": "PF6 PageHeader uses Brand for the logo, MastheadMain for the title, and MastheadContent for the right-side controls. The component layout changed in PF6; PF5 patterns don't translate.",
        "weight": 0.8,
    },
    {
        "content": "Use the React Router v6 useNavigate hook for programmatic navigation. The v5 useHistory is deprecated; mixing v5 and v6 patterns produces hard-to-debug navigation bugs.",
        "weight": 0.75,
    },
    {
        "content": "Dashboard Memory Graph panel uses a force-directed layout (d3-force) inside a React component. The graph data comes from /api/graph and updates incrementally as the user drills in.",
        "weight": 0.85,
    },
    {
        "content": "Frontend tests use React Testing Library with jest-dom matchers. Test user-visible behavior, not implementation details. screen.getByRole over getByTestId where possible.",
        "weight": 0.8,
    },
    {
        "content": "PF6 Tabs need an explicit aria-label and each Tab needs a unique key. Without keys, switching tabs leaves stale state in the previous tab's content.",
        "weight": 0.75,
    },
    {
        "content": "BFF response shapes should mirror the MCP tool response shapes. Don't reformat data in the BFF unless the frontend genuinely needs a different shape; transparent pass-through is easier to maintain.",
        "weight": 0.85,
    },
    {
        "content": "PF6 Card with CardHeader, CardBody, CardFooter is the right primitive for the dashboard panel boxes. Don't use plain divs; PF6 cards handle elevation, hover, and theme integration.",
        "weight": 0.8,
    },
    {
        "content": "Use PF6 Switch for boolean toggles in inline contexts (table rows, list items). Use Checkbox for boolean inputs in forms. The two look similar but have different accessibility semantics.",
        "weight": 0.75,
    },
    {
        "content": "BFF endpoints that proxy MCP tool responses should add a 'source: mcp' field for client-side debugging. Helps the frontend distinguish BFF errors from MCP errors when something fails.",
        "weight": 0.75,
    },
    {
        "content": "memoryhub-ui deployment is built and deployed via a single Containerfile that compiles the React app at build time and bundles it with the Python backend. No separate frontend deployment.",
        "weight": 0.85,
    },
    {
        "content": "Dashboard panels should be lazy-loaded via React.lazy and Suspense. The bundle is large enough that eager-loading every panel adds noticeable startup latency on the dashboard's first load.",
        "weight": 0.8,
    },
    {
        "content": "PF6 Pagination component needs total count, current page, per-page count, and onSetPage callback. Panel filters that change the result set should reset page to 1.",
        "weight": 0.8,
    },
    {
        "content": "Frontend uses dotenv for env vars (VITE_API_BASE_URL etc). Don't bake URLs into the bundle; the API base URL is set at runtime by the BFF via window.__APP_CONFIG__.",
        "weight": 0.75,
    },
    {
        "content": "BFF /api/status endpoint returns memory-hub-mcp health, BFF version, build SHA, and the connected user's JWT claims summary. Used by Status Overview panel.",
        "weight": 0.8,
    },
    {
        "content": "Use PF6 Badge to display counts (e.g., unresolved contradictions on the nav badge). Badge color follows the same yellow/blue/green/red palette as Label.",
        "weight": 0.75,
    },
    {
        "content": "memoryhub-ui frontend builds with 'npm run build' and outputs to frontend/build/. The Containerfile copies that into the FastAPI static dir during image build.",
        "weight": 0.8,
    },
    {
        "content": "Form validation in memoryhub-ui uses Zod schemas with react-hook-form. Schema-driven validation produces better error messages than ad-hoc isValid functions sprinkled in handlers.",
        "weight": 0.8,
    },
    {
        "content": "PF6 Toolbar filter chips appear below the filter bar when filters are active. Clicking a chip removes that filter. Frontend must handle the chip-clear callback to update its filter state.",
        "weight": 0.75,
    },
    {
        "content": "Dashboard Client Management panel uses a Table with sortable columns for client name, scopes, last activity, and action buttons. Sorts use PF6 useTableSort hook.",
        "weight": 0.8,
    },
]

assert len(MEMORIES) == 50, f"ui fixture must have 50 memories, has {len(MEMORIES)}"
