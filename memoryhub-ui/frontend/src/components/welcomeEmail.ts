/**
 * Welcome email body renderer.
 *
 * Pure function — takes the details of a newly-created (or freshly-rotated)
 * OAuth client and returns a formatted plain-text email body the maintainer
 * can copy and paste into their email client.
 *
 * The email is intentionally plain text, not HTML, because:
 *   1. It copies cleanly into every email client without losing formatting.
 *   2. Monospace rendering of credentials is preserved.
 *   3. New contributors aren't surprised by invisible HTML fluff.
 *
 * If clientSecret is null (e.g., when re-viewing an existing client whose
 * secret has already been shown), the template substitutes a placeholder
 * and adds a reminder line telling the maintainer to rotate and deliver
 * the secret separately.
 *
 * This is the MVP implementation documented in docs/inviting-new-contributors.md.
 * The follow-up tracked elsewhere automates the delivery channel so secrets
 * don't travel over plain email.
 */

export interface WelcomeEmailParams {
  clientId: string;
  clientName: string;
  clientSecret: string | null;
  tenantId: string;
  scopes: string[];
  mcpUrl: string;
  authUrl: string;
  /** Optional — the maintainer's first name for the signoff. Defaults to "The MemoryHub team". */
  maintainerName?: string;
}

const DOCS_URL = 'https://github.com/redhat-ai-americas/memory-hub';
const CONTRIBUTING_URL = 'https://github.com/redhat-ai-americas/memory-hub/blob/main/CONTRIBUTING.md';
const CLUSTER_ACCESS_DOC = 'https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/contributor-cluster-access.md';

const SECRET_PLACEHOLDER = '<ask the maintainer — rotate via the dashboard>';

export function renderWelcomeEmail(params: WelcomeEmailParams): string {
  const {
    clientId,
    clientName,
    clientSecret,
    tenantId,
    scopes,
    mcpUrl,
    authUrl,
    maintainerName,
  } = params;

  const signoff = maintainerName ? `— ${maintainerName}` : '— The MemoryHub team';
  const secret = clientSecret ?? SECRET_PLACEHOLDER;
  const secretNote = clientSecret
    ? 'Keep this secret somewhere safe (a password manager is ideal). It will not be shown again — if you lose it, ask me to rotate it.'
    : 'The secret was generated when your client was originally created and is not retrievable. If you need a new one, reply to this email and I will rotate it.';

  return `Subject: Welcome to MemoryHub — your credentials are attached

Hi,

Welcome to MemoryHub. You've been provisioned as an OAuth 2.1 client on
our demo deployment so you can start exercising the memory layer from
your agents, scripts, or the SDK.

Your credentials
----------------
  Client ID:      ${clientId}
  Client name:    ${clientName}
  Tenant:         ${tenantId}
  Scopes:         ${scopes.join(', ') || '(none)'}
  Client secret:  ${secret}

${secretNote}

How to use it
-------------
The MemoryHub auth server issues short-lived JWTs via the OAuth 2.1
client_credentials grant. Request a token with:

  curl -X POST ${authUrl}/token \\
    -d 'grant_type=client_credentials' \\
    -d 'client_id=${clientId}' \\
    -d "client_secret=$MEMORYHUB_CLIENT_SECRET"

The returned access_token is a JWT. Pass it as a bearer token on requests
to the MCP server:

  MCP endpoint: ${mcpUrl}

If you're using the Python SDK (pip install memoryhub), export the
credentials as environment variables and the SDK will handle the token
dance for you:

  export MEMORYHUB_URL=${mcpUrl}
  export MEMORYHUB_AUTH_URL=${authUrl}
  export MEMORYHUB_CLIENT_ID=${clientId}
  export MEMORYHUB_CLIENT_SECRET='<your secret>'

  python -c 'import asyncio; from memoryhub import MemoryHubClient; \\
    asyncio.run((lambda: print("ok"))())'

Then open ${CONTRIBUTING_URL}
for the local dev setup, coding conventions, and PR flow.

Cluster access
--------------
Most contributions don't need OpenShift cluster access at all — local
development against SQLite or a podman-run PostgreSQL is enough. If you
do need cluster access (to read logs or reproduce deploy-specific
behavior), the policy is in:

  ${CLUSTER_ACCESS_DOC}

The short version: log in with your GitHub account at the cluster's
OpenShift console. Your GitHub org membership handles authorization
automatically.

Where to find everything else
-----------------------------
  Repo:          ${DOCS_URL}
  Contributing:  ${CONTRIBUTING_URL}
  Cluster access: ${CLUSTER_ACCESS_DOC}

If you hit a wall, reply to this email or ping me directly. Welcome
aboard.

${signoff}
`;
}
