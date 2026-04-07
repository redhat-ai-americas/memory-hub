"""Benchmark queries for the two-vector retrieval study.

40 queries (10 per topic) at three specificity levels:
- specific (4): mentions topic-specific terms; should match without focus bias
- ambiguous (4): could match multiple topics depending on session context
- cross_topic (2): intentionally pulls from a topic different from the
  declared session focus, to test that focus biasing doesn't suppress
  off-topic content too aggressively

Each query is tagged with its expected topic (the topic whose memories
should appear in the top results when no focus bias is applied).
"""

QUERIES = [
    # ── deployment ───────────────────────────────────────────────
    # specific
    {"id": "deployment-s1", "topic": "deployment", "level": "specific",
     "text": "how do I avoid the linux/amd64 architecture mismatch when building containers on a Mac"},
    {"id": "deployment-s2", "topic": "deployment", "level": "specific",
     "text": "what's the right way to fix Permission denied errors from src/*.py in OpenShift pods"},
    {"id": "deployment-s3", "topic": "deployment", "level": "specific",
     "text": "BuildConfig binary source type how does the build context upload work"},
    {"id": "deployment-s4", "topic": "deployment", "level": "specific",
     "text": "OpenShift Route TLS termination edge vs reencrypt"},
    # ambiguous
    {"id": "deployment-a1", "topic": "deployment", "level": "ambiguous",
     "text": "what's the standard image base"},
    {"id": "deployment-a2", "topic": "deployment", "level": "ambiguous",
     "text": "rolling update strategy defaults"},
    {"id": "deployment-a3", "topic": "deployment", "level": "ambiguous",
     "text": "best way to manage credentials at runtime"},
    {"id": "deployment-a4", "topic": "deployment", "level": "ambiguous",
     "text": "how should we handle environment-specific configuration"},
    # cross_topic — these queries should still surface their target topic
    # even when a different focus is declared
    {"id": "deployment-x1", "topic": "deployment", "level": "cross_topic",
     "text": "container runtime preference podman or docker"},
    {"id": "deployment-x2", "topic": "deployment", "level": "cross_topic",
     "text": "do we use Helm or Kustomize for OpenShift manifests"},

    # ── mcp_tools ────────────────────────────────────────────────
    # specific
    {"id": "mcp_tools-s1", "topic": "mcp_tools", "level": "specific",
     "text": "how do I test a FastMCP decorated tool function in pytest"},
    {"id": "mcp_tools-s2", "topic": "mcp_tools", "level": "specific",
     "text": "what's the rule about adding new tools to main.py for memory-hub-mcp"},
    {"id": "mcp_tools-s3", "topic": "mcp_tools", "level": "specific",
     "text": "src prefix imports vs short-form imports in MCP server modules"},
    {"id": "mcp_tools-s4", "topic": "mcp_tools", "level": "specific",
     "text": "fips-agents scaffold workflow plan-tools create-tools exercise-tools"},
    # ambiguous
    {"id": "mcp_tools-a1", "topic": "mcp_tools", "level": "ambiguous",
     "text": "what's the right way to handle errors in tool responses"},
    {"id": "mcp_tools-a2", "topic": "mcp_tools", "level": "ambiguous",
     "text": "how should I structure tool parameter validation"},
    {"id": "mcp_tools-a3", "topic": "mcp_tools", "level": "ambiguous",
     "text": "what does the tool annotation hint do"},
    {"id": "mcp_tools-a4", "topic": "mcp_tools", "level": "ambiguous",
     "text": "are tools supposed to return dicts or pydantic models"},
    # cross_topic
    {"id": "mcp_tools-x1", "topic": "mcp_tools", "level": "cross_topic",
     "text": "FastMCP streamable-http vs SSE transport choice"},
    {"id": "mcp_tools-x2", "topic": "mcp_tools", "level": "cross_topic",
     "text": "search_memory branch handling include_branches parameter"},

    # ── ui ───────────────────────────────────────────────────────
    # specific
    {"id": "ui-s1", "topic": "ui", "level": "specific",
     "text": "PatternFly 6 Label color name yellow vs gold"},
    {"id": "ui-s2", "topic": "ui", "level": "specific",
     "text": "how does the dashboard's curation rules panel handle the inline switch toggle"},
    {"id": "ui-s3", "topic": "ui", "level": "specific",
     "text": "memoryhub-ui build context structure for the OpenShift Containerfile"},
    {"id": "ui-s4", "topic": "ui", "level": "specific",
     "text": "EmptyState component when a panel has no results"},
    # ambiguous
    {"id": "ui-a1", "topic": "ui", "level": "ambiguous",
     "text": "where should filter state live"},
    {"id": "ui-a2", "topic": "ui", "level": "ambiguous",
     "text": "what's the right pattern for forms"},
    {"id": "ui-a3", "topic": "ui", "level": "ambiguous",
     "text": "loading indicators best practices"},
    {"id": "ui-a4", "topic": "ui", "level": "ambiguous",
     "text": "how should we handle errors in panels"},
    # cross_topic
    {"id": "ui-x1", "topic": "ui", "level": "cross_topic",
     "text": "FastAPI BFF endpoint conventions for the dashboard"},
    {"id": "ui-x2", "topic": "ui", "level": "cross_topic",
     "text": "react-query versus raw useEffect for fetching"},

    # ── auth ─────────────────────────────────────────────────────
    # specific
    {"id": "auth-s1", "topic": "auth", "level": "specific",
     "text": "JWT validation order signature expiry issuer audience"},
    {"id": "auth-s2", "topic": "auth", "level": "specific",
     "text": "how does memoryhub do scope filtering at the SQL level for search_memory"},
    {"id": "auth-s3", "topic": "auth", "level": "specific",
     "text": "OAuth 2.1 PKCE code_verifier code_challenge"},
    {"id": "auth-s4", "topic": "auth", "level": "specific",
     "text": "RFC 8693 token exchange grant for kagenti service accounts"},
    # ambiguous
    {"id": "auth-a1", "topic": "auth", "level": "ambiguous",
     "text": "how should refresh tokens be handled"},
    {"id": "auth-a2", "topic": "auth", "level": "ambiguous",
     "text": "what's the right way to handle credentials in container runtime"},
    {"id": "auth-a3", "topic": "auth", "level": "ambiguous",
     "text": "scope hierarchy and tiers"},
    {"id": "auth-a4", "topic": "auth", "level": "ambiguous",
     "text": "should we trust claims from client side"},
    # cross_topic
    {"id": "auth-x1", "topic": "auth", "level": "cross_topic",
     "text": "register_session API key format mh-dev-username-year"},
    {"id": "auth-x2", "topic": "auth", "level": "cross_topic",
     "text": "JWKS endpoint key rotation kid header"},
]

# Sanity-check counts so failures point at the dataset, not the harness.
assert len(QUERIES) == 40, f"queries fixture must have 40 entries, has {len(QUERIES)}"
_per_topic_count: dict[str, int] = {}
for q in QUERIES:
    _per_topic_count[q["topic"]] = _per_topic_count.get(q["topic"], 0) + 1
for topic, count in _per_topic_count.items():
    assert count == 10, f"topic {topic} must have 10 queries, has {count}"
