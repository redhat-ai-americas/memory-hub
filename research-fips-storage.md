# FIPS 140-2/140-3 Compliance Research: Database and Storage Options for OpenShift

**Date:** 2026-04-03
**Context:** MemoryHub on Red Hat OpenShift AI
**Purpose:** Evaluate FIPS compliance status of database and storage technologies for production enterprise deployment

---

## Executive Summary and Recommendation

For a FIPS-compliant MemoryHub deployment on OpenShift AI, the recommended stack is:

1. **Crunchy Data PostgreSQL Operator + pgvector + Apache AGE** as a consolidated database for both vector search and graph queries. Crunchy Data is Red Hat certified, has a DISA STIG, Common Criteria EAL 2+ certification, and pgvector is included in their container images (v0.8.0). PostgreSQL's FIPS story is the strongest of any option here because it delegates all cryptography to the OS-level OpenSSL, which is FIPS-validated on RHEL/RHCOS.

2. **OpenShift Data Foundation (ODF)** for S3-compatible object storage instead of MinIO. ODF is designed for FIPS, uses RHEL's FIPS-validated cryptographic modules when the cluster is in FIPS mode, and supports encryption at rest with LUKS2 and external KMS (HashiCorp Vault). It is fully Red Hat supported.

3. If a dedicated vector database is absolutely required (for performance at scale beyond what pgvector can handle), **MinIO AIStor** is the strongest FIPS option among the non-PostgreSQL choices, with explicit FIPS 140-3 mode using Go 1.24's validated crypto module. For the vector DB itself, none of the dedicated options (Milvus, Qdrant, Weaviate) have FIPS validation; pgvector remains the safest path.

4. **Neo4j Enterprise** (5.23.0+) is the only graph database with explicit FIPS 140-2 compatibility documentation, but it is Enterprise-only, not Red Hat certified, and requires careful configuration (netty-tcnative + system OpenSSL). Apache AGE on PostgreSQL is a simpler, more FIPS-friendly path if its graph query capabilities are sufficient.

---

## Final Decisions

**Decided stack for MemoryHub (as of 2026-04-03):**

- **Vector search:** PostgreSQL (OOTB) + pgvector. OOTB is the PostgreSQL operator that ships with OpenShift — not Crunchy Data.
- **Graph queries:** PostgreSQL initially, via Apache AGE (openCypher) or adjacency list table patterns. Evolution path to a dedicated graph database or an in-process graph library (petgraph in Rust, with PostgreSQL as durable store) if graph complexity demands it.
- **Object storage:** MinIO. S3-compatible, Red Hat certified operator, FIPS 140-3 mode available via Go 1.24's validated crypto module.

**Ruled out and why:**

- **Crunchy Data PostgreSQL Operator:** Eliminated despite its strong FIPS credentials and pgvector support. MemoryHub cannot build on an external vendor product; OOTB (the operator Red Hat ships with OpenShift) is the appropriate foundation.
- **OpenShift Data Foundation (ODF):** Eliminated because ODF is not part of Red Hat AI Enterprise. The research recommendation to use ODF over MinIO was sound from a pure FIPS perspective, but ODF isn't available in the target deployment environment.
- **Milvus:** Eliminated. No encryption at rest, bcrypt authentication (not FIPS-approved), no Red Hat certified operator, no FIPS validation.
- **Neo4j Enterprise:** Eliminated. No certified OpenShift operator, Enterprise license required, complex FIPS configuration (requires non-native auth, specific netty-tcnative setup).

**Why the FIPS story is still strong with this stack:** PostgreSQL delegates all cryptography to the OS-level OpenSSL, which is FIPS-validated on RHEL/RHCOS — this holds regardless of which operator deploys it. pgvector computes vector distances using mathematical operations (L2, cosine, inner product), not cryptographic hash functions, so it is unaffected by FIPS restrictions. MinIO AIStor's FIPS mode uses Go 1.24's FIPS 140-3 validated crypto module. The consolidated picture: two storage systems (PostgreSQL + MinIO) instead of three, both with clear FIPS paths, both with Red Hat certified operators.

---

## Comparison Table

| Technology | FIPS Status | Encryption at Rest | Encryption in Transit | OCP Operator (Certified?) | BYOK/CMK | Red Hat Certified | Known FIPS Issues |
|---|---|---|---|---|---|---|---|
| **Crunchy PostgreSQL + pgvector** | Compatible (delegates to OS OpenSSL) | Via OS/storage-level encryption | TLS (native) | Yes (Red Hat Certified) | Via storage layer | Yes | PG < 14: MD5 auth issues in FIPS; PG 18 adds fips_mode() function |
| **Apache AGE (on PostgreSQL)** | Compatible (inherits from PG) | Via OS/storage-level encryption | TLS (inherits from PG) | Via Crunchy operator | Via storage layer | Via Crunchy | No known independent issues |
| **Neo4j Enterprise** | Compatible (5.23.0+, Enterprise only) | Application-level not built-in | TLS via netty-tcnative + OpenSSL | No certified operator (Helm only) | No native BYOK | No | Requires non-native auth (LDAP/SSO); Linux only; complex config |
| **Milvus** | Unknown/Not validated | Not natively supported (feature requested) | TLS (one-way or two-way) | No certified operator (Helm + custom operator) | No | No | Written in Go; bcrypt auth not FIPS-approved; no encryption-at-rest |
| **Qdrant** | Unknown/Not validated | Cloud-managed only (self-hosted: none by default) | TLS (requires manual config) | No certified operator (Helm) | Cloud-managed premium only | No | Written in Rust; no FIPS documentation; no default security |
| **Weaviate** | Unknown/Not validated | AES-256 (managed cloud) | TLS | No certified operator (Helm + community operator) | Managed cloud only | No | Written in Go; SOC2/HIPAA but no FIPS |
| **Redis Enterprise** | Compatible (delegates to OS) | Via OS filesystem encryption | TLS (native) | Yes (Red Hat Certified) | Cloud-managed only | Yes | No own FIPS module; relies entirely on OS; DISA STIG available |
| **MinIO AIStor** | FIPS 140-3 mode (Go 1.24 module) | AES-256-GCM (DARE) | TLS (AES-GCM suites only in FIPS mode) | Yes (Red Hat Certified) | Yes (KES + external KMS: Vault, AWS KMS, Azure, GCP) | Yes | Disclaimer: "no statements regarding FIPS certification status"; EdDSA certs incompatible |
| **OpenShift Data Foundation** | Designed for FIPS (uses RHEL validated modules) | LUKS2 (AES-XTS-Plain64, 512-bit) | TLS | Yes (Red Hat native) | Yes (HashiCorp Vault KMS) | Yes (Red Hat product) | FIPS must be enabled at OCP install time; RHCOS required |

---

## Detailed Findings

### 1. Milvus (Vector Database)

**FIPS Status: Unknown / Not Validated**

- Milvus is written in Go. With Go 1.24+, the Go crypto module has FIPS 140-3 validation, but Milvus itself has not been validated or tested in FIPS mode.
- Milvus uses bcrypt for authentication, which is **not FIPS 140-approved**. There is an [open GitHub issue (#44087)](https://github.com/milvus-io/milvus/issues/44087) requesting use of industry-standard crypto libraries.
- **Encryption at rest:** Not natively supported. An [open feature request (#33810)](https://github.com/milvus-io/milvus/issues/33810) exists for encryption at rest.
- **Encryption in transit:** TLS supported (one-way and two-way authentication modes).
- **OpenShift Operator:** No Red Hat certified operator. Deployment is via the [Zilliz Milvus Operator](https://github.com/zilliztech/milvus-operator) installed through Helm. There is [official documentation for OpenShift deployment](https://milvus.io/docs/openshift.md).
- **BYOK:** No native support. Zilliz Cloud (managed) uses cloud provider KMS.
- **Red Hat integration:** Used by Red Hat's llm-on-openshift examples and referenced in OpenShift AI RAG documentation, but not a certified/supported component.

**Assessment:** High risk for FIPS environments. No encryption at rest, non-FIPS auth, no validation.

### 2. Neo4j (Graph Database)

**FIPS Status: Compatible (Enterprise 5.23.0+, with significant configuration)**

- Neo4j Enterprise 5.23.0+ has [official FIPS 140-2 compatibility documentation](https://neo4j.com/docs/operations-manual/current/security/ssl-fips-compatibility/).
- **Requirements for FIPS mode:**
  - Enterprise Edition only (Community Edition does not support FIPS)
  - Linux only
  - Must use dynamically linked netty-tcnative with FIPS-certified OpenSSL (not BoringSSL)
  - Must use non-native authentication (LDAP or SSO; native auth not supported)
  - Private keys must be password-protected
  - Set `dbms.netty.ssl.provider=OPENSSL`
- **Encryption at rest:** Not natively provided by Neo4j; relies on OS/storage-level encryption.
- **Encryption in transit:** TLS 1.2/1.3 with configurable FIPS-compliant cipher suites (ECDHE/DHE-based for TLS 1.2; AES-GCM for TLS 1.3).
- **OpenShift Operator:** No Red Hat certified operator. A [Kubernetes operator exists](https://github.com/neo4j-partners/neo4j-kubernetes-operator) but is **alpha stage** and not recommended for production. Helm charts (neo4j/neo4j) are the supported deployment method and include OpenShift Route support.
- **BYOK:** No native key management; relies on infrastructure-level encryption.
- **Known issues:** [Issue #12799](https://github.com/neo4j/neo4j/issues/12799) documented FIPS startup failures in Neo4j 4.3.x on FIPS-enabled OpenShift, resolved in later versions with the FIPS compatibility guide.

**Assessment:** Viable for FIPS if Enterprise licensing is acceptable, but operational complexity is high. No certified operator is a gap for OpenShift.

### 3. PostgreSQL with pgvector

**FIPS Status: Compatible (strongest FIPS story among all options)**

- PostgreSQL delegates all cryptography to the system's OpenSSL library. When running on FIPS-enabled RHEL/RHCOS, PostgreSQL automatically uses FIPS-validated crypto modules.
- **PostgreSQL 18** (2025) added the `fips_mode()` function to report FIPS mode status and added the `builtin_crypto_enabled` server variable to pgcrypto for disabling non-FIPS built-in functions.
- **pgvector specifically:** pgvector performs vector similarity computations (L2 distance, inner product, cosine distance) using mathematical operations, **not cryptographic hash functions**. It does not use MD5, SHA, or any cryptographic primitives. pgvector should work without issues in FIPS mode.
- **MD5 authentication caveat:** PostgreSQL's MD5 password authentication fails in FIPS mode (MD5 is not FIPS-approved). Use SCRAM-SHA-256 authentication instead (default since PostgreSQL 14).
- **Encryption at rest:** Via OS/storage-level (LUKS, dm-crypt, ODF encryption).
- **Encryption in transit:** Native TLS support.
- **BYOK:** Via storage layer (ODF with Vault, or cloud provider KMS).
- **Crunchy Data's FIPS posture:** DISA STIG available, Common Criteria EAL 2+ certified, used widely in U.S. federal government deployments.

**Assessment:** The safest FIPS path. PostgreSQL's "no internal crypto, use the OS" design is ideal for FIPS compliance.

### 4. Redis Enterprise with Vector Search

**FIPS Status: Compatible (delegates to OS; DISA STIG available)**

- Redis Enterprise does **not include its own FIPS 140-2 validated cryptographic module**. It relies entirely on the underlying OS for FIPS compliance.
- A [DISA STIG exists for Redis Enterprise 6.x](https://ncp.nist.gov/checklist/1013) with specific requirements for FIPS-validated crypto modules.
- FIPS is "supported only if FIPS was enabled during RHEL installation."
- **Encryption at rest:** Via OS transparent filesystem encryption. Not built into Redis itself.
- **Encryption in transit:** TLS supported natively. Internode encryption enabled by default for control plane.
- **OpenShift Operator:** Yes, [Red Hat Certified operator](https://catalog.redhat.com/software/operators/detail/5e98728d3f398525a0ceafb9) available in OperatorHub.
- **BYOK:** Available on managed cloud platforms (Azure, AWS). For self-managed, relies on OS/storage encryption.
- **Vector search:** RediSearch module provides vector similarity search capabilities.
- **Known issues:** OpenSSL 1.1 compatibility issues between RediSearch module and clusters on certain platforms (Amazon Linux 2).

**Assessment:** Reasonable FIPS option with certified operator, but vector search capabilities are secondary to Redis's primary cache/data structure role. The "no own crypto module" approach is actually good for FIPS (same approach as PostgreSQL).

### 5. Qdrant (Vector Database)

**FIPS Status: Unknown / Not Validated**

- Written in Rust. No FIPS documentation or claims from Qdrant.
- By default, Qdrant starts with **no encryption or authentication** in self-hosted deployments.
- **Encryption at rest:** Only available in Qdrant Managed Cloud (all storage volumes encrypted). Not available in self-hosted by default.
- **Encryption in transit:** TLS available but requires manual configuration.
- **OpenShift Operator:** No certified operator. Community [Kubernetes operator](https://github.com/qdrant-operator/qdrant-operator) and Helm charts available. Enterprise operator available through Qdrant Private Cloud/Hybrid Cloud.
- **BYOK:** Premium managed cloud customers can bring their own encryption keys for storage volumes.
- **Certifications:** SOC2 Type 2 and HIPAA certified (managed cloud).
- **Red Hat partnership:** Qdrant Hybrid Cloud was announced with Red Hat OpenShift support.

**Assessment:** Not suitable for FIPS-regulated environments without significant custom work. No FIPS validation path, no default security in self-hosted mode.

### 6. Weaviate (Vector Database)

**FIPS Status: Unknown / Not Validated**

- Written in Go. Could theoretically benefit from Go 1.24's FIPS module, but Weaviate has not documented or validated FIPS compatibility.
- **Encryption at rest:** AES-256 in managed cloud deployments.
- **Encryption in transit:** TLS supported.
- **OpenShift Operator:** No certified operator. Community [Kubernetes operator](https://github.com/weaviate/weaviate-operator) (wraps Helm chart) and [Helm charts](https://github.com/weaviate/weaviate-helm) available.
- **BYOK:** Managed cloud only.
- **Certifications:** SOC2 Type 2 and HIPAA certified.
- **Red Hat integration:** [Red Hat blog post](https://www.redhat.com/en/blog/building-powerful-applications-weaviate-and-red-hat-openshift-retrieval-augmented-generation-workflow) on deploying Weaviate on OpenShift for RAG workflows.

**Assessment:** Similar to Qdrant -- not validated for FIPS, though the Go runtime provides a theoretical path. Not recommended for FIPS-regulated production.

### 7. MinIO AIStor (S3-Compatible Object Storage)

**FIPS Status: FIPS 140-3 mode available (with disclaimer)**

- MinIO AIStor uses [Go 1.24's native FIPS 140-3 cryptographic module](https://docs.min.io/enterprise/aistor-object-store/installation/kubernetes/fips-mode/). FIPS mode is enabled at runtime via `GODEBUG=fips140=on`.
- **Important caveat:** MinIO explicitly states: *"MinIO makes no statements or representations regarding FIPS 140-3 certification status."* They use a validated module but do not claim the product itself is validated.
- **FIPS mode specifics:**
  - TLS: AES-128-GCM and AES-256-GCM only (CHACHA20-POLY1305 excluded)
  - Object encryption (DARE): AES-256-GCM exclusively
  - SSH/SFTP: Weak key exchange algorithms excluded
  - JWT: FIPS-validated SHA3 implementations
  - EdDSA/Ed25519 certificates incompatible
- **Encryption at rest:** Data At Rest Encryption (DARE) with AES-256-GCM.
- **Encryption in transit:** TLS with FIPS-compliant cipher suites.
- **OpenShift Operator:** Yes, [Red Hat Certified operator](https://min.io/docs/minio/kubernetes/openshift/index.html) available in OperatorHub. FIPS mode requires Operator RELEASE.2025-12-16T20-51-03Z or later.
- **BYOK:** Yes. MinIO KES (Key Encryption Service) integrates with HashiCorp Vault, AWS KMS, Azure Key Vault, GCP KMS, and MinKMS. Each object gets a unique encryption key wrapped by the KMS-managed master key.

**Assessment:** The strongest FIPS option for S3-compatible storage outside of ODF. The "no certification claim" disclaimer is a risk for strict compliance but the technical implementation is sound. Consider ODF instead for full Red Hat support.

### 8. Apache AGE (PostgreSQL Graph Extension)

**FIPS Status: Compatible (inherits from PostgreSQL)**

- Apache AGE is a PostgreSQL extension that adds graph database functionality with openCypher query support.
- **No independent cryptographic operations.** AGE inherits all security properties from the underlying PostgreSQL instance.
- Supports PostgreSQL 11-18.
- **Encryption:** Entirely inherited from PostgreSQL (TLS for transit, OS-level for rest).
- **OpenShift deployment:** Can be deployed via Crunchy Data PostgreSQL operator by adding AGE as a custom extension, or via custom PostgreSQL container images.
- **BYOK:** Via PostgreSQL/storage layer.
- **Community maturity:** Apache incubator project. Less mature than Neo4j for complex graph workloads, but sufficient for relationship traversal and basic graph queries.

**Assessment:** Excellent FIPS choice because it adds zero crypto surface area. The ability to run vector (pgvector) AND graph (AGE) queries on a single PostgreSQL instance is a significant architectural simplification for FIPS compliance. The main question is whether AGE's graph capabilities are sufficient for MemoryHub's needs.

### 9. Crunchy Data PostgreSQL Operator

**FIPS Status: Compatible (strongest operator-level FIPS posture)**

- [Red Hat Certified operator](https://catalog.redhat.com/en/software/containers/crunchydata/postgres-operator/5c78066cecb5240adfaaeaa3) available in OperatorHub.
- Achieved "autopilot" capability level certification (highest level).
- **pgvector support:** Yes, pgvector 0.8.0 included in container images for PostgreSQL 13-18 (as of PGO v5.8.3+).
- **FIPS credentials:**
  - DISA STIG for Crunchy Data PostgreSQL
  - Common Criteria EAL 2+ certification (first open source RDBMS to achieve this)
  - Widely deployed in U.S. federal government
  - PostgreSQL STIG requires FIPS-compliant OpenSSL on the OS
- **Extensions available:** pgvector, PostGIS, pgAudit, pg_cron, TimescaleDB, wal2json, pg_parquet, and many others.
- **HA/DR:** Built-in high availability with automatic failover, pgBackRest for backup/restore.

**Assessment:** The recommended PostgreSQL operator for FIPS-regulated OpenShift deployments. Strong certification pedigree, pgvector included, Red Hat certified.

---

## OpenShift Data Foundation (ODF) as MinIO Replacement

**FIPS Status: Designed for FIPS**

ODF is a strong candidate to replace MinIO for S3-compatible object storage in FIPS environments:

- When running on a FIPS-enabled OpenShift cluster, ODF uses [RHEL's FIPS-validated cryptographic modules](https://docs.redhat.com/en/documentation/red_hat_openshift_data_foundation/4.15/html/planning_your_deployment/security-considerations_rhodf).
- **Encryption at rest:** LUKS v2 with AES-XTS-Plain64 cipher, 512-bit keys. Each device gets a unique encryption key.
- **KMS support:** HashiCorp Vault (KV v1 and v2). Thales CipherTrust Manager added in ODF 4.12.
- **S3 API:** Two implementations:
  - Ceph Object Gateway (RGW): Native Ceph object storage, scales to petabytes
  - NooBaa/Multicloud Object Gateway (MCG): Multi-cloud data federation with S3 API
- **Requirements:** FIPS must be enabled at OpenShift install time. RHCOS nodes required (not RHEL 7).

**Trade-offs vs MinIO:**
- ODF is heavier (requires minimum 3 nodes with storage).
- MinIO is simpler to deploy for small-scale use.
- ODF provides unified block, file, and object storage.
- ODF is fully Red Hat supported with FIPS validation through the OS stack.

**Recommendation:** Use ODF if the cluster has sufficient resources. Use MinIO AIStor with FIPS mode if ODF is too heavy for the deployment size.

---

## FIPS-Validated Graph Database for Kubernetes

There is **no FIPS-validated graph database** purpose-built for Kubernetes. The options are:

1. **Neo4j Enterprise 5.23.0+** -- FIPS compatible but not validated, Enterprise license required, no certified operator.
2. **Apache AGE on PostgreSQL** -- inherits PostgreSQL's FIPS-compatible posture, can run on certified Crunchy operator. Not a full graph database but supports openCypher queries.
3. **Amazon Neptune / Azure Cosmos DB (Gremlin)** -- managed cloud services with FIPS, but not self-hosted on OpenShift.

**Recommendation for MemoryHub:** Apache AGE on Crunchy Data PostgreSQL is the pragmatic choice. It provides graph query capability within the FIPS-validated PostgreSQL ecosystem without introducing a separate database requiring its own FIPS evaluation.

---

## Recommended Architecture for MemoryHub on OpenShift AI

```
┌─────────────────────────────────────────────────┐
│              OpenShift (FIPS mode)               │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  Crunchy Data PostgreSQL Operator (PGO)  │   │
│  │  ┌─────────────┐  ┌──────────────────┐  │   │
│  │  │  pgvector    │  │  Apache AGE      │  │   │
│  │  │  (vectors)   │  │  (graph queries) │  │   │
│  │  └─────────────┘  └──────────────────┘  │   │
│  │  PostgreSQL 17+ on RHEL 9 / FIPS OpenSSL │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  OpenShift Data Foundation (ODF)         │   │
│  │  S3 API (Ceph RGW or NooBaa)            │   │
│  │  LUKS2 encryption + Vault KMS           │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  Redis Enterprise (optional: caching)    │   │
│  │  Certified operator, OS-level FIPS       │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
└─────────────────────────────────────────────────┘
```

**Key decisions:**
- Single PostgreSQL instance with pgvector + AGE reduces the FIPS attack surface to one database engine.
- ODF for object storage eliminates the need for a separate MinIO deployment and is fully Red Hat supported.
- Redis Enterprise (optional) only if caching performance requires it; its certified operator and OS-level FIPS delegation make it low-risk.
- Avoid dedicated vector databases (Milvus, Qdrant, Weaviate) in FIPS environments -- none are validated and all introduce uncontrolled crypto surface area.

---

## Sources

- [Red Hat OpenShift FIPS Compliance FAQ](https://access.redhat.com/articles/openshift_fips_compliance_faq)
- [Red Hat OpenShift AI: Designed for FIPS](https://www.redhat.com/en/blog/red-hat-openshift-ai-designed-fips-delivering-trust-and-innovation)
- [Neo4j FIPS 140-2 Compatibility Guide](https://neo4j.com/docs/operations-manual/current/security/ssl-fips-compatibility/)
- [Neo4j FIPS Startup Issue #12799](https://github.com/neo4j/neo4j/issues/12799)
- [PostgreSQL and FIPS Mode (Peter Eisentraut)](http://peter.eisentraut.org/blog/2023/12/05/postgresql-and-fips-mode)
- [PostgreSQL 18 FIPS Improvements](https://neon.com/postgresql/postgresql-18/security-improvements)
- [The Un-Fun Work of Making Postgres FIPS Compliant](https://pganalyze.com/blog/5mins-postgres-FIPS-mode)
- [Crunchy Data PostgreSQL for Government](https://www.crunchydata.com/industries/government)
- [Crunchy Data PostgreSQL STIG](https://ncp.nist.gov/checklist/revision/4184)
- [Crunchy Postgres Operator - Red Hat Catalog](https://catalog.redhat.com/en/software/containers/crunchydata/postgres-operator/5c78066cecb5240adfaaeaa3)
- [Crunchy Data PGO Components and Compatibility](https://access.crunchydata.com/documentation/postgres-operator/latest/references/components)
- [Milvus OpenShift Deployment Guide](https://milvus.io/docs/openshift.md)
- [Milvus Encryption at Rest Feature Request #33810](https://github.com/milvus-io/milvus/issues/33810)
- [Milvus Crypto Library Enhancement #44087](https://github.com/milvus-io/milvus/issues/44087)
- [Redis Enterprise FIPS Discussion #7802](https://github.com/redis/redis/issues/7802)
- [Redis Enterprise DISA STIG](https://ncp.nist.gov/checklist/1013)
- [Redis Enterprise OpenShift Operator](https://catalog.redhat.com/software/operators/detail/5e98728d3f398525a0ceafb9)
- [Qdrant Security Overview](https://ironcorelabs.com/vectordbs/qdrant-security/)
- [Qdrant Cloud Security](https://qdrant.tech/documentation/cloud-security/)
- [Weaviate and Red Hat OpenShift](https://www.redhat.com/en/blog/building-powerful-applications-weaviate-and-red-hat-openshift-retrieval-augmented-generation-workflow)
- [MinIO AIStor FIPS Mode](https://docs.min.io/enterprise/aistor-object-store/installation/kubernetes/fips-mode/)
- [MinIO for Red Hat OpenShift](https://www.min.io/product/aistor/private-cloud-red-hat-openshift)
- [ODF Security Considerations](https://docs.redhat.com/en/documentation/red_hat_openshift_data_foundation/4.15/html/planning_your_deployment/security-considerations_rhodf)
- [Go 1.24 FIPS 140-3 Module](https://go.dev/blog/fips140)
- [Red Hat: Benefits of Native FIPS Support in Go 1.24](https://developers.redhat.com/articles/2025/03/10/benefits-native-fips-support-go-124)
- [Apache AGE GitHub](https://github.com/apache/age)
- [pgvector GitHub](https://github.com/pgvector/pgvector)
