# MemoryHub Edition Comparison

MemoryHub ships in two editions. The **personal edition** (`memoryhub-local`) runs entirely on your laptop with no infrastructure. The **cluster edition** deploys to OpenShift with PostgreSQL, multi-tenant auth, and horizontal scaling. Both editions expose the same MCP tool surface -- agents cannot tell which one they're talking to.

## Storage and Search

| Feature | Personal | Cluster |
|---------|----------|---------|
| Database | SQLite (WAL mode) | PostgreSQL + pgvector |
| Vector search | sqlite-vec (brute-force KNN) | pgvector IVFFlat/HNSW |
| Full-text search | FTS5 | PostgreSQL tsvector |
| Object storage | N/A | MinIO (S3-compatible) |
| Content truncation | No (all inline) | Large content offloaded to S3 |
| Data location | `~/.local/share/memoryhub/` | Cluster PVCs |

## Embeddings

| Feature | Personal | Cluster |
|---------|----------|---------|
| Model | Granite Embedding Small English R2 | vLLM-compatible (configurable) |
| Runtime | ONNX on CPU | vLLM server (GPU) |
| Dimensions | 384 | Configurable |
| Download | ~200MB, automatic on first start | Server-managed |

## Memory Operations

| Feature | Personal | Cluster |
|---------|----------|---------|
| search | Yes | Yes |
| read | Yes | Yes |
| list | Yes | Yes |
| write | Yes | Yes |
| update (versioned) | Yes | Yes |
| delete (soft) | Yes | Yes |
| similar | Yes | Yes |
| relationships / relate | Yes | Yes |
| reconstruct | Yes | Yes |
| report (contradictions) | Yes | Yes |
| status | Yes | Yes |
| promote / graduate | Stub | Yes |
| checkpoint | Stub | Yes |
| set_focus | Stub | Yes |
| resolve (contradictions) | Stub | Yes |
| set_rule (curation) | Stub | Yes |
| create_project / members | Stub | Yes |
| entity management | Stub | Yes |

"Stub" means the action is accepted but returns a "not available in personal edition" message. No error is raised.

## Thread Operations

| Feature | Personal | Cluster |
|---------|----------|---------|
| create | Yes | Yes |
| append | Yes | Yes |
| get | Yes | Yes |
| list | Yes | Yes |
| archive | Yes | Yes |
| delete | Yes | Yes |
| extract | Yes (MCP sampling) | Yes (server-side LLM) |
| fork | Stub | Yes |
| share | Stub | Yes |

## Extraction

| Feature | Personal | Cluster |
|---------|----------|---------|
| In-session (MCP sampling) | Yes (agent's own LLM) | N/A |
| On-connect dreaming | Yes (via register_session) | Yes (server-side) |
| CLI extraction | `memoryhub dream` (Ollama / any OpenAI-compatible) | N/A |
| Server-side extraction | N/A | Gemini, vLLM, etc. |
| Windowed processing | Yes | Yes |
| Dedup / reconciliation | Yes | Yes |

## Auth and Multi-tenancy

| Feature | Personal | Cluster |
|---------|----------|---------|
| Authentication | None (single user) | API keys + JWT (JWKS) |
| API keys | Not needed | Required |
| Multi-tenancy | No | Yes (tenant isolation) |
| Owner isolation | No (single owner) | Yes |
| Scopes accepted | All | All |
| Scopes enforced | user, project | All (user through enterprise) |

## Curation and Governance

| Feature | Personal | Cluster |
|---------|----------|---------|
| Admin search | Yes | Yes (cross-tenant) |
| Quarantine / restore | Yes | Yes |
| Hard delete | Yes | Yes |
| Curation rules | Stub | Configurable (dedup, routing, gating) |
| Promotion workflow | Stub | Cross-scope promotion |
| Knowledge graduation | Stub | Experiential to knowledge |

## Deployment

| Feature | Personal | Cluster |
|---------|----------|---------|
| Install | `pip install "memoryhub[local]"` | OpenShift manifests |
| Infrastructure | None | PostgreSQL, MinIO, Valkey, OpenShift |
| Configuration | Zero-config | Multi-namespace, Alembic, Kustomize |
| Scaling | Single process | Horizontal (replicas behind Service) |
| FIPS compliance | No | Yes |
