"""Auth-topic synthetic memories.

50 memories about OAuth 2.1, JWT, RBAC, scope filtering, and the
memory-hub auth service architecture.
"""

FOCUS_STRING = (
    "OAuth 2.1, JWT signing and verification, RBAC enforcement, scope filtering, "
    "session authentication, API keys, and authorization servers"
)

MEMORIES = [
    {
        "content": "MemoryHub OAuth 2.1 Authorization Server runs as a separate service from the MCP server, not inline. Three grant types: client_credentials, authorization_code+PKCE, and token_exchange (RFC 8693).",
        "weight": 0.95,
    },
    {
        "content": "JWT signing in memoryhub-auth uses RSA-2048 keys. Public keys are exposed via /.well-known/jwks.json. The MCP server's JWTVerifier fetches the JWKS at startup and on key rotation.",
        "weight": 0.9,
    },
    {
        "content": "RBAC scopes in MemoryHub are crossed: operational scopes (memory:read, memory:write, memory:admin) crossed with access tiers (user, project, organizational, enterprise).",
        "weight": 0.95,
    },
    {
        "content": "register_session is a JWT compatibility shim, not the primary auth path. When AUTH_JWKS_URI is set, the MCP server validates JWTs and ignores session-based registration.",
        "weight": 0.9,
    },
    {
        "content": "API key format for dev sessions: mh-dev-<username>-<year>. Keys are matched against a hardcoded users dict in src/tools/auth.py. Production replaces this with the OAuth flow.",
        "weight": 0.85,
    },
    {
        "content": "All 12 MCP tools enforce authorization via core/authz.py. authorize_read, authorize_write, and get_claims_from_context (JWT-first, session-fallback) are the entry points.",
        "weight": 0.9,
    },
    {
        "content": "search_memory uses SQL-level scope filtering for RBAC. Authorized scopes are passed into the query as a WHERE clause; unauthorized scopes never reach the result set, never paginated.",
        "weight": 0.9,
    },
    {
        "content": "Cross-reference tools (get_similar_memories, get_relationships) do post-fetch filtering with omitted_count. SQL-level filtering doesn't apply because the cross-reference traversal happens after the initial fetch.",
        "weight": 0.85,
    },
    {
        "content": "build_authorized_scopes converts JWT scopes into a dict mapping scope_name → required_owner_id. The dict drives the SQL filter; an empty dict means no scopes are authorized and the query short-circuits.",
        "weight": 0.85,
    },
    {
        "content": "FastMCP JWTVerifier validates incoming tokens but does not reject unauthenticated requests. Service-layer enforcement in core/authz.py handles rejection. The verifier's job is signature + expiry only.",
        "weight": 0.85,
    },
    {
        "content": "JWT short-lived tokens (5-15 minutes) with refresh token rotation. Refresh tokens are DB-backed in the oauth_clients table; rotation invalidates the previous refresh token immediately.",
        "weight": 0.9,
    },
    {
        "content": "TenantID lives in JWT claims for multi-tenant isolation. The tenant_id maps to a project scope; cross-tenant access requires explicit authorization at the enterprise tier.",
        "weight": 0.85,
    },
    {
        "content": "Session-based auth normalizes scopes: access-tier scopes from the API key are converted to operational scopes (memory:read:user, memory:write:user) at session register time.",
        "weight": 0.85,
    },
    {
        "content": "Access tiers form a hierarchy: enterprise > organizational > project > role > user. Higher tiers see lower-tier memories; lower tiers don't see higher-tier memories.",
        "weight": 0.85,
    },
    {
        "content": "OAuth 2.1 dropped support for the implicit flow and password grant. Use authorization_code with PKCE for browser flows; client_credentials for server-to-server. Don't try to use password grant for new code.",
        "weight": 0.9,
    },
    {
        "content": "PKCE (Proof Key for Code Exchange) is required for public clients in OAuth 2.1, recommended for confidential clients. Generates a code_verifier and code_challenge to prevent code interception attacks.",
        "weight": 0.85,
    },
    {
        "content": "memoryhub-auth deployment route: auth-server-memoryhub-auth.apps.cluster-n7pd5. Token endpoint: POST /token. JWKS: GET /.well-known/jwks.json. Discovery: /.well-known/oauth-authorization-server.",
        "weight": 0.85,
    },
    {
        "content": "RFC 8693 token exchange enables platform-integrated agents on RHOAI/K8s. ServiceAccount token → MemoryHub JWT via /token with grant_type=urn:ietf:params:oauth:grant-type:token-exchange.",
        "weight": 0.85,
    },
    {
        "content": "JWTs include 'sub' (subject = user_id), 'name' (display name), 'scopes' (operational scopes), 'tenant_id', 'iss' (issuer URL), 'iat'/'exp' (issued/expires unix time).",
        "weight": 0.85,
    },
    {
        "content": "Bcrypt is the right choice for hashing OAuth client_secret values at rest. Use bcrypt.hashpw with a cost factor of at least 12; verify with bcrypt.checkpw.",
        "weight": 0.85,
    },
    {
        "content": "OAuth client_credentials grant: agent presents client_id + client_secret to /token, receives an access token. No user identity; the client itself is the principal.",
        "weight": 0.85,
    },
    {
        "content": "JWT validation order: signature → expiry → issuer → audience → scopes. Fail fast on signature mismatch; the other checks only matter if the signature is valid.",
        "weight": 0.85,
    },
    {
        "content": "Don't store JWTs in localStorage for browser apps. Use httpOnly cookies for the refresh token and keep the access token in memory only. Mitigates XSS exfiltration.",
        "weight": 0.85,
    },
    {
        "content": "JWKS endpoint should support rotation. Publish multiple keys with different 'kid' values; old keys stay valid until tokens signed with them expire. New tokens always use the latest key.",
        "weight": 0.85,
    },
    {
        "content": "OAuth 2.1 token endpoint requires Content-Type: application/x-www-form-urlencoded for token requests. JSON bodies are not part of the spec, even though some implementations accept them.",
        "weight": 0.85,
    },
    {
        "content": "Refresh tokens in memoryhub-auth are single-use. Each refresh issues a new access token AND a new refresh token; the old refresh token is invalidated. Detects token theft via reuse.",
        "weight": 0.9,
    },
    {
        "content": "Don't put PII or secrets in JWT claims. Claims are base64-encoded, not encrypted. Anyone with the token can read them. Use opaque tokens if you need confidential session state.",
        "weight": 0.9,
    },
    {
        "content": "MCP server reads AUTH_JWKS_URI at startup. If unset, falls back to session-based auth. If set but unreachable, the server fails to start with a clear error message about JWKS connectivity.",
        "weight": 0.85,
    },
    {
        "content": "Authorino is the OpenShift-native authz layer. memory-hub-mcp does not use Authorino; instead it does service-layer authz in core/authz.py because Authorino can't see scope-vs-owner relationships.",
        "weight": 0.85,
    },
    {
        "content": "OAuth scopes should be granular: memory:read:user is the right scope for user-tier reads. Lumping everything into a single 'memory' scope is too coarse and forces over-privileged tokens.",
        "weight": 0.85,
    },
    {
        "content": "Token introspection (RFC 7662) lets a resource server verify a token without holding the signing key. memoryhub-auth supports POST /introspect for cases where the resource server can't fetch JWKS.",
        "weight": 0.8,
    },
    {
        "content": "Use 'kid' (Key ID) in JWT headers to support key rotation. The verifier looks up the right public key from JWKS by kid. Without kid, you can't safely rotate keys without downtime.",
        "weight": 0.85,
    },
    {
        "content": "OAuth state parameter prevents CSRF on the authorization_code flow. Generate a random opaque string, store in session, verify on callback. Mismatched state means the callback is forged.",
        "weight": 0.85,
    },
    {
        "content": "JWT signing key for memoryhub-auth is loaded from a Kubernetes Secret at startup. The Secret has both the private key (for signing) and a kid label. Rotation rolls a new Secret and restarts the auth service.",
        "weight": 0.85,
    },
    {
        "content": "Don't accept the 'none' algorithm in JWT validation. Some libraries used to accept alg=none as a default; this allows trivial token forgery. Hardcode the allowed algorithms list.",
        "weight": 0.95,
    },
    {
        "content": "memory:admin scope grants curation rule and contradiction resolution access. memory:write doesn't include admin operations; the curation tools check for admin explicitly.",
        "weight": 0.85,
    },
    {
        "content": "OAuth 2.1 mandates HTTPS for all token endpoints in production. Plain HTTP is allowed only for localhost development. The token endpoint SHALL reject HTTP requests outside loopback.",
        "weight": 0.9,
    },
    {
        "content": "The authentication module at core/authz.py exposes authorize_read, authorize_write, get_claims_from_context, build_authorized_scopes, and AuthenticationError. All other auth code goes through these.",
        "weight": 0.85,
    },
    {
        "content": "When a tool fails authz, raise ToolError with a message that does NOT reveal which scope is missing. 'Unauthorized to read this scope' is fine; 'Missing memory:read:project' leaks scope topology.",
        "weight": 0.85,
    },
    {
        "content": "OAuth Authorization Server discovery document at /.well-known/oauth-authorization-server lists endpoints, supported grant types, supported scopes, JWKS URI. Clients should consume the discovery doc, not hardcode URLs.",
        "weight": 0.85,
    },
    {
        "content": "JWT 'aud' (audience) claim should be the resource server's URL. The resource server validates that aud matches its own identity, preventing token reuse against unintended servers.",
        "weight": 0.85,
    },
    {
        "content": "Database tables for OAuth: oauth_clients (client_id, hashed_secret, allowed_grant_types, allowed_scopes), refresh_tokens (token_id, client_id, expires_at, revoked_at). Migration 006 introduced these.",
        "weight": 0.8,
    },
    {
        "content": "OAuth client registration is an admin operation. Don't expose dynamic client registration without rate limiting and a quota; otherwise anyone can spawn unlimited clients.",
        "weight": 0.85,
    },
    {
        "content": "JWT validation libraries vary in defaults. PyJWT requires explicit options={'verify_aud': True}; jose validates aud by default. Always pass options explicitly to be safe.",
        "weight": 0.85,
    },
    {
        "content": "Service account JWTs in OpenShift have a fixed audience of the API server. To use them with token exchange, the auth service must be in the audience list or token exchange will reject them.",
        "weight": 0.8,
    },
    {
        "content": "Authorization checks must happen on the server, never trust client-provided scope claims. Even with JWT signing, the server should verify the token signature on every request, not cache the result.",
        "weight": 0.9,
    },
    {
        "content": "memoryhub-auth's /token endpoint supports both client_credentials and refresh_token grant types. The grant_type form field selects which path runs. Unknown grant_type returns 400 with unsupported_grant_type.",
        "weight": 0.8,
    },
    {
        "content": "The MCP server's authz module calls get_claims_from_context on every tool call. JWT-first means: if a JWT is present, use its claims; otherwise, fall back to session state from register_session.",
        "weight": 0.85,
    },
    {
        "content": "Token exchange grant subject_token + actor_token combination supports delegated authorization. The subject identifies the user; the actor identifies the service performing the action on behalf of the user.",
        "weight": 0.8,
    },
    {
        "content": "OAuth refresh tokens should expire (e.g., 30 days). Indefinite refresh tokens become a credential that's nearly impossible to revoke. Refresh expiry forces re-authentication periodically.",
        "weight": 0.85,
    },
]

assert len(MEMORIES) == 50, f"auth fixture must have 50 memories, has {len(MEMORIES)}"
