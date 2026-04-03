# Observability

MemoryHub uses the monitoring stack that already exists in every OpenShift cluster: Prometheus for metrics collection and Grafana for visualization. We don't introduce new monitoring infrastructure -- we plug into what's there.

What makes this interesting is that memory-specific observability is a novel capability. Nobody is shipping Grafana dashboards that show you how many memories are stale, which agents are writing the most, or where semantic conflicts are accumulating. This is unexplored territory in the agent tooling space.

## Prometheus Metrics

MemoryHub components export metrics at `/metrics` endpoints, scraped by Prometheus via ServiceMonitor CRs.

### MCP Server Metrics

These capture the agent-facing behavior of the system.

**memoryhub_operations_total** (counter, labels: operation, scope, status) -- total memory operations broken down by type (read, write, search, get_branches, list_versions), memory scope, and outcome (success, denied, error). This is the primary throughput indicator.

**memoryhub_operation_duration_seconds** (histogram, labels: operation, scope) -- latency distribution for each operation type. Search latency is especially important -- if agents are waiting too long for memory retrieval, the UX degrades.

**memoryhub_search_results_count** (histogram, labels: scope) -- how many results a search returns. Consistently zero results might indicate an embedding quality problem or a scope mismatch. Consistently high counts might mean the weight/stub threshold needs tuning.

**memoryhub_active_connections** (gauge) -- current number of MCP connections. Correlates with agent activity across the cluster.

**memoryhub_memories_total** (gauge, labels: scope, is_current) -- total memory count by scope and current/historical status. Tracks growth over time.

### Governance Metrics

**memoryhub_governance_decisions_total** (counter, labels: decision, scope, reason) -- access control decisions: permitted, denied, escalated. A spike in denials might indicate misconfigured policies or an agent attempting unauthorized access.

**memoryhub_audit_log_size_bytes** (gauge) -- size of the audit log table. Tracks growth for capacity planning.

**memoryhub_secrets_detected_total** (counter, labels: action) -- secrets/PII detections, broken down by action taken (blocked, flagged, quarantined).

**memoryhub_policy_violations_total** (counter, labels: policy, scope) -- policy violations by policy name and scope.

### Curator Metrics

**memoryhub_curator_run_duration_seconds** (histogram, labels: task) -- how long each curator task takes (promotion, pruning, dedup, conflict detection, secrets scan).

**memoryhub_curator_promotions_total** (counter) -- memories promoted to higher scopes.

**memoryhub_curator_pruned_total** (counter) -- memories pruned or marked superseded.

**memoryhub_curator_conflicts_detected_total** (counter, labels: resolution) -- conflicts found, broken down by resolution (auto-resolved, queued for human review).

**memoryhub_curator_staleness_flagged_total** (counter) -- memories flagged as potentially stale.

### Storage Metrics

**memoryhub_postgresql_connections_active** (gauge) -- active database connections. Important for connection pool monitoring.

**memoryhub_postgresql_query_duration_seconds** (histogram, labels: query_type) -- database query latency by type (vector_search, graph_traversal, metadata_lookup, audit_write).

**memoryhub_minio_objects_total** (gauge) -- total objects in MinIO. Tracks document memory growth.

**memoryhub_minio_storage_bytes** (gauge) -- total storage used in MinIO.

## Grafana Dashboards

The operator deploys Grafana dashboard ConfigMaps that are auto-discovered by the cluster's Grafana instance. Dashboards are organized by audience.

### Operations Dashboard

The "is MemoryHub healthy?" dashboard for platform administrators. Shows:

- Request rate and error rate over time
- Operation latency percentiles (p50, p95, p99)
- Active MCP connections
- PostgreSQL connection pool utilization
- MinIO storage utilization
- Curator agent last-run status and duration
- Component health (pods ready, restarts, OOM kills)

This is a standard SRE dashboard. Nothing novel here, but it needs to exist and be accurate.

### Memory Intelligence Dashboard

The novel dashboard -- insights into memory behavior across the organization.

- Memory count by scope over time (growth trends)
- Memories created vs. pruned over time (is the system growing or stabilizing?)
- Top agents by memory write volume (who's generating the most memories?)
- Stale memory count and age distribution
- Promotion activity: candidates identified, promoted, rejected
- Conflict detection: open conflicts, resolution rate, time to resolution
- Scope distribution: what fraction of memories are user vs. project vs. org vs. enterprise

This dashboard tells the story of organizational learning. Is the organization accumulating knowledge? Are stale memories being cleaned up? Is the curator agent doing its job?

### Governance Dashboard

For security and compliance teams.

- Secrets/PII detection events over time
- Policy violation trends
- Access denial events by scope and actor
- Audit log growth and retention status
- Governance decision latency (are access control checks adding noticeable latency?)

### Memory Graph Visualization (Stretch Goal)

Grafana's node graph panel can visualize relationships between memory nodes. This would show the tree structure -- how memories branch, where rationale lives, how organizational memories connect back to user memories via provenance links.

This is a stretch goal because Grafana's node graph panel hasn't been tested at scale with thousands of nodes. It might work well for a focused view (one user's memory tree, one organizational memory's provenance) but not for the full memory graph. Testing needed before committing to this approach.

## Alerting

Prometheus alerting rules for conditions that need human attention:

**Critical:**
- Secrets detected in memory content (immediate security concern)
- MCP server error rate exceeds threshold (agents can't access memories)
- PostgreSQL replication lag exceeds threshold (durability risk)
- Curator agent hasn't completed a scheduled run (maintenance not happening)

**Warning:**
- Stale memory count exceeds threshold (organizational knowledge may be outdated)
- Audit log size approaching retention limit
- Memory growth rate unusually high (possible runaway agent)
- Governance denial rate spike (possible misconfiguration or attack)
- MinIO storage utilization above 80%

Alert routing follows standard OpenShift patterns -- AlertmanagerConfig CRs route to the appropriate teams via the cluster's notification system.

## Design Questions

- What's the right cardinality for metric labels? Per-agent labels would be extremely useful but could cause Prometheus cardinality explosion at scale. Per-scope is safe. Per-user is probably fine. Per-agent-instance probably isn't.
- How do we expose memory graph data to Grafana's node graph panel? The panel expects a specific data format. Do we create a Grafana data source plugin, or use a Prometheus-compatible metric format?
- Should we include a "memory health score" -- a single composite metric that summarizes overall system health? It's useful for executive dashboards but can obscure real issues.
- What's the retention period for metrics? The default Prometheus retention in OpenShift is 15 days. Memory trend analysis benefits from longer retention. Should we recommend adjusting the retention, or summarize trends in the application layer?
