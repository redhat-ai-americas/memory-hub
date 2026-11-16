import React, { useMemo, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Icon, Pager, ScopeLabel, SkLines, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { AuditEvent, BreakGlassGrant, BreakGlassReport, BreakGlassState, ForensicsResponse, OperationsResponse, SettingsResponse } from '@/types';
import { errorMessage, fmtInt, shortId, truncate } from '@/utils/format';
import { actorKind, EventTarget, memoryHref } from './common';

/* ------------------------------------------------------------------ */
/* Shared helpers                                                       */
/* ------------------------------------------------------------------ */

type Tab = 'log' | 'activity' | 'denied' | 'forensics' | 'grants' | 'retention';
const TABS: Tab[] = ['log', 'activity', 'denied', 'forensics', 'grants', 'retention'];
const TAB_LABEL: Record<Tab, string> = {
  log: 'Audit log',
  activity: 'Activity log',
  denied: 'Denied only',
  forensics: 'Forensics',
  grants: 'Incident grants',
  retention: 'Retention',
};

const PERIODS: { value: string; label: string; short: string }[] = [
  { value: '24', label: 'Last 24 hours', short: '24 h' },
  { value: '168', label: 'Last 7 days', short: '7 d' },
  { value: '720', label: 'Last 30 days', short: '30 d' },
  { value: '2160', label: 'Last 90 days', short: '90 d' },
];
const periodOf = (h: string) => PERIODS.find((p) => p.value === h) ?? PERIODS[0];

const meta = (e: AuditEvent) => (e.metadata || {}) as Record<string, unknown>;
const str = (v: unknown) => (typeof v === 'string' && v ? v : undefined);

export type Category = 'access' | 'data' | 'policy' | 'review' | 'identity' | 'project' | 'incident' | 'settings';
export const CATEGORY_LABEL: Record<Category, string> = {
  access: 'access',
  data: 'data operations',
  policy: 'policy',
  review: 'review',
  identity: 'identity / client',
  project: 'project',
  incident: 'incident',
  settings: 'settings',
};
const CATEGORY_ORDER: Category[] = ['access', 'data', 'policy', 'review', 'identity', 'project', 'incident', 'settings'];

export const categoryOf = (e: AuditEvent): Category => {
  const t = `${e.event_type} ${e.operation}`.toLowerCase();
  if (/incident|break.?glass|grant/.test(t)) return 'incident';
  if (/quarantine|curation|rule|policy/.test(t)) return 'policy';
  if (/review|promot|approve|reject/.test(t)) return 'review';
  if (/client|identity|agent\.|key|token|oauth/.test(t)) return 'identity';
  if (/project|team|campaign/.test(t)) return 'project';
  if (/setting|tenant|retention/.test(t)) return 'settings';
  if (/memory\.read|access|auth|login|sign/.test(t)) return 'access';
  return 'data';
};

const DATA_OPS = new Set(['memory.read', 'memory.search', 'memory.write', 'memory.update', 'memory.delete', 'memory.restore', 'memory.promote']);

const hhmm = (iso: string, seconds = true) => {
  const d = new Date(iso);
  const today = new Date();
  const t = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}), hour12: false });
  return d.toDateString() === today.toDateString() ? t : `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} ${t.slice(0, 5)}`;
};
const utcStamp = (iso: string) => {
  const d = new Date(iso);
  return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })} ${d.toISOString().slice(11, 19)} UTC`;
};

/** A personal record the viewer may not read: its ID and nothing else. */
const Hidden: React.FC<{ id: string | null }> = ({ id }) => (
  <span className="hidden-box" title="Personal content hidden — metadata only">
    <Icon.EyeOff />
    <span className="mono">{id ? shortId(id) : 'personal record'}</span>
  </span>
);

/** Whether the viewer may see the target of an event (not a personal record, or an incident grant covers it). */
const useCanSee = () => {
  const { me } = useApp();
  const grant = Boolean(me?.access?.break_glass);
  return (e: { scope?: string | null; event_type?: string }) => grant || e.scope !== 'user' || e.event_type === 'memory.search';
};

const Target: React.FC<{ e: AuditEvent; max?: number }> = ({ e, max = 34 }) => {
  const canSee = useCanSee();
  const m = meta(e);
  if (!canSee(e)) return <Hidden id={e.memory_id} />;
  const subject = str(m.subject) ?? str(m.member) ?? str(m.client_id) ?? str(m.request_id);
  if (!e.memory_id && subject) {
    const after = str(m.after) ?? str(m.role);
    return (
      <span>
        {truncate(subject, max)}
        {after ? ` → ${after}` : ''}
      </span>
    );
  }
  return <EventTarget e={e} max={max} />;
};

const ScopeCell: React.FC<{ e: AuditEvent }> = ({ e }) => {
  const project = str(meta(e).project);
  if (e.scope === 'project' && project) return <ScopeLabel scope="project">{project}</ScopeLabel>;
  if (e.scope === 'user')
    return (
      <ScopeLabel scope="user">
        <Icon.Lock size={11} /> User
      </ScopeLabel>
    );
  if (!e.scope || ['all', 'session'].includes(e.scope)) return <span className="muted">—</span>;
  return <ScopeLabel scope={e.scope} />;
};

/** Decision text: permitted / denied / queued, with the capability or reason behind it. */
const decision = (e: AuditEvent): { label: string; cls: string; reason?: string } => {
  const m = meta(e);
  const reason = str(m.rule) ? `rule ${m.rule}` : str(m.reason) ?? str(m.capability) ?? str(m.detail);
  const grant = str(m.grant_id);
  if (e.decision === 'denied') return { label: 'Denied', cls: 'err', reason: reason ?? 'no capability' };
  if (m.queued || e.event_type === 'review.promotion_proposed') return { label: 'Queued', cls: 'warn', reason: 'for review' };
  if (m.flagged) return { label: 'Permitted', cls: 'warn', reason: 'flagged' };
  return { label: 'Permitted', cls: 'ok', reason: grant ?? (str(m.capability) ? `capability ${m.capability}` : str(m.reason) ? 'reason given' : undefined) };
};

const DecisionCell: React.FC<{ e: AuditEvent }> = ({ e }) => {
  const d = decision(e);
  return (
    <span className={d.cls} style={{ fontWeight: 600 }}>
      {d.label}
      {d.reason && <div style={{ fontWeight: 500, overflowWrap: 'anywhere' }}>{truncate(d.reason, 24)}</div>}
    </span>
  );
};

/** Short role badge for people (Platform admin / Super-user) and the agent kind for agents. */
const ActorCell: React.FC<{ e: AuditEvent; sub?: boolean }> = ({ e, sub = true }) => {
  const m = meta(e);
  const role = str(m.actor_role);
  const kind = actorKind(e);
  const badge = role === 'superuser' ? 'SA' : role === 'admin' ? 'PA' : null;
  return (
    <div>
      <div>{e.actor_id}</div>
      {badge ? (
        <span className={`lbl ${badge === 'SA' ? 'org' : 'blue'}`} style={{ fontWeight: 700, padding: '0 8px' }} title={badge === 'SA' ? 'Super-user' : 'Platform admin'}>
          {badge}
        </span>
      ) : (
        sub && (
          <div className="sm muted">
            {kind}
            {e.driver_id && e.driver_id !== e.actor_id ? ` · ${e.driver_id}` : ''}
          </div>
        )
      )}
    </div>
  );
};

/** Every event in a period, fetched in pages; filters and counts work on this list. */
const useEvents = (hours: number, extra: { actor?: string; decision?: string } = {}) =>
  useApi<{ items: AuditEvent[]; total: number; hidden: number }>(async () => {
    const all: AuditEvent[] = [];
    let total = 0;
    let hidden = 0;
    for (let page = 1; page <= 5; page += 1) {
      const res = await api.audit({ hours, page, per_page: 200, ...extra });
      all.push(...res.items);
      total = res.total;
      hidden = res.hidden_user_operations ?? 0;
      if (all.length >= res.total || res.items.length === 0) break;
    }
    all.sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));
    return { items: all, total, hidden };
  }, [hours, extra.actor, extra.decision]);

const downloadCsv = (name: string, rows: (string | number | null | undefined)[][]) => {
  const csv = rows.map((r) => r.map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
};

const Sel: React.FC<{ id: string; label: string; value: string; onChange: (v: string) => void; options: [string, string][] }> = ({ id, label, value, onChange, options }) => (
  <>
    <label htmlFor={id} className="vh">
      {label}
    </label>
    <select id={id} className="in auto" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </select>
  </>
);

const SearchBox: React.FC<{ id: string; placeholder: string; value: string; onChange: (v: string) => void }> = ({ id, placeholder, value, onChange }) => {
  const [text, setText] = useState(value);
  return (
    <span className="in-icon" style={{ flex: '0 1 260px' }}>
      <Icon.Search size={15} />
      <label htmlFor={id} className="vh">
        {placeholder}
      </label>
      <input
        id={id}
        className="in"
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => onChange(text.trim())}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onChange(text.trim());
        }}
      />
    </span>
  );
};

const Info: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="alert" role="note">
    <Icon.Info size={16} />
    <span className="sm">{children}</span>
  </div>
);

/* ------------------------------------------------------------------ */
/* Page                                                                 */
/* ------------------------------------------------------------------ */

const DESCRIPTION: Record<Tab, (tenant: string) => string> = {
  log: (t) =>
    `Every administrative and data operation in ${t}: who did what, to which object, and the decision. Personal records appear by ID and metadata only; event text never includes memory content.`,
  activity: (t) => `Data operations in ${t} — reads, searches and writes by people and their agents. Personal records appear by ID and metadata only.`,
  denied: () => 'Operations refused by access rules, curation policy or a suspended client — grouped by actor and reason. A denial never shows the content that was refused.',
  forensics: (t) => `Every operation in ${t}: who did what, the decision, and what an agent knew at a point in time. Personal memories appear by ID and metadata.`,
  grants: () =>
    'Incident grants that touch this tenant’s data, read-only. You see who requested and approved each grant, its type, targets, window and how many records were read — never the content read under it.',
  retention: () =>
    'How long this tenant keeps each kind of audit and activity record, within the ceilings set in Global policies. Shortening is immediate; extending past a ceiling is not possible here. Privileged-access records are fixed by the platform.',
};

const AdminAudit: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { me } = useApp();
  const notify = useToast();
  const requested = route.params.get('tab') as Tab | null;
  const tab: Tab = requested && TABS.includes(requested) ? requested : 'log';
  const tenant = me?.tenant_id ?? 'this tenant';
  const go = (t: Tab) => navigate('/audit', t === 'log' ? new URLSearchParams() : new URLSearchParams({ tab: t }), { replace: true });
  const deniedCount = useApi(() => api.audit({ decision: 'denied', hours: 168, per_page: 1 }), []);
  const grants = useApi<BreakGlassState>(() => api.breakGlass(), []);
  const activeGrants = grants.data ? grants.data.grants.filter((g) => g.active).length + (grants.data.active && !grants.data.grants.some((g) => g.id === grants.data!.active!.id) ? 1 : 0) : null;
  const [escalate, setEscalate] = useState(false);
  const [retentionSave, setRetentionSave] = useState<{ ready: boolean; save: () => void } | null>(null);

  const exportCsv = async () => {
    try {
      const all: AuditEvent[] = [];
      for (let page = 1; page <= 25; page += 1) {
        const res = await api.audit({ page, per_page: 200, decision: tab === 'denied' ? 'denied' : undefined });
        all.push(...res.items);
        if (all.length >= res.total || res.items.length === 0) break;
      }
      downloadCsv(`memoryhub-audit-${new Date().toISOString().slice(0, 10)}.csv`, [
        ['time_utc', 'event_id', 'actor', 'driver', 'category', 'operation', 'scope', 'owner', 'record_id', 'decision', 'reason'],
        ...all.map((e) => [e.timestamp, e.id, e.actor_id, e.driver_id, CATEGORY_LABEL[categoryOf(e)], e.operation, e.scope, e.owner_id, e.memory_id, e.decision, decision(e).reason]),
      ]);
      notify(`Exported metadata for ${fmtInt(all.length)} events — no memory content.`);
    } catch (e) {
      notify(errorMessage(e), 'err');
    }
  };

  return (
    <>
      <PageHeader
        title="Audit & forensics"
        crumbs={[{ label: 'Audit & forensics', href: buildHash('/audit') }, { label: TAB_LABEL[tab] }]}
        description={DESCRIPTION[tab](tenant)}
        actions={
          <>
            <button type="button" className="btn bs" onClick={exportCsv}>
              Export metadata CSV
            </button>
            {tab === 'grants' && (
              <button type="button" className="btn bp" onClick={() => setEscalate(true)}>
                Request escalation…
              </button>
            )}
            {tab === 'retention' && (
              <button type="button" className="btn bp" disabled={!retentionSave?.ready} onClick={() => retentionSave?.save()}>
                Save · reason required
              </button>
            )}
          </>
        }
        tabs={
          <Tabs
            label="Audit views"
            value={tab}
            onChange={(t) => go(t as Tab)}
            tabs={TABS.map((t) => ({
              value: t,
              label: TAB_LABEL[t],
              count: t === 'denied' ? deniedCount.data?.denied_total ?? null : t === 'grants' ? activeGrants : undefined,
            }))}
          />
        }
      />
      <div className="body">
        {tab === 'log' && <AuditLogView route={route} />}
        {tab === 'activity' && <ActivityView route={route} />}
        {tab === 'denied' && <DeniedView route={route} />}
        {tab === 'forensics' && <ForensicsView route={route} grants={grants.data} />}
        {tab === 'grants' && <GrantsView route={route} state={grants} escalate={escalate} setEscalate={setEscalate} />}
        {tab === 'retention' && <RetentionView onReady={setRetentionSave} />}
      </div>
    </>
  );
};

/* ------------------------------------------------------------------ */
/* Audit log                                                            */
/* ------------------------------------------------------------------ */

const setParams = (route: HashRoute, changes: Record<string, string | undefined>) => {
  const next = new URLSearchParams(route.params);
  Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
  if (!('page' in changes)) next.delete('page');
  navigate('/audit', next, { replace: true });
};

const KIND_OPTIONS: [string, string][] = [
  ['', 'Source: all'],
  ['human', 'Source: people'],
  ['user_agent', 'Source: user agents'],
  ['service_agent', 'Source: service agents'],
];
const kindOf = (e: AuditEvent) => {
  const k = actorKind(e);
  if (k.startsWith('human') || k === 'user') return 'human';
  if (k === 'user agent') return 'user_agent';
  return 'service_agent';
};

const AuditLogView: React.FC<{ route: HashRoute }> = ({ route }) => {
  const p = route.params;
  const hours = p.get('hours') ?? '24';
  const q = p.get('q') ?? '';
  const cat = (p.get('cat') ?? '') as Category | '';
  const dec = p.get('decision') ?? '';
  const op = p.get('op') ?? '';
  const src = p.get('src') ?? '';
  const page = Number(p.get('page') || 1);
  const selId = p.get('event');
  const set = (c: Record<string, string | undefined>) => setParams(route, c);
  const { data, error, loading, reload } = useEvents(Number(hours));
  const events = data?.items ?? [];
  const ops = [...new Set(events.map((e) => e.operation))].sort();
  const rows = events.filter((e) => {
    if (cat && categoryOf(e) !== cat) return false;
    if (dec === 'permitted' && e.decision === 'denied') return false;
    if (dec === 'denied' && e.decision !== 'denied') return false;
    if (op && e.operation !== op) return false;
    if (src && kindOf(e) !== src) return false;
    if (q) {
      const hay = `${e.id} ${e.actor_id} ${e.driver_id ?? ''} ${e.memory_id ?? ''} ${str(meta(e).trace_id) ?? ''} ${str(meta(e).correlation_id) ?? ''}`.toLowerCase();
      if (!hay.includes(q.toLowerCase())) return false;
    }
    return true;
  });
  const perPage = 50;
  const shown = rows.slice((page - 1) * perPage, page * perPage);
  const selected = rows.find((e) => String(e.id) === selId) ?? shown[0] ?? null;
  const total = cat || dec || op || src || q ? rows.length : Math.max(rows.length, data?.total ?? 0);

  return (
    <>
      <div className="filters">
        <SearchBox id="al-q" placeholder="Search actor, target ID, trace" value={q} onChange={(v) => set({ q: v || undefined })} />
        <Sel id="al-cat" label="Category" value={cat} onChange={(v) => set({ cat: v || undefined })} options={[['', 'Category: all'], ...CATEGORY_ORDER.map((c) => [c, `Category: ${CATEGORY_LABEL[c]}`] as [string, string])]} />
        <Sel
          id="al-dec"
          label="Decision"
          value={dec}
          onChange={(v) => set({ decision: v || undefined })}
          options={[
            ['', 'Decision: all'],
            ['permitted', 'Decision: permitted'],
            ['denied', 'Decision: denied'],
          ]}
        />
        <Sel id="al-op" label="Operation" value={op} onChange={(v) => set({ op: v || undefined })} options={[['', 'Operation: all'], ...ops.map((o) => [o, o] as [string, string])]} />
        <Sel id="al-src" label="Source" value={src} onChange={(v) => set({ src: v || undefined })} options={KIND_OPTIONS} />
        <Sel id="al-h" label="Period" value={hours} onChange={(v) => set({ hours: v === '24' ? undefined : v })} options={PERIODS.map((x) => [x.value, x.label])} />
      </div>
      <div className="cat-chips">
        {CATEGORY_ORDER.filter((c) => c !== 'settings' || events.some((e) => categoryOf(e) === 'settings')).map((c) => (
          <button key={c} type="button" className={`cat-chip ${cat === c ? 'on' : ''}`} onClick={() => set({ cat: cat === c ? undefined : c })}>
            {CATEGORY_LABEL[c]}
          </button>
        ))}
        <span className="sm muted" style={{ marginLeft: 'auto' }}>
          Click a category to filter
        </span>
      </div>

      <div className="row-wrap">
        <section className="card col-main" style={{ padding: 0, minWidth: 0 }}>
          {error && !data ? (
            <ErrorState error={error} onRetry={reload} />
          ) : loading && !data ? (
            <SkTable rows={8} cols={7} />
          ) : rows.length === 0 ? (
            <Empty title="No events match">Widen the period or clear a filter.</Empty>
          ) : (
            <>
              <div className="scroll">
                <table className="tbl audit-tbl" style={{ minWidth: 700 }}>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Actor</th>
                      <th>Category</th>
                      <th>Operation</th>
                      <th>Target</th>
                      <th>Scope</th>
                      <th>Decision</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((e) => (
                      <tr key={e.id} className={`clickable ${selected?.id === e.id ? 'is-sel' : ''}`} onClick={() => set({ event: String(e.id), page: p.get('page') ?? undefined })}>
                        <td className="mono" style={{ whiteSpace: 'nowrap' }}>
                          {hhmm(e.timestamp)}
                        </td>
                        <td>
                          <ActorCell e={e} />
                        </td>
                        <td>
                          <span className="tag">{CATEGORY_LABEL[categoryOf(e)]}</span>
                        </td>
                        <td className="mono sm" style={{ overflowWrap: 'anywhere', maxWidth: 150 }}>{e.operation}</td>
                        <td style={{ maxWidth: 170 }}>
                          <Target e={e} max={28} />
                        </td>
                        <td>
                          <ScopeCell e={e} />
                        </td>
                        <td className="sm" style={{ minWidth: 100, maxWidth: 130 }}>
                          <DecisionCell e={e} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager page={page} perPage={perPage} total={total} onPage={(pg) => set({ page: String(pg) })} noun="events" />
            </>
          )}
        </section>
        <aside className="col-side" style={{ flex: '1 1 280px', maxWidth: 330 }}>
          <EventDetail e={selected} onRelated={(e) => set({ q: str(meta(e).trace_id) ?? e.actor_id, event: undefined })} />
          <Info>Events about personal records keep ID, owner, operation and decision. Content, previews and embeddings are never logged.</Info>
          {!!data?.hidden && (
            <p className="sm muted" style={{ margin: 0 }}>
              {fmtInt(data.hidden)} operations on personal records in this period are counted but not listed: only super-users audit user-scope activity.
            </p>
          )}
        </aside>
      </div>
    </>
  );
};

const EventDetail: React.FC<{ e: AuditEvent | null; onRelated: (e: AuditEvent) => void }> = ({ e, onRelated }) => {
  const notify = useToast();
  const canSee = useCanSee();
  if (!e)
    return (
      <section className="card">
        <h2 data-h="3">Event detail</h2>
        <p className="sm muted" style={{ marginTop: 10 }}>
          Select an event to see its detail.
        </p>
      </section>
    );
  const m = meta(e);
  const d = decision(e);
  const client = [str(m.client_id) ?? (m.via === 'dashboard' ? 'dashboard' : e.actor_type === 'agent' || e.driver_id ? 'mcp' : undefined), str(m.session_id) ? `session ${m.session_id}` : undefined]
    .filter(Boolean)
    .join(' · ');
  const before = e.change ? `v${e.change.before.version}` : str(m.before);
  const after = e.change ? `v${e.change.after.version}` : str(m.after);
  const trace = str(m.trace_id) ?? str(m.correlation_id);
  const role = str(m.actor_role);
  return (
    <section className="card">
      <div className="card-head">
        <h2 data-h="3">Event detail</h2>
        <span className="tag">{CATEGORY_LABEL[categoryOf(e)]}</span>
      </div>
      <dl className="detail-kv">
        <dt>Event ID</dt>
        <dd className="mono">{String(e.id).length > 14 ? `${String(e.id).slice(0, 8)}…${String(e.id).slice(-3)}` : e.id}</dd>
        <dt>Time</dt>
        <dd>{utcStamp(e.timestamp)}</dd>
        <dt>Actor</dt>
        <dd>
          {e.actor_id}
          {role === 'admin' ? ' · Platform Admin' : role === 'superuser' ? ' · Super Admin' : ` · ${actorKind(e)}`}
          {e.driver_id && e.driver_id !== e.actor_id ? ` for ${e.driver_id}` : ''}
        </dd>
        {client && (
          <>
            <dt>Client</dt>
            <dd>{client}</dd>
          </>
        )}
        <dt>Operation</dt>
        <dd className="mono">{e.operation}</dd>
        <dt>Target</dt>
        <dd>
          {canSee(e) ? (
            e.memory_id ? (
              <a href={memoryHref(e.memory_id)}>
                <Target e={e} max={60} />
              </a>
            ) : (
              <Target e={e} max={60} />
            )
          ) : (
            <>
              <Hidden id={e.memory_id} />
              <div className="sm muted" style={{ marginTop: 4 }}>
                owner {e.owner_id}
              </div>
            </>
          )}
        </dd>
        {(before || after) && (
          <>
            <dt>Before → after</dt>
            <dd>
              {before ?? '—'} → {after ?? '—'}
            </dd>
          </>
        )}
        {str(m.reason) && (
          <>
            <dt>Reason</dt>
            <dd>{str(m.reason)}</dd>
          </>
        )}
        <dt>Decision</dt>
        <dd className={d.cls} style={{ fontWeight: 600 }}>
          {d.label}
          {d.reason ? ` · ${d.reason}` : ''}
        </dd>
        {trace && (
          <>
            <dt>Trace</dt>
            <dd className="mono">{trace}</dd>
          </>
        )}
      </dl>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginTop: 16, flexWrap: 'wrap' }}>
        <button type="button" className="btn bs sm-btn" onClick={() => onRelated(e)}>
          Show related events
        </button>
        <button
          type="button"
          className="link-btn"
          style={{ textDecoration: 'none' }}
          onClick={() => {
            const url = `${location.origin}${location.pathname}${buildHash('/audit', { event: String(e.id) })}`;
            void navigator.clipboard?.writeText(url).then(
              () => notify('Event link copied.'),
              () => notify(url),
            );
          }}
        >
          Copy event link
        </button>
      </div>
    </section>
  );
};

/* ------------------------------------------------------------------ */
/* Activity log: data operations by people and agents                   */
/* ------------------------------------------------------------------ */

const ActivityView: React.FC<{ route: HashRoute }> = ({ route }) => {
  const p = route.params;
  const hours = p.get('hours') ?? '168';
  const q = p.get('q') ?? '';
  const src = p.get('src') ?? '';
  const op = p.get('op') ?? '';
  const scope = p.get('scope') ?? '';
  const page = Number(p.get('page') || 1);
  const set = (c: Record<string, string | undefined>) => setParams(route, c);
  const { data, error, loading, reload } = useEvents(Number(hours));
  const all = (data?.items ?? []).filter((e) => DATA_OPS.has(e.operation) || DATA_OPS.has(e.event_type));
  const rows = all.filter((e) => {
    if (src && kindOf(e) !== src) return false;
    if (op && e.operation !== op) return false;
    if (scope && e.scope !== scope) return false;
    if (q && !`${e.actor_id} ${e.driver_id ?? ''} ${e.memory_id ?? ''}`.toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });
  const perPage = 25;
  const shown = rows.slice((page - 1) * perPage, page * perPage);
  const isWrite = (e: AuditEvent) => /write|update|delete|restore|promote/.test(e.operation);
  const ok = all.filter((e) => e.decision !== 'denied');
  const peopleWrites = ok.filter((e) => isWrite(e) && kindOf(e) === 'human').length;
  const agentWrites = ok.filter((e) => isWrite(e) && kindOf(e) !== 'human');
  const reads = ok.filter((e) => !isWrite(e)).length;
  const blocked = all.filter((e) => e.decision === 'denied' && isWrite(e)).length;
  const byActor = new Map<string, { w: number; r: number; kind: string }>();
  ok.forEach((e) => {
    const k = byActor.get(e.actor_id) ?? { w: 0, r: 0, kind: actorKind(e) };
    if (isWrite(e)) k.w += 1;
    else k.r += 1;
    byActor.set(e.actor_id, k);
  });
  const top = [...byActor.entries()].sort((a, b) => b[1].w + b[1].r - (a[1].w + a[1].r)).slice(0, 7);
  const max = Math.max(1, ...top.map(([, v]) => v.w + v.r));
  const per = periodOf(hours).short;

  return (
    <>
      <div className="filters">
        <SearchBox id="ac-q" placeholder="Search actor or record ID" value={q} onChange={(v) => set({ q: v || undefined })} />
        <Sel id="ac-src" label="Actor" value={src} onChange={(v) => set({ src: v || undefined })} options={KIND_OPTIONS.map(([v, l]) => [v, l.replace('Source', 'Actor')])} />
        <Sel id="ac-op" label="Operation" value={op} onChange={(v) => set({ op: v || undefined })} options={[['', 'Operation: all'], ...[...DATA_OPS].map((o) => [o, o] as [string, string])]} />
        <Sel
          id="ac-scope"
          label="Scope"
          value={scope}
          onChange={(v) => set({ scope: v || undefined })}
          options={[
            ['', 'Scope: all'],
            ['user', 'Scope: personal (metadata)'],
            ['project', 'Scope: project'],
            ['organizational', 'Scope: organization'],
          ]}
        />
        <Sel id="ac-h" label="Period" value={hours} onChange={(v) => set({ hours: v === '168' ? undefined : v })} options={PERIODS.map((x) => [x.value, x.label])} />
      </div>
      {error && !data ? (
        <section className="card">
          <ErrorState error={error} onRetry={reload} />
        </section>
      ) : (
        <>
          <div className="grid-kpi">
            <Tile label={`Writes by people · ${per}`} value={data ? peopleWrites : null} sub="dashboard edits and imports" />
            <Tile label={`Writes by agents · ${per}`} value={data ? agentWrites.length : null} sub={`${new Set(agentWrites.map((e) => e.actor_id)).size} agents`} />
            <Tile label={`Searches & reads · ${per}`} value={data ? reads : null} sub="served to people and agents" />
            <Tile label="Blocked by policy" value={data ? blocked : null} sub="nothing was stored" />
          </div>
          <div className="row-wrap">
            <section className="card col-main" style={{ padding: 0, minWidth: 0 }}>
              {loading && !data ? (
                <SkTable rows={6} cols={6} />
              ) : rows.length === 0 ? (
                <Empty compact title="No data operations">Nothing matches in this period.</Empty>
              ) : (
                <>
                  <div className="scroll">
                    <table className="tbl" style={{ minWidth: 720 }}>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Actor</th>
                          <th>Operation</th>
                          <th>Memory</th>
                          <th>Scope</th>
                          <th>Decision</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shown.map((e) => (
                          <tr key={e.id}>
                            <td className="mono" style={{ whiteSpace: 'nowrap' }}>
                              {hhmm(e.timestamp)}
                            </td>
                            <td>
                              <ActorCell e={e} />
                            </td>
                            <td className="mono sm">{e.operation}</td>
                            <td style={{ maxWidth: 240 }}>
                              <Target e={e} />
                            </td>
                            <td>
                              <ScopeCell e={e} />
                            </td>
                            <td className="sm">
                              <DecisionCell e={e} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pager page={page} perPage={perPage} total={rows.length} onPage={(pg) => set({ page: String(pg) })} noun="operations" />
                </>
              )}
            </section>
            <aside className="col-side" style={{ flex: '1 1 280px', maxWidth: 330 }}>
              <section className="card">
                <h2 data-h="3">Most active · {per}</h2>
                {top.length === 0 ? (
                  <p className="sm muted" style={{ marginTop: 10 }}>No activity.</p>
                ) : (
                  <div className="reason-bars">
                    {top.map(([a, v]) => (
                      <div key={a}>
                        <div className="stage-head">
                          <span>
                            {a} <span className="muted sm">· {v.kind}</span>
                          </span>
                          <span className="muted">{v.w + v.r}</span>
                        </div>
                        <div className="stackbar" title={`${v.w} writes · ${v.r} searches and reads`}>
                          <span style={{ width: `${(v.w / max) * 100}%`, background: '#0066cc' }} />
                          <span style={{ width: `${(v.r / max) * 100}%`, background: '#73bcf7' }} />
                        </div>
                      </div>
                    ))}
                    <div className="sm muted" style={{ display: 'flex', gap: 14 }}>
                      <span>
                        <span className="legend-dot" style={{ background: '#0066cc' }} /> writes
                      </span>
                      <span>
                        <span className="legend-dot" style={{ background: '#73bcf7' }} /> searches &amp; reads
                      </span>
                    </div>
                  </div>
                )}
              </section>
              <Info>Personal records show ID and owner only. Who read a specific record is on its Who read tab.</Info>
            </aside>
          </div>
        </>
      )}
    </>
  );
};

const Tile: React.FC<{ label: string; value: number | null; sub: React.ReactNode }> = ({ label, value, sub }) => (
  <section className="card">
    <div className="sm muted">{label}</div>
    {value === null ? (
      <SkLines lines={2} />
    ) : (
      <>
        <div className="kpi">{fmtInt(value)}</div>
        <div className="sm">{sub}</div>
      </>
    )}
  </section>
);

/* ------------------------------------------------------------------ */
/* Denied only                                                          */
/* ------------------------------------------------------------------ */

type Reason = { key: string; group: 'policy' | 'capability' | 'suspended' | 'cross'; label: string; cls: string };
const reasonOf = (e: AuditEvent): Reason => {
  const m = meta(e);
  const rule = str(m.rule);
  const r = (str(m.reason) ?? str(m.detail) ?? '').toLowerCase();
  if (m.cross_tenant) return { key: 'cross', group: 'cross', label: 'cross-tenant', cls: 'red' };
  if (rule) return { key: `rule:${rule}`, group: 'policy', label: `rule ${rule}`, cls: 'red' };
  if (/suspend|revok/.test(r)) {
    const inc = str(m.incident_ref);
    return { key: `susp:${inc ?? ''}`, group: 'suspended', label: `client suspended${inc ? ` · ${inc}` : ''}`, cls: 'ylw' };
  }
  const why = r.includes('member') ? 'not a member' : r.includes('owner') || e.scope === 'user' ? 'not owner' : str(m.capability) ? `needs ${m.capability}` : r ? truncate(r, 20) : 'missing';
  return { key: `cap:${why}`, group: 'capability', label: `no capability · ${why}`, cls: 'g' };
};

const DeniedView: React.FC<{ route: HashRoute }> = ({ route }) => {
  const p = route.params;
  const hours = p.get('hours') ?? '168';
  const q = p.get('q') ?? '';
  const rf = p.get('reason') ?? '';
  const kf = p.get('src') ?? '';
  const [grouped, setGrouped] = useState(true);
  const set = (c: Record<string, string | undefined>) => setParams(route, c);
  const h = Number(hours);
  // Twice the period: this period's denials and the previous period's for the trend.
  const { data, error, loading, reload } = useEvents(h * 2, { decision: 'denied' });
  const since = Date.now() - h * 3600000;
  const cur = (data?.items ?? []).filter((e) => e.decision === 'denied' && Date.parse(e.timestamp) >= since);
  const prev = (data?.items ?? []).filter((e) => e.decision === 'denied' && Date.parse(e.timestamp) < since).length;
  const rows = cur.filter((e) => {
    const r = reasonOf(e);
    if (rf && r.group !== rf) return false;
    if (kf && kindOf(e) !== kf) return false;
    if (q && !`${e.actor_id} ${e.driver_id ?? ''} ${e.memory_id ?? ''} ${r.label}`.toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });
  const groups = useMemo(() => {
    const map = new Map<string, { key: string; last: AuditEvent; n: number; reason: Reason }>();
    rows.forEach((e) => {
      const r = reasonOf(e);
      const key = `${e.actor_id}|${e.driver_id ?? ''}|${r.key}|${e.operation}`;
      const g = map.get(key);
      if (!g) map.set(key, { key, last: e, n: 1, reason: r });
      else {
        g.n += 1;
        if (Date.parse(e.timestamp) > Date.parse(g.last.timestamp)) g.last = e;
      }
    });
    return [...map.values()].sort((a, b) => Date.parse(b.last.timestamp) - Date.parse(a.last.timestamp));
  }, [rows]);
  const list = grouped ? groups : rows.map((e) => ({ key: String(e.id), last: e, n: 1, reason: reasonOf(e) }));
  const byGroup = { policy: 0, capability: 0, suspended: 0, cross: 0 };
  const rules = new Map<string, number>();
  cur.forEach((e) => {
    const r = reasonOf(e);
    byGroup[r.group] += 1;
    if (r.group === 'policy') rules.set(r.label.replace('rule ', ''), (rules.get(r.label.replace('rule ', '')) ?? 0) + 1);
  });
  const topRules = [...rules.entries()].sort((a, b) => b[1] - a[1]);
  const ruleSub = topRules.length
    ? [...topRules.slice(0, 2).map(([n, c]) => `${n} ${c}`), ...(topRules.length > 2 ? [`other ${topRules.slice(2).reduce((a, [, c]) => a + c, 0)}`] : [])].join(' · ')
    : 'none in this period';
  const trend = prev ? Math.round(((cur.length - prev) / prev) * 100) : null;
  const attention = groups.filter((g) => g.n >= 5 && g.reason.group !== 'policy').slice(0, 3);
  const maxR = Math.max(1, byGroup.policy, byGroup.capability, byGroup.suspended);
  const per = periodOf(hours).short;

  const actionFor = (g: { last: AuditEvent; reason: Reason }) => {
    const e = g.last;
    if (g.reason.group === 'policy') return { label: 'Open rule', href: buildHash('/curation', { q: g.reason.label.replace('rule ', '') }) };
    if (g.reason.group === 'suspended') return { label: 'Open client', href: buildHash('/clients', { q: e.driver_id ?? e.actor_id }) };
    if (kindOf(e) !== 'human' && g.reason.label.includes('member')) return { label: 'Open identity', href: buildHash('/identities', { q: e.actor_id }) };
    return { label: 'Show event', href: buildHash('/audit', { event: String(e.id), hours: hours === '24' ? undefined : hours }) };
  };

  return (
    <>
      <div className="filters">
        <SearchBox id="dn-q" placeholder="Search actor, target, rule" value={q} onChange={(v) => set({ q: v || undefined })} />
        <Sel
          id="dn-r"
          label="Reason"
          value={rf}
          onChange={(v) => set({ reason: v || undefined })}
          options={[
            ['', 'Reason: all'],
            ['policy', 'Reason: policy rule'],
            ['capability', 'Reason: missing capability'],
            ['suspended', 'Reason: suspended client'],
            ['cross', 'Reason: cross-tenant'],
          ]}
        />
        <Sel id="dn-k" label="Actor type" value={kf} onChange={(v) => set({ src: v || undefined })} options={KIND_OPTIONS.map(([v, l]) => [v, l.replace('Source', 'Actor type')])} />
        <Sel id="dn-h" label="Period" value={hours} onChange={(v) => set({ hours: v === '168' ? undefined : v })} options={PERIODS.map((x) => [x.value, x.label])} />
      </div>
      {error && !data ? (
        <section className="card">
          <ErrorState error={error} onRetry={reload} />
        </section>
      ) : (
        <>
          <div className="grid-kpi">
            <Tile
              label={`Denied · ${per}`}
              value={data ? cur.length : null}
              sub={trend === null ? 'no earlier period to compare' : `${trend <= 0 ? '▼' : '▲'} ${Math.abs(trend)}% vs. previous period`}
            />
            <Tile label="Policy rules" value={data ? byGroup.policy : null} sub={ruleSub} />
            <Tile label="Missing capability" value={data ? byGroup.capability : null} sub={byGroup.capability ? 'mostly reads of others’ records' : 'none in this period'} />
            <Tile label="Cross-tenant" value={data ? byGroup.cross : null} sub="in this tenant" />
          </div>
          <div className="row-wrap">
            <section className="card col-main" style={{ padding: 0, minWidth: 0 }}>
              {loading && !data ? (
                <SkTable rows={6} cols={6} />
              ) : list.length === 0 ? (
                <Empty compact title="No denied operations">Nothing was refused in this period{rf || kf || q ? ' with these filters' : ''}.</Empty>
              ) : (
                <>
                  <div className="scroll">
                    <table className="tbl denied-tbl" style={{ minWidth: 640 }}>
                      <thead>
                        <tr>
                          <th>Last seen</th>
                          <th>Actor</th>
                          <th>Operation</th>
                          <th>Target</th>
                          <th>Reason</th>
                          <th>{grouped ? 'Repeats' : ''}</th>
                          <th><span className="vh">Actions</span></th>
                        </tr>
                      </thead>
                      <tbody>
                        {list.map((g) => {
                          const e = g.last;
                          const a = actionFor(g);
                          return (
                            <tr key={g.key}>
                              <td className="mono" style={{ whiteSpace: 'nowrap' }}>
                                {hhmm(e.timestamp, false)}
                              </td>
                              <td>
                                {e.actor_id}
                                {e.driver_id && e.driver_id !== e.actor_id ? ` · ${e.driver_id}` : ''}
                              </td>
                              <td className="mono sm">{e.operation}</td>
                              <td>{e.memory_id && e.scope !== 'user' ? <Target e={e} max={22} /> : <ScopeCell e={e} />}</td>
                              <td>
                                <span className={`lbl ${g.reason.cls}`}>{g.reason.label}</span>
                              </td>
                              <td>{grouped ? g.n : ''}</td>
                              <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                                <a href={a.href}>{a.label}</a>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="sm muted" style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 20px', flexWrap: 'wrap', gap: 10 }}>
                    <span>{grouped ? `Grouped by actor + reason · ${groups.length} groups, ${rows.length} events` : `${rows.length} events`}</span>
                    <button type="button" className="link-btn" onClick={() => setGrouped(!grouped)}>
                      {grouped ? 'Show ungrouped' : 'Group by actor + reason'}
                    </button>
                  </div>
                </>
              )}
            </section>
            <aside className="col-side" style={{ flex: '1 1 280px', maxWidth: 330 }}>
              <section className="card">
                <div className="card-head">
                  <h2 data-h="3">Needs attention</h2>
                  <span className={`lbl ${attention.length ? 'ylw' : 'grn'}`}>{attention.length}</span>
                </div>
                {attention.length === 0 ? (
                  <p className="sm muted" style={{ marginTop: 10 }}>No repeated denials worth acting on.</p>
                ) : (
                  <>
                    <ul className="attn">
                      {attention.map((g) => (
                        <li key={g.key}>
                          <span className="legend-dot" style={{ background: '#f0ab00' }} />
                          <div>
                            <div>
                              {g.reason.group === 'suspended'
                                ? `${g.last.actor_id} still retries after suspension`
                                : g.last.operation.includes('search')
                                  ? `${g.last.actor_id} keeps searching ${g.last.scope === 'project' ? 'a project' : 'records'} it can’t read`
                                  : `${g.last.actor_id} keeps calling ${g.last.operation} without access`}
                            </div>
                            <div className="sm muted">
                              {g.reason.group === 'suspended'
                                ? `Covered by ${g.reason.label.split(' · ')[1] ?? 'the suspension'}`
                                : `${g.n} denials · probably a wrong ${g.last.scope === 'project' ? 'project' : 'scope'} in its config`}
                            </div>
                          </div>
                        </li>
                      ))}
                    </ul>
                    {attention.find((g) => g.reason.group !== 'suspended') && (
                      <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', marginTop: 12 }}>
                        <a className="btn bs" href={buildHash('/identities', { q: attention.find((g) => g.reason.group !== 'suspended')!.last.actor_id })}>
                          Suspend {truncate(attention.find((g) => g.reason.group !== 'suspended')!.last.actor_id, 14)}…
                        </a>
                        <a href={buildHash('/accounts', { q: attention.find((g) => g.reason.group !== 'suspended')!.last.driver_id ?? '' })}>Contact owner</a>
                      </div>
                    )}
                  </>
                )}
              </section>
              <section className="card">
                <h2 data-h="3">By reason</h2>
                <div className="reason-bars">
                  {(
                    [
                      ['Policy rule', byGroup.policy, '#a30000'],
                      ['Missing capability', byGroup.capability, '#0066cc'],
                      ['Suspended client', byGroup.suspended, '#f0ab00'],
                    ] as const
                  ).map(([l, v, c]) => (
                    <div key={l}>
                      <div className="stage-head">
                        <span>{l}</span>
                        <span className="muted">{v}</span>
                      </div>
                      <div className="bar thin">
                        <span style={{ width: `${(v / maxR) * 100}%`, background: c }} />
                      </div>
                    </div>
                  ))}
                </div>
              </section>
              <Info>A denial never shows the content that was refused — for writes, nothing was stored.</Info>
            </aside>
          </div>
        </>
      )}
    </>
  );
};

/* ------------------------------------------------------------------ */
/* Forensics                                                            */
/* ------------------------------------------------------------------ */

const localInput = (d: Date) => {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const ForensicsView: React.FC<{ route: HashRoute; grants: BreakGlassState | null }> = ({ route, grants }) => {
  const ids = useApi(() => api.identities(), []);
  const settings = useApi<SettingsResponse>(() => api.settings(), []);
  const day = useEvents(24);
  const [agent, setAgent] = useState(route.params.get('actor') || '');
  const [session, setSession] = useState('');
  const [at, setAt] = useState(localInput(new Date()));
  const [cat, setCat] = useState<Category | ''>('');
  const [dec, setDec] = useState('');
  const atIso = new Date(at).toISOString();
  const fx = useApi<ForensicsResponse | null>(
    () => (agent ? api.forensics({ actor: agent, at: atIso, session_id: session || undefined, window_minutes: 60 }) : Promise.resolve(null)),
    [agent, atIso, session],
  );
  const actorEvents = useApi<AuditEvent[]>(
    async () => (agent ? (await api.audit({ actor: agent, hours: Math.max(1, Math.ceil((Date.now() - Date.parse(atIso)) / 3600000) + 1), per_page: 200 })).items : []),
    [agent, atIso],
  );
  const canSee = useCanSee();
  const agentOptions = (ids.data?.items ?? []).map((i) => ({ id: i.id, label: `${i.name}${i.bound_to ? ` · ${i.bound_to}` : ''}` }));
  const atMs = Date.parse(atIso);
  const sessions = [...new Set((actorEvents.data ?? []).map((e) => str(meta(e).session_id)).filter(Boolean) as string[])];

  type Row = { key: string; time: string; op: string; id: string | null; stub: string; scope: string; delivered: string; dec: React.ReactNode };
  const rows: Row[] = [];
  (fx.data?.context ?? []).forEach((c) =>
    rows.push({
      key: `c${c.id}`,
      time: c.served_at,
      op: fx.data?.last_search_at === c.served_at ? 'search_memory' : 'read_memory',
      id: c.id,
      stub: c.stub,
      scope: c.scope,
      delivered: c.delivery === 'stub' ? 'index' : 'full',
      dec: c.changed_after ? (
        <span className="warn" style={{ fontWeight: 600 }}>
          Permitted · changed since (v{c.version_now})
        </span>
      ) : c.deleted ? (
        <span className="warn" style={{ fontWeight: 600 }}>
          Permitted · deleted since
        </span>
      ) : (
        <span className="ok" style={{ fontWeight: 600 }}>
          Permitted
        </span>
      ),
    }),
  );
  (actorEvents.data ?? [])
    .filter((e) => /write|update/.test(e.operation) && Date.parse(e.timestamp) <= atMs && Date.parse(e.timestamp) >= atMs - 3600000)
    .forEach((e) =>
      rows.push({
        key: `e${e.id}`,
        time: e.timestamp,
        op: 'write_memory',
        id: e.memory_id,
        stub: e.memory_stub ?? '',
        scope: e.scope,
        delivered: '—',
        dec: <DecisionCell e={e} />,
      }),
    );
  rows.sort((a, b) => Date.parse(a.time) - Date.parse(b.time));
  const served = (fx.data?.context ?? []).length;
  const written = rows.length - served;

  const recent = (day.data?.items ?? []).filter((e) => (!cat || categoryOf(e) === cat) && (!dec || (dec === 'denied' ? e.decision === 'denied' : e.decision !== 'denied'))).slice(0, 8);
  const all24 = day.data?.items ?? [];
  const sec = {
    failed: all24.filter((e) => /auth|login|sign/.test(e.event_type) && e.decision === 'denied').length,
    tools: all24.filter((e) => e.decision === 'denied' && !str(meta(e).rule)).length,
    policy: all24.filter((e) => e.decision === 'denied' && str(meta(e).rule)).length,
    cross: all24.filter((e) => meta(e).cross_tenant).length,
  };
  const a = settings.data?.values.audit;
  const g = grants?.active ?? grants?.grants.find((x) => x.active) ?? null;

  return (
    <>
      <section className="card">
        <div className="card-head">
          <h2 data-h="3">What did the agent know?</h2>
          {agent && (
            <a className="sm" href={buildHash('/audit', { tab: 'activity', q: agent })}>
              List sessions
            </a>
          )}
        </div>
        <div className="fx-form">
          <div className="f">
            <label htmlFor="fx-ag">Agent</label>
            <select id="fx-ag" className="in" value={agent} onChange={(e) => setAgent(e.target.value)}>
              <option value="">Choose an agent…</option>
              {agentOptions.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
              {agent && !agentOptions.some((o) => o.id === agent) && <option value={agent}>{agent}</option>}
            </select>
          </div>
          <div className="f">
            <label htmlFor="fx-ss">Session</label>
            <select id="fx-ss" className="in" value={session} onChange={(e) => setSession(e.target.value)} disabled={!agent}>
              <option value="">Any session in the hour before</option>
              {sessions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="f">
            <label htmlFor="fx-at">At</label>
            <input id="fx-at" className="in" type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} />
          </div>
        </div>
      </section>

      <div className="row-wrap">
        <div className="col-main" style={{ minWidth: 0 }}>
          <section className="card">
            <div className="card-head">
              <h2 data-h="3">{agent ? `Memories served to ${agent} at ${hhmm(atIso, false)}` : 'Memories served'}</h2>
              {fx.data && (
                <span className="sm muted">
                  {served} served · {written} written
                </span>
              )}
            </div>
            {!agent ? (
              <p className="sm muted" style={{ marginTop: 10 }}>
                Pick an agent and a moment. The audit log is replayed to show which version of each memory it was given, and whether it has changed since.
              </p>
            ) : fx.error ? (
              <ErrorState error={fx.error} compact onRetry={fx.reload} />
            ) : fx.loading && !fx.data ? (
              <SkLines lines={4} />
            ) : rows.length === 0 ? (
              <Empty compact title="Nothing served in that hour">
                {fx.data?.events ? `${fx.data.events} audit events found, but none referenced a memory.` : `No audit events for ${agent} in the hour before that time.`}
              </Empty>
            ) : (
              <>
                <div className="scroll">
                  <table className="tbl" style={{ minWidth: 640, marginTop: 8 }}>
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Operation</th>
                        <th>Memory</th>
                        <th>Scope</th>
                        <th>Delivered</th>
                        <th>Decision</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.key}>
                          <td className="mono">{hhmm(r.time)}</td>
                          <td className="mono sm">{r.op}</td>
                          <td style={{ maxWidth: 200 }}>
                            {!canSee({ scope: r.scope }) ? (
                              r.id ? <Hidden id={r.id} /> : <span className="muted">—</span>
                            ) : r.id ? (
                              <a href={memoryHref(r.id)}>{truncate(r.stub || shortId(r.id), 40)}</a>
                            ) : (
                              <span className="muted">—</span>
                            )}
                          </td>
                          <td>{r.scope === 'user' ? <ScopeLabel scope="user"><Icon.Lock size={11} /> User</ScopeLabel> : <ScopeLabel scope={r.scope} />}</td>
                          <td>{r.delivered}</td>
                          <td className="sm">{r.dec}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {rows.some((r) => !canSee({ scope: r.scope })) && (
                  <p className="sm muted" style={{ margin: '10px 0 0' }}>
                    To see the hidden content, link this view to an incident and request a grant from a Super Admin.
                  </p>
                )}
              </>
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <h2 data-h="3">Audit log</h2>
              <span className="sm muted">Last 24 hours</span>
            </div>
            <div className="filters" style={{ margin: '10px 0' }}>
              <Sel id="fx-cat" label="Category" value={cat} onChange={(v) => setCat(v as Category | '')} options={[['', 'Category: all'], ...CATEGORY_ORDER.map((c) => [c, `Category: ${CATEGORY_LABEL[c]}`] as [string, string])]} />
              <Sel
                id="fx-dec"
                label="Decision"
                value={dec}
                onChange={setDec}
                options={[
                  ['', 'Decision: all'],
                  ['permitted', 'Decision: permitted'],
                  ['denied', 'Decision: denied'],
                ]}
              />
            </div>
            {day.loading && !day.data ? (
              <SkLines lines={4} />
            ) : recent.length === 0 ? (
              <p className="sm muted">No events.</p>
            ) : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Target</th>
                    <th>Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((e) => (
                    <tr key={e.id}>
                      <td className="mono">{hhmm(e.timestamp, false)}</td>
                      <td>
                        <ActorCell e={e} sub={false} />
                      </td>
                      <td className="mono sm">{e.operation}</td>
                      <td style={{ maxWidth: 220 }}>
                        <Target e={e} max={30} />
                      </td>
                      <td className={decision(e).cls} style={{ fontWeight: 600 }}>
                        {decision(e).label}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <a className="sm" href={buildHash('/audit')} style={{ display: 'inline-block', marginTop: 10 }}>
              Open the full audit log →
            </a>
          </section>
        </div>

        <aside className="col-side" style={{ flex: '1 1 280px', maxWidth: 330 }}>
          <section className="card">
            <div className="card-head">
              <h2 data-h="3">Retention</h2>
              <a className="sm" href={buildHash('/audit', { tab: 'retention' })}>
                Edit
              </a>
            </div>
            {!a ? (
              <SkLines lines={4} />
            ) : (
              <dl className="detail-kv">
                <dt>Full-detail events</dt>
                <dd>{a.full_retention_days} days</dd>
                <dt>Summary events</dt>
                <dd>{a.retention?.summary_days ?? 400} days</dd>
                <dt>Read operation detail</dt>
                <dd>{a.read_detail === 'sample' ? 'sample 1/N' : a.read_detail}</dd>
                <dt>Privileged access events</dt>
                <dd>7 years · immutable</dd>
              </dl>
            )}
            <p className="sm muted" style={{ marginTop: 10 }}>
              Limits set by global policy; tenant can shorten, not extend.
            </p>
          </section>
          <section className="card">
            <div className="card-head">
              <h2 data-h="3">Incident grants on this tenant</h2>
            </div>
            <span className="lbl g" style={{ marginTop: 8 }}>
              read-only
            </span>
            {!grants ? (
              <p className="sm muted" style={{ marginTop: 10 }}>
                Grant metadata is not available to your role on this server.
              </p>
            ) : !g ? (
              <p className="sm muted" style={{ marginTop: 10 }}>
                No active grant. {grants.grants.length ? `${grants.grants.length} earlier grant${grants.grants.length === 1 ? '' : 's'} on record.` : ''}
              </p>
            ) : (
              <dl className="detail-kv">
                <dt className="mono">{grantId(g.id)}</dt>
                <dd>
                  {g.incident_ref} <span className="lbl blue">inspect</span>
                </dd>
                <dt>Requested / approved</dt>
                <dd>{g.username} / —</dd>
                <dt>Window</dt>
                <dd>
                  {hhmm(g.created_at, false)} → {hhmm(g.expires_at, false)}
                </dd>
                <dt>Reads so far</dt>
                <dd>{g.reads ?? 0}</dd>
              </dl>
            )}
            <p className="sm muted" style={{ marginTop: 10 }}>
              You see grant metadata, never the content read under it.
            </p>
          </section>
          <section className="card">
            <h2 data-h="3">Security · 24 h</h2>
            {day.loading && !day.data ? (
              <SkLines lines={5} />
            ) : (
              <dl className="detail-kv nums">
                <dt>Failed sign-ins</dt>
                <dd>{sec.failed}</dd>
                <dt>Unauthorized tool calls</dt>
                <dd>{sec.tools}</dd>
                <dt>Policy-denied</dt>
                <dd>{sec.policy}</dd>
                <dt>Cross-tenant</dt>
                <dd>{sec.cross}</dd>
                <dt>Privileged access</dt>
                <dd>{grants ? `${grants.grants.filter((x) => x.active).length || (grants.active ? 1 : 0)} grant` : '—'}</dd>
              </dl>
            )}
          </section>
        </aside>
      </div>
    </>
  );
};

/* ------------------------------------------------------------------ */
/* Incident grants                                                      */
/* ------------------------------------------------------------------ */

const grantId = (id: string) => (/^grt_/.test(id) ? id : shortId(id, 'grt'));
const grantType = (g: BreakGlassGrant) => (/delete|remediat|restore/i.test(g.justification) ? 'remediate' : 'inspect');
const grantStatus = (g: BreakGlassGrant) =>
  g.active ? { label: 'Active', cls: 'grn' } : g.ended_at && Date.parse(g.ended_at) < Date.parse(g.expires_at) ? { label: 'Ended', cls: 'g' } : { label: 'Expired', cls: 'g' };

const GrantsView: React.FC<{
  route: HashRoute;
  state: { data: BreakGlassState | null; error: Error | null; loading: boolean; reload: () => void };
  escalate: boolean;
  setEscalate: (v: boolean) => void;
}> = ({ route, state, escalate, setEscalate }) => {
  const { superuser } = useApp();
  const p = route.params;
  const statusF = p.get('status') ?? '';
  const typeF = p.get('type') ?? '';
  const days = p.get('days') ?? '90';
  const set = (c: Record<string, string | undefined>) => setParams(route, c);
  const month = new Date().toISOString().slice(0, 7);
  const report = useApi<BreakGlassReport>(() => api.breakGlassReport(month), [month]);
  const incidentEvents = useEvents(Number(days) * 24);
  const all: BreakGlassGrant[] = useMemo(() => {
    const list = [...(state.data?.grants ?? [])];
    if (state.data?.active && !list.some((g) => g.id === state.data!.active!.id)) list.unshift(state.data.active);
    return list;
  }, [state.data]);
  const since = Date.now() - Number(days) * 86400000;
  const grants = all.filter(
    (g) => Date.parse(g.created_at) >= since && (!statusF || grantStatus(g).label.toLowerCase() === statusF) && (!typeF || grantType(g) === typeF),
  );
  const sel = grants.find((g) => g.id === p.get('grant')) ?? grants[0] ?? null;
  const useLog = (incidentEvents.data?.items ?? []).filter(
    (e) => sel && (str(meta(e).grant_id) === sel.id || (categoryOf(e) === 'incident' && e.actor_id === sel.username && Date.parse(e.timestamp) >= Date.parse(sel.created_at) - 600000)),
  );

  return (
    <>
      <div className="filters">
        <Sel
          id="gr-st"
          label="Status"
          value={statusF}
          onChange={(v) => set({ status: v || undefined })}
          options={[
            ['', 'Status: all'],
            ['active', 'Status: active'],
            ['expired', 'Status: expired'],
            ['ended', 'Status: ended'],
          ]}
        />
        <Sel
          id="gr-ty"
          label="Type"
          value={typeF}
          onChange={(v) => set({ type: v || undefined })}
          options={[
            ['', 'Type: inspect · remediate'],
            ['inspect', 'Type: inspect'],
            ['remediate', 'Type: remediate'],
          ]}
        />
        <Sel
          id="gr-d"
          label="Period"
          value={days}
          onChange={(v) => set({ days: v === '90' ? undefined : v })}
          options={[
            ['30', 'Last 30 days'],
            ['90', 'Last 90 days'],
            ['365', 'Last 12 months'],
          ]}
        />
      </div>
      <div className="row-wrap">
        <div className="col-main" style={{ minWidth: 0 }}>
          <section className="card" style={{ padding: 0 }}>
            {state.error && !state.data ? (
              <div style={{ padding: 20 }}>
                <Empty compact title="Grant metadata is not available">
                  This server shows incident grants to super-users only ({errorMessage(state.error)}). You can still request an escalation.
                </Empty>
              </div>
            ) : state.loading && !state.data ? (
              <SkTable rows={3} cols={8} />
            ) : grants.length === 0 ? (
              <Empty compact title="No incident grants">No grant touched this tenant’s data in this period.</Empty>
            ) : (
              <div className="scroll">
                <table className="tbl" style={{ minWidth: 720 }}>
                  <thead>
                    <tr>
                      <th>Grant</th>
                      <th>Type</th>
                      <th>Incident</th>
                      <th>Requested / approved</th>
                      <th>Target</th>
                      <th>Window</th>
                      <th>Uses</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {grants.map((g) => {
                      const st = grantStatus(g);
                      const t = grantType(g);
                      return (
                        <tr key={g.id} className={`clickable ${sel?.id === g.id ? 'is-sel' : ''}`} onClick={() => set({ grant: g.id })}>
                          <td className="mono sm">{grantId(g.id)}</td>
                          <td>
                            <span className={`lbl ${t === 'inspect' ? 'blue' : 'red'}`}>{t}</span>
                          </td>
                          <td>{g.incident_ref}</td>
                          <td>{g.username} / —</td>
                          <td className="sm">{g.owners ? `${g.owners} owner${g.owners === 1 ? '' : 's'}` : '—'}</td>
                          <td className="sm">
                            {hhmm(g.created_at, false)} → {hhmm(g.expires_at, false)}
                          </td>
                          <td className="sm">{g.reads ? `${g.reads} read${g.reads === 1 ? '' : 's'}` : '—'}</td>
                          <td>
                            <span className={`lbl ${st.cls}`}>{st.label}</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          {sel && (
            <section className="card">
              <div className="card-head">
                <h2 data-h="3">{grantId(sel.id)} · use log</h2>
                <span className="sm muted">IDs and times only</span>
              </div>
              {incidentEvents.loading && !incidentEvents.data ? (
                <SkLines lines={3} />
              ) : useLog.length === 0 ? (
                <p className="sm muted" style={{ marginTop: 10 }}>
                  No reads under this grant yet.
                </p>
              ) : (
                <table className="tbl" style={{ marginTop: 8 }}>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Event</th>
                      <th>Record</th>
                      <th>Severity</th>
                      <th>Owner notified</th>
                    </tr>
                  </thead>
                  <tbody>
                    {useLog.map((e) => {
                      const high = Boolean(e.memory_id);
                      const notified = str(meta(e).owner_notified_at);
                      return (
                        <tr key={e.id}>
                          <td className="mono">{hhmm(e.timestamp)}</td>
                          <td className="mono sm">{e.operation}</td>
                          <td>{e.memory_id ? <Hidden id={e.memory_id} /> : <span className="muted">—</span>}</td>
                          <td>
                            <span className={`lbl ${high ? 'red' : 'ylw'}`}>{high ? 'High' : 'Medium'}</span>
                          </td>
                          <td className="sm">{notified ? <span className="ok">● {hhmm(notified, false)}</span> : <span className="muted">—</span>}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </section>
          )}
        </div>
        <aside className="col-side" style={{ flex: '1 1 280px', maxWidth: 330 }}>
          <section className="card">
            <h2 data-h="3">Your role in incidents</h2>
            <ul className="role-list">
              {(
                [
                  [true, 'See every grant on this tenant’s data'],
                  [true, 'Request escalation to Super Admins with a reason'],
                  [superuser, 'Approve or use a grant'],
                  [superuser, 'See content read under a grant'],
                ] as const
              ).map(([ok, l]) => (
                <li key={l}>
                  <span className={`role-mark ${ok ? 'on' : ''}`}>{ok ? <Icon.Check size={12} /> : <Icon.X size={12} />}</span>
                  {l}
                </li>
              ))}
            </ul>
            {superuser && (
              <a className="sm" href={buildHash('/incident')} style={{ display: 'inline-block', marginTop: 10 }}>
                Open Incident access →
              </a>
            )}
          </section>
          {escalate ? (
            <EscalationForm onClose={() => setEscalate(false)} />
          ) : (
            <section className="card">
              <h2 data-h="3">Request escalation</h2>
              <p className="sm muted" style={{ margin: '8px 0 12px' }}>
                Ask a Super Admin to inspect or remediate personal records. Say what you observed; never paste the content.
              </p>
              <button type="button" className="btn bs" onClick={() => setEscalate(true)}>
                Request escalation…
              </button>
            </section>
          )}
          <section className="card">
            <div className="card-head">
              <h2 data-h="3">Monthly report · {new Date().toLocaleDateString('en-US', { month: 'long' })}</h2>
            </div>
            <button
              type="button"
              className="link-btn"
              style={{ textDecoration: 'none', marginTop: 6 }}
              disabled={!report.data}
              onClick={() =>
                report.data &&
                downloadCsv(`incident-report-${report.data.month}.csv`, [
                  ['grant', 'user', 'incident', 'created', 'expires', 'reads', 'owners'],
                  ...report.data.grants.map((g) => [g.id, g.username, g.incident_ref, g.created_at, g.expires_at, g.reads, g.owners]),
                ])
              }
            >
              Download
            </button>
            {report.error && !report.data ? (
              <p className="sm muted" style={{ marginTop: 8 }}>
                Not available to your role on this server.
              </p>
            ) : !report.data ? (
              <SkLines lines={3} />
            ) : (
              <dl className="detail-kv nums">
                <dt>Grants on this tenant</dt>
                <dd>{report.data.totals.grants}</dd>
                <dt>Records read</dt>
                <dd>{report.data.totals.reads}</dd>
                <dt>Owners notified</dt>
                <dd>{report.data.totals.owners}</dd>
              </dl>
            )}
          </section>
        </aside>
      </div>
    </>
  );
};

const EscalationForm: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const notify = useToast();
  const [target, setTarget] = useState('');
  const [observed, setObserved] = useState('');
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    const text = `Escalation request\nRecords or owner: ${target}\nObserved: ${observed}`;
    try {
      await api.requestEscalation({ target: target.trim(), observed: observed.trim() });
      notify('Sent to the Security center. Super Admins will review it.');
      onClose();
    } catch (e) {
      try {
        await navigator.clipboard?.writeText(text);
        notify(`This server does not accept escalation requests yet (${errorMessage(e)}). The request was copied — send it to your Super Admins.`, 'err');
      } catch {
        notify(`This server does not accept escalation requests yet (${errorMessage(e)}).`, 'err');
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card">
      <h2 data-h="3">Request escalation</h2>
      <div className="f" style={{ marginTop: 12 }}>
        <label htmlFor="esc-t">Records or owner</label>
        <input id="esc-t" className="in mono" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="mem_4e21…b90 or a username" autoFocus />
      </div>
      <div className="f" style={{ marginTop: 12 }}>
        <label htmlFor="esc-o">What you observed</label>
        <textarea id="esc-o" className="in" style={{ minHeight: 70 }} value={observed} onChange={(e) => setObserved(e.target.value)} placeholder="Policy flag on a personal record; owner asked to restore." />
      </div>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginTop: 12 }}>
        <button type="button" className="btn bp" disabled={busy || !target.trim() || !observed.trim()} onClick={send}>
          {busy ? 'Sending…' : 'Send to Security center'}
        </button>
        <button type="button" className="link-btn" style={{ textDecoration: 'none' }} onClick={onClose}>
          Cancel
        </button>
      </div>
    </section>
  );
};

/* ------------------------------------------------------------------ */
/* Retention                                                            */
/* ------------------------------------------------------------------ */

type RetKey = 'admin' | 'data' | 'read' | 'denied' | 'conversations';
const DAY_OPTIONS = [7, 14, 30, 60, 90, 180, 365, 400];

const RetentionView: React.FC<{ onReady: (s: { ready: boolean; save: () => void } | null) => void }> = ({ onReady }) => {
  const notify = useToast();
  const settings = useApi<SettingsResponse>(() => api.settings(), []);
  const ops = useApi<OperationsResponse>(() => api.operations({ days: 7 }), []);
  const a = settings.data?.values.audit;
  const r = a?.retention;
  const initial = useMemo(
    () =>
      a
        ? {
            admin: { full: r?.admin_full_days ?? 90, summary: r?.admin_summary_days ?? 400 },
            data: { full: a.full_retention_days, summary: r?.summary_days ?? 180 },
            denied: { full: r?.denied_full_days ?? 90, summary: r?.denied_summary_days ?? 400 },
            conversations: { full: r?.conversation_days ?? 14, summary: 0 },
            read: a.read_detail,
          }
        : null,
    [a, r],
  );
  const [draft, setDraft] = useState<typeof initial>(null);
  const [reason, setReason] = useState('');
  const cur = draft ?? initial;
  const ceil = r?.ceilings ?? { admin: [400, 400], data: [90, 400], denied: [400, 400], conversations: [30, 30] };
  const stats = r?.stats ?? {};

  const changes: string[] = [];
  if (initial && cur) {
    const label: Record<string, string> = { admin: 'Administrative events', data: 'Data operations', denied: 'Denied operations', conversations: 'Conversations' };
    (['admin', 'data', 'denied', 'conversations'] as const).forEach((k) => {
      if (cur[k].full !== initial[k].full) changes.push(`${label[k]} full detail: ${initial[k].full} → ${cur[k].full} days`);
      if (cur[k].summary !== initial[k].summary) changes.push(`${label[k]} summary: ${initial[k].summary} → ${cur[k].summary} days`);
    });
    if (cur.read !== initial.read) changes.push(`Read operation detail: ${initial.read} → ${cur.read}`);
  }
  const dirty = changes.length > 0;
  const shortened = initial && cur ? (['admin', 'data', 'denied', 'conversations'] as const).filter((k) => cur[k].full < initial[k].full) : [];

  const save = async () => {
    if (!cur || !a) return;
    try {
      await api.saveSettings({
        audit: {
          ...a,
          full_retention_days: cur.data.full,
          read_detail: cur.read,
          retention: {
            ...(r ?? {}),
            admin_full_days: cur.admin.full,
            admin_summary_days: cur.admin.summary,
            summary_days: cur.data.summary,
            denied_full_days: cur.denied.full,
            denied_summary_days: cur.denied.summary,
            conversation_days: cur.conversations.full,
            reason: reason.trim(),
          },
        },
      });
      notify('Retention saved as an administrative event.');
      setDraft(null);
      setReason('');
      settings.reload();
    } catch (e) {
      notify(errorMessage(e), 'err');
    }
  };
  const ready = dirty && reason.trim().length >= 4;
  React.useEffect(() => {
    onReady({ ready, save });
    return () => onReady(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, reason, JSON.stringify(cur)]);

  const setDays = (k: Exclude<RetKey, 'read'>, part: 'full' | 'summary', v: number) => cur && setDraft({ ...cur, [k]: { ...cur[k], [part]: v } });
  const DaySel: React.FC<{ k: Exclude<RetKey, 'read'>; part: 'full' | 'summary'; max: number }> = ({ k, part, max }) => (
    <select className="in auto" aria-label={`${k} ${part}`} value={cur![k][part]} onChange={(e) => setDays(k, part, Number(e.target.value))}>
      {[...new Set([...DAY_OPTIONS.filter((d) => d <= max), cur![k][part]])]
        .sort((x, y) => x - y)
        .map((d) => (
          <option key={d} value={d}>
            {d} days
          </option>
        ))}
    </select>
  );
  const purge = ops.data?.items.find((j) => /retention|purge/.test(j.kind));
  const purgeKind = ops.data?.kinds.find((k) => /retention|purge/.test(k.kind));
  const statCell = (k: string) => {
    const s = stats[k];
    return [s?.stored !== undefined ? fmtInt(s.stored) : '—', s?.oldest ? new Date(s.oldest).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—'];
  };

  if (settings.error && !settings.data)
    return (
      <section className="card">
        <ErrorState error={settings.error} onRetry={settings.reload} />
      </section>
    );
  if (!cur)
    return (
      <section className="card">
        <SkLines lines={6} />
      </section>
    );
  const Row: React.FC<{ title: string; sub?: string; full: React.ReactNode; summary: React.ReactNode; ceiling: string; stat: string; locked?: boolean }> = ({
    title,
    sub,
    full,
    summary,
    ceiling,
    stat,
    locked,
  }) => {
    const [stored, oldest] = statCell(stat);
    return (
      <tr className={locked ? 'locked-row' : ''}>
        <td>
          <b>{title}</b>
          {sub && <div className="sm muted">{sub}</div>}
        </td>
        <td>{full}</td>
        <td>{summary}</td>
        <td className="sm">{ceiling}</td>
        <td className="sm">{stored}</td>
        <td className="sm">{oldest}</td>
      </tr>
    );
  };
  const lock = (t: string) => (
    <span className="sm" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
      <Icon.Lock size={12} /> {t}
    </span>
  );

  return (
    <>
      <section className="card" style={{ padding: 0 }}>
        <div className="scroll">
          <table className="tbl mid" style={{ minWidth: 820 }}>
            <thead>
              <tr>
                <th>Record type</th>
                <th>Full detail</th>
                <th>Summary</th>
                <th>Global ceiling</th>
                <th>Stored now</th>
                <th>Oldest record</th>
              </tr>
            </thead>
            <tbody>
              <Row
                title="Administrative events"
                sub="roles, projects, clients, settings, review"
                full={<DaySel k="admin" part="full" max={ceil.admin[0]} />}
                summary={<DaySel k="admin" part="summary" max={ceil.admin[1]} />}
                ceiling={`${ceil.admin[1]} days`}
                stat="admin"
              />
              <Row
                title="Data operations"
                sub="read, write, search, update"
                full={<DaySel k="data" part="full" max={ceil.data[0]} />}
                summary={<DaySel k="data" part="summary" max={ceil.data[1]} />}
                ceiling={`${ceil.data[0]} / ${ceil.data[1]} days`}
                stat="data"
              />
              <Row
                title="Read operation detail"
                sub="which records a read returned"
                full={
                  <select className="in auto" aria-label="Read operation detail" value={cur.read} onChange={(e) => setDraft({ ...cur, read: e.target.value as typeof cur.read })}>
                    <option value="full">full</option>
                    <option value="sample">sample 1/N</option>
                    <option value="summary">summary</option>
                  </select>
                }
                summary={<span className="muted">—</span>}
                ceiling="full"
                stat="read"
              />
              <Row
                title="Denied operations"
                full={<DaySel k="denied" part="full" max={ceil.denied[0]} />}
                summary={<DaySel k="denied" part="summary" max={ceil.denied[1]} />}
                ceiling={`${ceil.denied[1]} days`}
                stat="denied"
              />
              <Row
                title="Conversations"
                sub="agent session transcripts"
                full={<DaySel k="conversations" part="full" max={ceil.conversations[0]} />}
                summary={<span className="muted">—</span>}
                ceiling={`${ceil.conversations[0]} days`}
                stat="conversations"
              />
              <Row title="Privileged access" sub="incident grants and their use" full={lock('7 years')} summary={lock('immutable')} ceiling="platform fixed" stat="privileged" locked />
              <Row title="Hard-delete entries" full={lock('7 years')} summary={<span className="sm">sanitized · no deleted text</span>} ceiling="platform fixed" stat="hard_delete" locked />
            </tbody>
          </table>
        </div>
      </section>
      <div className="row-wrap">
        <section className="card" style={{ flex: '1 1 380px' }}>
          <div className="card-head">
            <h2 data-h="3">Purge schedule</h2>
            <span className={`lbl ${purge?.status === 'failed' ? 'red' : 'grn'}`}>{purge?.status === 'failed' ? 'Failing' : 'Healthy'}</span>
          </div>
          <dl className="detail-kv">
            <dt>Runs</dt>
            <dd>{r?.purge_schedule ?? 'Daily 03:00 UTC'}</dd>
            <dt>Last run</dt>
            <dd>
              {purge
                ? `${hhmm(purge.started_at, false)} · ${purge.duration_ms ? `${Math.round(purge.duration_ms / 1000)}s` : '—'}${typeof purge.detail?.count === 'number' ? ` · ${fmtInt(purge.detail.count as number)} removed` : ''}`
                : purgeKind
                  ? `${purgeKind.ok} runs this week`
                  : 'No run in the last 7 days'}
            </dd>
            <dt>Next run</dt>
            <dd>Tomorrow 03:00</dd>
          </dl>
          <a className="sm" href={buildHash('/quality', { view: 'jobs' })} style={{ display: 'inline-block', marginTop: 12 }}>
            Open job history
          </a>
        </section>
        <section className="card" style={{ flex: '1 1 380px' }}>
          <div className="card-head">
            <h2 data-h="3">Change summary</h2>
            <span className={`lbl ${dirty ? 'ylw' : 'g'}`}>{dirty ? 'unsaved' : 'no changes'}</span>
          </div>
          {dirty ? (
            <ul className="sm" style={{ margin: '10px 0', paddingLeft: 18 }}>
              {changes.map((c) => (
                <li key={c}>{c}</li>
              ))}
              {shortened.length > 0 && <li>Records older than the new limits move to summary or are purged at the next run.</li>}
            </ul>
          ) : (
            <p className="sm muted" style={{ margin: '10px 0' }}>
              Change a limit above; the summary and the reason are saved together.
            </p>
          )}
          <div className="f">
            <label htmlFor="ret-r">Reason</label>
            <input id="ret-r" className="in" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reduce stored detail per privacy review PR-14" disabled={!dirty} />
          </div>
          <p className="sm muted" style={{ marginTop: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
            <Icon.Info size={14} /> Saved as an administrative event; tenant users are not notified.
          </p>
        </section>
      </div>
      <Info>Ceilings come from Global policies (Super Admin). Shortening retention cannot be undone for records already purged.</Info>
    </>
  );
};

export default AdminAudit;
