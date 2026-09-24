# Local Development

MemoryHub has two shipped editions and three useful development paths:

1. **Personal edition** — SQLite-backed, no infrastructure, and stdio MCP.
2. **Local full-stack mode** — the cluster edition's governed PostgreSQL stack
   running on a laptop with Compose, an HTTP MCP server, and the dashboard UI.
3. **Cluster edition** — the complete OpenShift deployment described in the
   [cluster install guide](cluster-install.md).

Local full-stack mode is a development mode of the cluster edition. It is not
a third product edition.

## Prerequisites

- Python 3.11+
- Git
- Docker Compose or Podman Compose
- Node.js 20+ and npm when using the Vite development server

## Personal edition

Use the personal edition when you need a lightweight, single-user setup:

```bash
pip install "memoryhub[local]"
claude mcp add memoryhub -- memoryhub mcp
```

This edition stores memories in SQLite and runs MCP over stdio. It does not
start PostgreSQL, the dashboard, or the governed cluster services.

## Local full-stack mode

The root Makefile manages a persistent PostgreSQL + pgvector database, the MCP
server in streamable-HTTP mode, and the dashboard BFF serving the built React
frontend.

```bash
make local-install
```

The command:

1. Creates the root Python environment when needed.
2. Prepares the MCP and UI build contexts.
3. Starts PostgreSQL with a persistent named volume.
4. Runs the Alembic migrations.
5. Builds and starts the MCP HTTP service.
6. Builds and starts the UI BFF and frontend.

The services are available at:

| Service | URL |
| --- | --- |
| Dashboard | http://localhost:8080 |
| MCP | http://localhost:18080/mcp/ |
| PostgreSQL | localhost:5432 |

After the first setup, use:

```bash
make local-up
make local-logs
make local-down
```

`make local-down` removes the containers but preserves the
`memoryhub-local-postgres` volume. Data therefore survives an up/down cycle.

The local Compose file is `compose.yaml`. The stack uses the example user
configuration at `memory-hub-mcp/dev-users.example.json`; it is suitable for
development only.

When running the MCP process directly, copy the example file first if you want
to use your own local API keys:

```bash
cp memory-hub-mcp/dev-users.example.json memory-hub-mcp/dev-users.json
```

### Optional local auth service

The default local stack does not require OAuth SSO. The dashboard remains
usable without the auth service, while the Clients panel reports that auth is
not configured.

To start the optional auth container:

```bash
make local-auth-up
```

This runs the auth migrations and starts the service at `http://localhost:18081`.

Valkey is also available as an optional Compose profile for queue and
notification development:

```bash
podman compose --profile valkey -f compose.yaml up -d valkey
```

### Vite development mode

For frontend development with hot reload, keep the local BFF running on port
8080 and start Vite separately:

```bash
cd memoryhub-ui/frontend
npm install
npm run dev
```

Vite listens on port 3000 and proxies `/api` to the local BFF at
`http://localhost:8080`.

The default Compose UI service uses the pre-built frontend served by the BFF.
This is the single-process mode used when no Vite development server is
needed.

### Local MCP HTTP mode without Compose

The MCP project also exposes a direct local HTTP target:

```bash
cd memory-hub-mcp
make run-local-http
```

Set the normal `MEMORYHUB_DB_*` variables first if the database is not being
provided by the local Compose stack.

## Integration tests

The integration test Compose file remains intentionally ephemeral: it uses
tmpfs for PostgreSQL and Valkey so test runs do not retain state.

```bash
podman compose -f tests/integration/compose.yaml up -d
make test-integration
podman compose -f tests/integration/compose.yaml down
```

Use `docker compose` instead when Docker is the local container runtime.
Development uses the persistent root `compose.yaml`; integration tests use a
separate disposable database.

## Cluster edition

For the full OpenShift deployment, see the [cluster install guide](cluster-install.md).
The cluster path includes PostgreSQL, MinIO, Valkey, embedding and reranker
models, the auth service, the MCP server, and the dashboard UI.
