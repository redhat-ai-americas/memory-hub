# Constraints

These are the hard boundaries we're working within.

MemoryHub must be deployable to existing RHOAI clusters without requiring RHOAI source modifications. This is critical for the adoption path — if it requires a custom RHOAI build, nobody will touch it. It needs to deploy alongside RHOAI, use the same cluster resources, and integrate through standard interfaces.

FIPS compliance is required. This is a Red Hat enterprise environment, and many target customers are in regulated industries. Every component — the operator, the MCP server, the storage backends — needs to either be FIPS-compliant or have a path to compliance. We're not sure yet whether Milvus and Neo4j meet this bar (see risks.md).

All containers must use Red Hat UBI base images. No Alpine, no Debian, no "I found this image on Docker Hub." UBI9 for everything.

Storage backends: PostgreSQL (OOTB — the operator that ships with OpenShift, not Crunchy Data) with pgvector for vector search, PostgreSQL for graph queries initially (Apache AGE extension or adjacency list patterns), and MinIO for S3-compatible object storage (markdown files and documents). Two constraints drove these choices: no Crunchy Data (can't build on an external vendor product), and no OpenShift Data Foundation (not part of Red Hat AI Enterprise). The FIPS story is strong throughout: PostgreSQL delegates crypto to OS-level OpenSSL (FIPS-validated on RHEL), and pgvector uses mathematical distance computations — not cryptographic hashes — so it works cleanly in FIPS mode. MinIO AIStor has FIPS 140-3 mode via Go 1.24's validated crypto module and a Red Hat certified operator.

Grafana and Prometheus for observability. These are already present in OpenShift clusters and are the standard monitoring stack. We use what's there rather than introducing new tooling.

The system must be viable as a future upstream contribution to OpenShift AI. This means clean code, good documentation, and architectural decisions that align with how RHOAI is built. It also means not taking shortcuts that would embarrass us in a code review with the engineering team.

The RHOAI engineering team needs to see this working before adoption. Proof over proposals. A working demo on a real cluster is worth more than any architecture document. This constrains how we spend our time — building beats theorizing.

MCP server development will use the fips-agents CLI workflow: `/plan-tools` to design the tool surface, `/create-tools` to implement, `/exercise-tools` to test, `/deploy-mcp` to deploy. This keeps us consistent with other MCP servers in the ecosystem and gives us a proven development path.
