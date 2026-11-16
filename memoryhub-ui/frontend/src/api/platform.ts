/**
 * Super Admin · Platform Operations.
 *
 * Every screen asks the dashboard backend for /api/platform/* first. A deployment that
 * serves a single tenant (no platform API yet) answers 404; the screens then show the
 * same views built from this deployment's own endpoints, as one tenant, and say so.
 */
import { api, ApiError, rawRequest } from './client';
import type { AuditEvent } from '@/types';

export type TenantHealth = 'healthy' | 'degraded' | 'quota' | 'down' | null;

export interface TenantSummary {
  id: string;
  status: 'active' | 'onboarding' | 'suspended';
  platform_admins: string[];
  admins_mfa?: boolean | null;
  users: number | null;
  agents: number | null;
  ops_24h: number | null;
  search_success: number | null;
  storage_pct: number | null;
  memory_quota: number | null;
  memories: number | null;
  rate_limit: number | null;
  health: TenantHealth;
  /** Short reason when not healthy: "Reranker", "Quota 88%". */
  health_label?: string | null;
  created_at?: string | null;
  incident_grants?: number | null;
  /** The tenant this dashboard deployment serves. */
  current?: boolean;
}

export interface GlobalEvent {
  id: string;
  timestamp: string;
  actor: string;
  actor_role?: 'superuser' | 'admin' | null;
  event: string;
  tenant: string;
  target: string;
  reason: string;
  severity: 'high' | 'medium' | 'info';
  category: 'policy' | 'deploy' | 'admin' | 'review' | 'privileged' | 'other';
}

export interface PlatformOverview {
  source: 'platform' | 'single-tenant';
  tenants: TenantSummary[];
  kpis: {
    active_tenants: number;
    suspended: number;
    onboarding: number;
    active_users: number | null;
    users_trend_pct?: number | null;
    agents: number | null;
    active_sessions: number | null;
    ops_24h: number | null;
    search_success: number | null;
    availability_30d?: number | null;
    slo?: number | null;
  };
  alert?: { title: string; detail: string } | null;
  security: { open_incidents: number; cross_tenant_24h: number; active_grants: number; grant_expires?: string | null; pending_approvals: number; revoked_clients_24h: number };
  admins: { super_admins: number; super_source?: string; platform_admins: number; tenants: number; without_mfa: number | null };
  release: { mcp?: string | null; ui?: string | null; migrations?: string | null };
  scopes: { scope: string; count: number }[];
  events: GlobalEvent[];
}

export interface AdminRow {
  username: string;
  name: string;
  role: 'superuser' | 'admin';
  scope: string;
  granted_by: string | null;
  granted_at?: string | null;
  valid_until?: string | null;
  mfa: 'webauthn' | 'totp' | null;
  last_action?: string | null;
  you?: boolean;
}

export interface PlatformIncident {
  id: string;
  title: string;
  tenant: string;
  severity: 'high' | 'medium' | 'low';
  owner: string;
  grants: string;
  opened_at: string;
  status: 'investigating' | 'monitoring' | 'closed';
}

export interface SecurityResponse {
  source: 'platform' | 'single-tenant';
  kpis: { open_incidents: number; with_grant: number; cross_tenant_24h: number; failed_signins_24h: number | null; failed_trend?: string | null; revoked_24h: number; revoked_platform: number };
  incidents: PlatformIncident[];
  alerts: { id: string; text: string; detail?: string | null }[];
  cross_tenant: { id: string; time: string; identity: string; from: string; to: string; operation: string }[];
  revoked: { id: string; time: string; client: string; tenant: string; by: string; scope: 'tenant' | 'platform' }[];
  grants: { active: string; pending: number; remediate_month: number; self_approval: number };
}

export interface PlatformPolicies {
  source: 'platform' | 'single-tenant';
  privileged: { inspect_max_hours: number; remediate_max_hours: number; hard_delete_extra_confirm: boolean; stepup_mfa: boolean; owner_notification: boolean };
  models: { embedding: string; reranker: string; mcp_profile: 'compact' | 'full'; embedding_options: string[]; reranker_options: string[] };
  limits: { rate_limit_per_min: number | null; memory_quota: number | null; max_full_audit_days: number; privileged_years: number; self_signup: string };
  registration: { self_signup: 'per_tenant' | 'invite_only'; require_mfa_admins: boolean };
  system_rules: { id: string; name: string; tier: string; action: string; hits: number | null }[];
}

export interface HealthResponse {
  source: 'platform' | 'single-tenant';
  components: { name: string; status: 'healthy' | 'degraded' | 'down' | 'not_configured'; detail?: string | null; latency_ms?: number | null; tenants_affected?: number }[];
  deployments: { id: string; time: string; component: string; version: string; by: string; status: 'done' | 'running' | 'failed' | 'rolled_back' }[];
  release: { mcp?: string | null; ui?: string | null; migrations?: string | null };
  jobs: { kind: string; label: string; ok: number; failed: number; running: number }[];
}

export interface GrantRequest {
  id: string;
  incident_ref: string;
  type: 'inspect' | 'remediate';
  tenant: string;
  owner: string;
  targets: string[];
  operations: string[];
  action?: string | null;
  reason: string;
  window_hours: number;
  requested_by: string;
  requested_at: string;
  status: 'pending' | 'approved' | 'declined' | 'active' | 'expired';
}

export interface Runbook {
  id: string;
  kind: 'runbook' | 'procedure' | 'decision' | 'draft';
  title: string;
  component: string;
  owner: string;
  version: string;
  reviewed_at: string | null;
  audience: string;
  url?: string | null;
}

const enc = encodeURIComponent;
const isMissing = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 405 || e.status === 501);
const safe = async <T,>(p: Promise<T>): Promise<T | null> => {
  try {
    return await p;
  } catch {
    return null;
  }
};
async function platformGet<T>(path: string, fallback: () => Promise<T>): Promise<T> {
  try {
    return await req<T>('GET', path);
  } catch (e) {
    if (isMissing(e) || !(e instanceof ApiError)) return fallback();
    throw e;
  }
}
const req = <T,>(method: string, path: string, body?: unknown) => rawRequest<T>(method, path, body);
/** Writes have no single-tenant fallback: a server without the platform API says so. */
async function platformWrite<T>(method: string, path: string, body?: unknown): Promise<T> {
  try {
    return await req<T>(method, path, body);
  } catch (e) {
    if (isMissing(e)) throw new ApiError(404, 'This server does not run the platform API yet (/api/platform). The change was not made.');
    throw e;
  }
}

/* ---------------- single-tenant fallbacks ---------------- */

const ADMIN_EVENT = /project|team|campaign|client|identity|role|setting|tenant|review|incident|grant|break|quarantine|rule|policy|admin|deploy|account/i;
const toGlobal = (e: AuditEvent, tenant: string): GlobalEvent => {
  const m = (e.metadata ?? {}) as Record<string, unknown>;
  const t = `${e.event_type}`;
  const category: GlobalEvent['category'] = /incident|grant|break/.test(t) ? 'privileged' : /review/.test(t) ? 'review' : /setting|policy|rule/.test(t) ? 'policy' : /deploy|release/.test(t) ? 'deploy' : /role|admin|account|client|identity/.test(t) ? 'admin' : 'other';
  return {
    id: String(e.id),
    timestamp: e.timestamp,
    actor: e.actor_id,
    actor_role: (m.actor_role as GlobalEvent['actor_role']) ?? null,
    event: e.operation || e.event_type,
    tenant,
    target: e.memory_id ? `${e.memory_id.slice(0, 8)}…` : String(m.subject ?? m.client_id ?? m.request_id ?? '—'),
    reason: String(m.reason ?? m.incident_ref ?? m.comment ?? '—'),
    severity: category === 'privileged' ? (/read/.test(t) ? 'high' : 'medium') : category === 'policy' || category === 'admin' ? 'medium' : 'info',
    category,
  };
};

const thisTenant = async (): Promise<TenantSummary> => {
  const [ov, acc, ids, bg, settings] = await Promise.all([safe(api.overview('1d')), safe(api.accounts()), safe(api.identities()), safe(api.breakGlass()), safe(api.settings())]);
  const g = ov?.governance;
  const unhealthy = ov?.health.find((h) => h.status === 'degraded' || h.status === 'down');
  const quota = g?.storage_quota_pct ?? null;
  return {
    id: ov?.tenant_id ?? settings?.tenant.tenant_id ?? 'this tenant',
    status: 'active',
    platform_admins: (acc?.items ?? []).filter((a) => a.role === 'admin').map((a) => a.display_name),
    users: acc ? acc.items.filter((a) => a.status === 'active').length : null,
    agents: ov?.agents.total ?? (ids ? ids.counts.user_agents + ids.counts.service_agents : null),
    ops_24h: ov ? ov.searches.last_24h + ov.activity.reduce((a, b) => a + b.writes, 0) : null,
    search_success: null,
    storage_pct: quota,
    memory_quota: g?.storage_quota_limit ?? settings?.values.quotas?.tenant_memory_quota ?? null,
    memories: ov?.memories.current ?? null,
    rate_limit: null,
    health: unhealthy ? 'degraded' : quota !== null && quota >= 85 ? 'quota' : ov ? 'healthy' : null,
    health_label: unhealthy ? unhealthy.name : quota !== null && quota >= 85 ? `Quota ${quota}%` : null,
    incident_grants: bg ? bg.grants.filter((x) => x.active).length : null,
    current: true,
  };
};

export const platform = {
  overview: () =>
    platformGet<PlatformOverview>('/platform/overview', async () => {
      const [t, ov, audit, bg, acc, denied] = await Promise.all([
        thisTenant(),
        safe(api.overview('1d')),
        safe(api.audit({ hours: 72, per_page: 100 })),
        safe(api.breakGlass()),
        safe(api.accounts()),
        safe(api.audit({ hours: 24, decision: 'denied', per_page: 1 })),
      ]);
      const unhealthy = ov?.health.find((h) => h.status === 'degraded' || h.status === 'down');
      return {
        source: 'single-tenant',
        tenants: [t],
        kpis: {
          active_tenants: 1,
          suspended: 0,
          onboarding: 0,
          active_users: t.users,
          agents: ov?.agents.total ?? null,
          active_sessions: ov?.agents.active_now ?? null,
          ops_24h: t.ops_24h,
          search_success: null,
        },
        alert: unhealthy ? { title: `${unhealthy.name} ${unhealthy.status === 'down' ? 'not responding' : 'degraded'}`, detail: unhealthy.detail ?? '' } : null,
        security: {
          open_incidents: bg?.active ? 1 : 0,
          cross_tenant_24h: 0,
          active_grants: bg?.active ? 1 : 0,
          grant_expires: bg?.active?.expires_at ?? null,
          pending_approvals: 0,
          revoked_clients_24h: 0,
        },
        admins: { super_admins: 1, super_source: 'deployment', platform_admins: acc ? acc.counts.admins : 0, tenants: 1, without_mfa: null },
        release: {},
        scopes: (ov?.scopes ?? []).map((s) => ({ scope: s.scope, count: s.count })),
        events: (audit?.items ?? []).filter((e) => ADMIN_EVENT.test(e.event_type)).slice(0, 8).map((e) => toGlobal(e, t.id)),
        ...(denied ? {} : {}),
      };
    }),
  tenants: () => platformGet<{ source: 'platform' | 'single-tenant'; items: TenantSummary[] }>('/platform/tenants', async () => ({ source: 'single-tenant', items: [await thisTenant()] })),
  createTenant: (body: { id: string; name: string; admin?: string; memory_quota?: number | null; rate_limit?: number | null }) => platformWrite<TenantSummary>('POST', '/platform/tenants', body),
  setTenantStatus: (id: string, status: 'active' | 'suspended', reason: string) => platformWrite<TenantSummary>('POST', `/platform/tenants/${enc(id)}/status`, { status, reason }),
  setTenantLimits: (id: string, body: { memory_quota: number | null; rate_limit: number | null; reason: string }) => platformWrite<TenantSummary>('PATCH', `/platform/tenants/${enc(id)}`, body),
  /** Records the tenant-context switch (who, which tenant, why) in Global audit. */
  enterTenant: (id: string, reason: string) => platformWrite<{ ok: boolean }>('POST', `/platform/tenants/${enc(id)}/context`, { reason }),

  admins: () =>
    platformGet<{ source: 'platform' | 'single-tenant'; items: AdminRow[] }>('/platform/admins', async () => {
      const [acc, me] = await Promise.all([safe(api.accounts()), safe(api.me())]);
      const tenant = me?.tenant_id ?? 'this tenant';
      const items: AdminRow[] = (acc?.items ?? [])
        .filter((a) => a.role === 'admin' || a.superuser)
        .map((a) => ({
          username: a.username,
          name: a.display_name,
          role: a.superuser ? 'superuser' : 'admin',
          scope: a.superuser ? 'Platform' : tenant,
          granted_by: a.approved_by ?? a.invited_by,
          granted_at: a.created_at,
          valid_until: null,
          mfa: null,
          last_action: a.last_login_at,
          you: a.username === me?.username,
        }));
      if (me && me.role === 'superuser' && !items.some((x) => x.username === me.username))
        items.unshift({ username: me.username, name: me.name, role: 'superuser', scope: 'Platform', granted_by: 'deployment config', mfa: null, last_action: null, you: true });
      return { source: 'single-tenant', items };
    }),
  assignAdmin: (body: { username: string; role: 'admin' | 'superuser'; tenant?: string; valid_until?: string | null; reason: string }) => platformWrite<AdminRow>('POST', '/platform/admins', body),
  revokeAdmin: (username: string, scope: string, reason: string) => platformWrite<{ ok: boolean }>('POST', `/platform/admins/${enc(username)}/revoke`, { scope, reason }),
  requireMfa: (username: string) => platformWrite<{ ok: boolean }>('POST', `/platform/admins/${enc(username)}/require-mfa`, {}),

  health: () =>
    platformGet<HealthResponse>('/platform/health', async () => {
      const [ov, ops] = await Promise.all([safe(api.overview('1d')), safe(api.operations({ days: 7 }))]);
      return {
        source: 'single-tenant',
        components: (ov?.health ?? []).map((h) => ({ name: h.name, status: h.status === 'idle' ? 'healthy' : h.status, detail: h.detail, latency_ms: h.latency_ms, tenants_affected: h.status === 'healthy' ? 0 : 1 })),
        deployments: [],
        release: {},
        jobs: (ops?.kinds ?? []).map((k) => ({ kind: k.kind, label: k.label, ok: k.ok, failed: k.failed, running: k.running })),
      };
    }),

  policies: () =>
    platformGet<PlatformPolicies>('/platform/policies', async () => {
      const [s, rules, matches, bg] = await Promise.all([safe(api.settings()), safe(api.rules()), safe(api.ruleMatches()), safe(api.breakGlass())]);
      const v = s?.values;
      return {
        source: 'single-tenant',
        privileged: { inspect_max_hours: bg?.policy.hours ?? 4, remediate_max_hours: 1, hard_delete_extra_confirm: true, stepup_mfa: false, owner_notification: bg?.policy.notify_owner ?? true },
        models: {
          embedding: s?.models.embedding.detail ?? s?.models.embedding.name ?? '—',
          reranker: s?.models.reranker.detail ?? s?.models.reranker.name ?? '—',
          mcp_profile: v?.audit.mcp_profile ?? 'full',
          embedding_options: [],
          reranker_options: [],
        },
        limits: {
          rate_limit_per_min: null,
          memory_quota: v?.quotas?.tenant_memory_quota ?? null,
          max_full_audit_days: v?.audit.retention?.ceilings?.data?.[0] ?? 90,
          privileged_years: 7,
          self_signup: 'Per tenant',
        },
        registration: { self_signup: 'per_tenant', require_mfa_admins: false },
        system_rules: (rules ?? [])
          .filter((r) => r.layer === 'system')
          .map((r) => ({ id: r.id, name: r.name, tier: r.tier, action: r.action, hits: matches?.available ? matches.counts[r.name] ?? 0 : null })),
      };
    }),
  savePolicies: (body: Partial<Omit<PlatformPolicies, 'source' | 'system_rules'>> & { reason: string }) => platformWrite<PlatformPolicies>('PUT', '/platform/policies', body),
  createSystemRule: (body: { name: string; tier: 'regex' | 'embedding'; pattern?: string; threshold?: number; action: string; reason: string }) =>
    platformWrite<{ id: string }>('POST', '/platform/rules', body),
  previewPolicies: (body: Partial<Omit<PlatformPolicies, 'source' | 'system_rules'>>) => platformWrite<{ tenants: { id: string; change: string }[] }>('POST', '/platform/policies/preview', body),

  security: () =>
    platformGet<SecurityResponse>('/platform/security', async () => {
      const [bg, denied, me, creds] = await Promise.all([
        safe(api.breakGlass()),
        safe(api.audit({ hours: 24, decision: 'denied', per_page: 200 })),
        safe(api.me()),
        safe(api.credentials()),
      ]);
      const tenant = me?.tenant_id ?? 'this tenant';
      const items = denied?.items ?? [];
      const failed = items.filter((e) => /auth|login|sign/.test(e.event_type)).length;
      const incidents: PlatformIncident[] = (bg?.grants ?? []).map((g) => ({
        id: g.incident_ref,
        title: g.justification,
        tenant,
        severity: 'high',
        owner: g.username,
        grants: g.active ? 'inspect active' : '1 expired',
        opened_at: g.created_at,
        status: g.active ? 'investigating' : 'closed',
      }));
      const unique = incidents.filter((x, i) => incidents.findIndex((y) => y.id === x.id) === i);
      const revoked = (creds?.clients ?? []).filter((c) => !c.active);
      return {
        source: 'single-tenant',
        kpis: {
          open_incidents: unique.filter((i) => i.status !== 'closed').length,
          with_grant: bg?.active ? 1 : 0,
          cross_tenant_24h: 0,
          failed_signins_24h: failed,
          revoked_24h: revoked.filter((c) => Date.now() - Date.parse(c.updated_at) < 86400000).length,
          revoked_platform: 0,
        },
        incidents: unique,
        alerts: [],
        cross_tenant: [],
        revoked: revoked.map((c) => ({ id: c.client_id, time: c.updated_at, client: c.client_name, tenant, by: '—', scope: 'tenant' as const })),
        grants: { active: bg?.active ? '1 · inspect' : '0', pending: 0, remediate_month: 0, self_approval: 0 },
      };
    }),
  openIncident: (body: { title: string; tenant: string; severity: string }) => platformWrite<PlatformIncident>('POST', '/platform/incidents', body),
  revokeClientPlatformWide: (client_id: string, reason: string) => platformWrite<{ ok: boolean }>('POST', '/platform/clients/revoke', { client_id, reason }),

  audit: (params: { hours?: number; tenant?: string; category?: string }) =>
    platformGet<{ source: 'platform' | 'single-tenant'; items: GlobalEvent[]; tenants: string[]; review: { decisions_7d: number | null; overturned: number | null; hard_deletes: number | null; self_blocked: number | null } }>(
      `/platform/audit?hours=${params.hours ?? 24}${params.tenant ? `&tenant=${enc(params.tenant)}` : ''}`,
      async () => {
        const [audit, me] = await Promise.all([safe(api.audit({ hours: params.hours ?? 24, per_page: 200 })), safe(api.me())]);
        const tenant = me?.tenant_id ?? 'this tenant';
        const items = (audit?.items ?? []).filter((e) => ADMIN_EVENT.test(e.event_type)).map((e) => toGlobal(e, tenant));
        const reviews = items.filter((e) => e.category === 'review').length;
        return { source: 'single-tenant', items, tenants: [tenant], review: { decisions_7d: reviews, overturned: null, hard_deletes: null, self_blocked: null } };
      },
    ),

  grantRequests: () =>
    platformGet<{ source: 'platform' | 'single-tenant'; to_approve: GrantRequest[]; mine: GrantRequest[] }>('/platform/grant-requests', async () => ({ source: 'single-tenant', to_approve: [], mine: [] })),
  /** With the platform API a second Super Admin approves; without it the server starts the grant at once (single-tenant). */
  requestGrant: async (body: Omit<GrantRequest, 'id' | 'requested_by' | 'requested_at' | 'status'>): Promise<{ id: string; started: boolean }> => {
    try {
      const r = await req<GrantRequest>('POST', '/platform/grant-requests', body);
      return { id: r.id, started: false };
    } catch (e) {
      if (!isMissing(e)) throw e;
      const g = await api.startBreakGlass({
        incident_ref: body.incident_ref,
        justification: `${body.reason} · ${body.type} · ${body.owner} · ${body.targets.join(', ')} · ${body.operations.join(', ')}`,
        hours: Math.max(1, Math.round(body.window_hours)),
      });
      return { id: g.id, started: true };
    }
  },
  decideGrant: (id: string, decision: 'approve' | 'decline', reason?: string) => platformWrite<GrantRequest>('POST', `/platform/grant-requests/${enc(id)}/decision`, { decision, reason }),
  runbooks: () => platformGet<{ source: 'platform' | 'single-tenant'; items: Runbook[] }>('/platform/runbooks', async () => ({ source: 'single-tenant', items: [] })),
};
