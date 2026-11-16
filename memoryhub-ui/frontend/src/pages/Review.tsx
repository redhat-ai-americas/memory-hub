import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Icon, ScopeLabel, SkLines, Standby, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { AuditEvent, ReviewItem, ReviewQueue, ReviewSummary } from '@/types';
import { errorMessage, fmtInt, fmtRelative, fmtUtc, scopeMeta, shortId, truncate } from '@/utils/format';
import { actorName, memoryHref } from './common';

type Tab = 'assigned' | 'promotions' | 'contradictions' | 'approvals' | 'quarantine' | 'hard_delete' | 'history';
const QUEUES: Exclude<Tab, 'assigned' | 'history'>[] = ['promotions', 'contradictions', 'approvals', 'quarantine', 'hard_delete'];
const KIND_LABEL: Record<string, string> = {
  approval: 'enterprise approval',
  promotion: 'promotion',
  contradiction: 'contradiction',
  quarantine: 'quarantine follow-up',
  hard_delete: 'hard-delete request',
};
const KIND_PREFIX: Record<string, string> = { approval: 'req', promotion: 'prm', contradiction: 'ctr', quarantine: 'qrn', hard_delete: 'del' };

type Counts = ReviewQueue['counts'];

const ago = (iso: string) => {
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} d`;
};
const meta = (s: { metadata?: Record<string, unknown> | null }) => (s.metadata ?? {}) as Record<string, unknown>;
const str = (v: unknown) => (typeof v === 'string' && v ? v : undefined);
const titleOf = (s: ReviewSummary) => str(meta(s).title) ?? truncate(s.stub || s.content, 70);

/** Scope pill: the project name for project scope, a lock for personal records. */
const ScopePill: React.FC<{ scope: string; name?: string }> = ({ scope, name }) =>
  scope === 'user' ? (
    <ScopeLabel scope="user">
      <Icon.Lock size={11} /> Personal
    </ScopeLabel>
  ) : (
    <ScopeLabel scope={scope}>{name ?? scopeMeta(scope).label}</ScopeLabel>
  );

const Review: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { standby, refreshCounts, me } = useApp();
  const requested = route.params.get('tab') as Tab | null;
  const tab: Tab = requested && ['assigned', ...QUEUES, 'history'].includes(requested) ? requested : 'assigned';
  const selectedId = route.params.get('item');
  const tenant = me?.tenant_id ?? 'this tenant';

  const setParam = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(route.params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    navigate('/review', next, { replace: true });
  };

  // One queue at a time; "Assigned to me" gathers every queue and drops the viewer's own requests.
  const { data, error, loading, reload } = useApi<{ items: ReviewSummary[]; counts: Counts | null; viewer: string; history: AuditEvent[] }>(
    async () => {
      if (tab === 'history') {
        const h = await api.reviewQueue('history');
        return { items: [], counts: h.counts as Counts, viewer: h.viewer, history: h.items as AuditEvent[] };
      }
      if (tab === 'assigned') {
        const base = await api.reviewQueue('approvals');
        const counts = base.counts as Counts;
        const rest = await Promise.all(
          QUEUES.filter((q) => q !== 'approvals' && (q !== 'hard_delete' || counts.hard_delete !== undefined)).map((q) => api.reviewQueue(q).catch(() => null)),
        );
        const all = [base, ...rest].flatMap((r) => (r ? (r.items as ReviewSummary[]) : []));
        const seen = new Set<string>();
        const items = all.filter((i) => {
          if (seen.has(i.id) || i.kind === 'history') return false;
          seen.add(i.id);
          const assignee = str(meta(i).assignee);
          return assignee ? assignee === base.viewer : (i.actor_id ?? i.owner_id) !== base.viewer;
        });
        items.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
        return { items, counts, viewer: base.viewer, history: [] };
      }
      if (tab === 'hard_delete') {
        const probe = await api.reviewQueue('approvals');
        if ((probe.counts as Counts).hard_delete === undefined) return { items: [], counts: probe.counts as Counts, viewer: probe.viewer, history: [] };
      }
      const r = await api.reviewQueue(tab);
      return { items: r.items as ReviewSummary[], counts: r.counts as Counts, viewer: r.viewer, history: [] };
    },
    [tab],
    standby ? 5000 : 30000,
  );

  const items = data?.items ?? [];
  const selected = items.find((i) => i.id === selectedId) ?? items[0];
  const counts = data?.counts;
  const hardDeleteSupported = counts ? counts.hard_delete !== undefined : true;
  const assignedCount = counts ? counts.approvals + counts.promotions + counts.contradictions + counts.quarantine + (counts.hard_delete ?? 0) : null;

  return (
    <>
      <PageHeader
        title="Review queue"
        crumbs={[{ label: 'Review queue' }]}
        description={`Promotions, contradiction reports, enterprise approvals, quarantine follow-ups and hard-delete requests for ${tenant}. Opening an assigned item lets you read that submission until you decide. You can never decide your own request; the author is notified with your reason.`}
        tabs={
          <Tabs
            label="Queue"
            value={tab}
            onChange={(t) => setParam({ tab: t === 'assigned' ? undefined : t, item: undefined })}
            tabs={[
              { value: 'assigned', label: 'Assigned to me', count: data && tab === 'assigned' ? items.length : assignedCount },
              { value: 'promotions', label: 'Promotions', count: counts?.promotions ?? null },
              { value: 'contradictions', label: 'Contradictions', count: counts?.contradictions ?? null },
              { value: 'approvals', label: 'Enterprise approvals', count: counts?.approvals ?? null },
              { value: 'quarantine', label: 'Quarantine follow-ups', count: counts?.quarantine ?? null },
              { value: 'hard_delete', label: 'Hard-delete requests', count: counts?.hard_delete ?? null },
              { value: 'history', label: 'History' },
            ]}
          />
        }
      />
      <div className="body">
        {standby ? (
          <div className="card">
            <Standby compact={false}>
              Enterprise approvals, promotions, contradictions past the threshold, quarantined writes and hard-delete requests will wait here for a decision.
            </Standby>
          </div>
        ) : error && !data ? (
          <div className="card">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : tab === 'history' ? (
          <History items={data?.history ?? []} loading={loading && !data} />
        ) : (
          <div className="row-wrap rq-layout">
            <aside className="rq-list card">
              {loading && !data ? (
                <SkLines lines={6} />
              ) : items.length === 0 ? (
                <Empty compact title={tab === 'assigned' ? 'Nothing assigned to you' : 'Queue is clear'}>
                  {tab === 'hard_delete' && !hardDeleteSupported ? 'This server does not run a two-person hard-delete workflow yet.' : EMPTY_TEXT[tab]}
                </Empty>
              ) : (
                items.map((i) => <ListItem key={i.id} item={i} on={selected?.id === i.id} showKind={tab === 'assigned'} onClick={() => setParam({ item: i.id })} />)
              )}
            </aside>

            <div className="rq-main">
              <section className="card rq-detail">
                {selected ? (
                  <Detail
                    key={selected.id}
                    summary={selected}
                    viewer={data?.viewer ?? ''}
                    onDecided={() => {
                      setParam({ item: undefined });
                      reload();
                      refreshCounts();
                    }}
                  />
                ) : loading && !data ? (
                  <SkLines lines={10} />
                ) : (
                  <Empty compact title="Nothing to review">
                    Pick an item on the left when one arrives.
                  </Empty>
                )}
              </section>
              {tab !== 'quarantine' && counts && counts.quarantine > 0 && <QuarantineCard count={counts.quarantine} />}
              {tab !== 'hard_delete' && counts?.hard_delete ? <HardDeleteCard count={counts.hard_delete} viewer={data?.viewer ?? ''} /> : null}
              <RecentDecisions />
            </div>
          </div>
        )}
      </div>
    </>
  );
};

const EMPTY_TEXT: Record<string, string> = {
  assigned: 'Items you can decide — and that you did not request yourself — collect here.',
  approvals: 'Enterprise-scope memories written by agents or people wait here until an approver signs off.',
  promotions: 'Promotions to broader scopes wait here for review.',
  contradictions: 'Memories whose open contradiction reports reach the revision threshold appear here.',
  quarantine: 'Writes held by a quarantine rule appear here to be restored or deleted.',
  hard_delete: 'Requests to permanently remove a record wait here for a second admin.',
};

const ListItem: React.FC<{ item: ReviewSummary; on: boolean; showKind: boolean; onClick: () => void }> = ({ item: i, on, showKind, onClick }) => {
  const m = meta(i);
  const who = str(m.reporter) ?? i.actor_id ?? i.owner_id;
  const project = str(m.project) ?? (i.scope === 'project' ? str(m.scope_id) : undefined);
  const detail =
    i.kind === 'contradiction'
      ? `${typeof m.memories === 'number' ? m.memories : 2} memories · reported by ${who}`
      : i.kind === 'promotion'
        ? `${i.sources ?? 1} source${i.sources === 1 ? '' : 's'} · proposed by ${who}`
        : i.kind === 'quarantine'
          ? `${str(m.reason) ?? str(m.quarantine_reason) ?? 'held by a curation rule'}`
          : i.kind === 'hard_delete'
            ? `requested by ${who}`
            : `requested by ${who}`;
  return (
    <button type="button" className={`rq-item ${on ? 'on' : ''}`} onClick={onClick}>
      <div className="rq-item-head">
        <b>{i.scope === 'user' && i.kind === 'quarantine' ? shortId(i.id) : titleOf(i)}</b>
        <span className="sm muted">{ago(i.updated_at)}</span>
      </div>
      <div className="sm rq-item-sub">
        {showKind && <span className="tag">{KIND_LABEL[i.kind] ?? i.kind}</span>} <ScopePill scope={i.scope} name={project} /> · {detail}
      </div>
      {i.kind === 'contradiction' && (
        <div className="sm muted" style={{ marginTop: 4 }}>
          Revisions: {i.reports ?? 0}
          {typeof m.threshold === 'number' && (i.reports ?? 0) >= (m.threshold as number) ? ` · over threshold ${m.threshold}` : ''}
        </div>
      )}
    </button>
  );
};

const Detail: React.FC<{ summary: ReviewSummary; viewer: string; onDecided: () => void }> = ({ summary, viewer, onDecided }) => {
  const toast = useToast();
  const { me } = useApp();
  const { data, error, loading, reload } = useApi<ReviewItem>(() => api.reviewItem(summary.id, summary.kind), [summary.id]);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [tried, setTried] = useState(false);

  const decide = async (decision: string, done: string) => {
    setTried(true);
    if (!reason.trim()) return;
    setBusy(decision);
    try {
      await api.reviewDecision(summary.id, decision, reason.trim());
      toast(done);
      onDecided();
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(null);
    }
  };

  if (error && !data) return <ErrorState error={error} onRetry={reload} compact />;
  if (loading || !data) return <SkLines lines={10} />;
  const self = data.requested_by === viewer;
  const kind = summary.kind;
  const hidden = data.scope === 'user' && !me?.access?.break_glass && (kind === 'quarantine' || kind === 'hard_delete');
  const records = kind === 'contradiction' ? 1 + data.contradictions.length : 1 + data.sources.length;
  const rationale = data.branches.find((b) => b.branch_type === 'rationale') ?? data.branches[0];
  const m = meta(summary);

  return (
    <>
      <div className="rq-head">
        <div>
          <div className="sm muted">
            <span className="mono">{shortId(data.id, KIND_PREFIX[kind] ?? 'mem')}</span> · {KIND_LABEL[kind] ?? kind}
          </div>
          <h2 className="rq-title">{hidden ? shortId(data.id) : str(m.title) ?? truncate(data.stub || data.content, 90)}</h2>
        </div>
        {data.can_decide && !hidden && (
          <span className="lbl blue" title="Opening this item lets you read these records until you decide">
            <Icon.Clock size={12} /> Workflow access · {records} record{records === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {kind === 'contradiction' ? (
        <div className="rq-compare">
          <div className="rq-mem">
            <div className="sm muted mono">
              {shortId(data.id)} · v{data.version} · weight {data.weight.toFixed(2)}
            </div>
            <p>{data.content}</p>
            <div className="sm muted">
              {data.owner_id} · {new Date(data.requested_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
            </div>
          </div>
          {data.contradictions.slice(0, 3).map((c) => (
            <div className="rq-mem" key={c.id}>
              <div className="sm muted mono">
                {shortId(c.id, 'rpt')} · confidence {c.confidence.toFixed(2)}
              </div>
              <p>{c.observed_behavior}</p>
              <div className="sm muted">
                {c.reporter} · {new Date(c.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
              </div>
            </div>
          ))}
          {data.contradictions.length === 0 && <div className="rq-mem muted sm">No open reports are attached any more.</div>}
        </div>
      ) : hidden ? (
        <div className="rq-hidden">
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <b className="mono">{shortId(data.id)}</b> · <ScopePill scope="user" /> · <span className="sm">owner {data.owner_id}</span>
            {data.reason && <span className="sm muted">· {data.reason}</span>}
          </div>
          <p className="sm muted" style={{ margin: '8px 0 0' }}>
            Content stays hidden from you. Decide on metadata and the policy finding, or escalate.
          </p>
        </div>
      ) : (
        <>
          <div className="quote" style={{ fontSize: 15 }}>
            {data.content}
          </div>
          <div className="rq-facts">
            <div>
              <div className="sm muted">{kind === 'hard_delete' ? 'Requested by' : 'Requested by'}</div>
              <b>{data.requested_by}</b> · {fmtRelative(data.requested_at).toLowerCase()}
            </div>
            <div>
              <div className="sm muted">Weight</div>
              <b>{data.weight.toFixed(2)}</b> · {data.injection === 'full' ? 'injected in full' : 'injected as a stub'}
            </div>
            <div>
              <div className="sm muted">Reach</div>
              {data.scope === 'enterprise' || data.scope === 'organizational' ? (
                <>
                  <b>All {fmtInt(data.reach_agents)} agents</b> in tenant
                </>
              ) : (
                <>
                  <b>{scopeMeta(data.scope).label}</b> {data.scope_id ?? data.owner_id}
                </>
              )}
            </div>
          </div>
          {rationale && (
            <p className="sm muted" style={{ margin: 0, lineHeight: 1.55 }}>
              <b style={{ color: 'inherit' }}>{rationale.branch_type ?? 'Branch'}:</b> {rationale.content}
            </p>
          )}
          {kind !== 'hard_delete' && (
            <div>
              <Check ok={data.checks.scan_clean} label="Secrets & PII scan" note={data.checks.scan_clean ? 'clean' : data.checks.scan_findings.join(', ')} />
              <Check
                ok={!data.checks.similar}
                warn
                label={
                  data.checks.similar ? (
                    <>
                      Similar memory <a href={memoryHref(data.checks.similar.id)}>“{truncate(data.checks.similar.stub, 50)}”</a>
                    </>
                  ) : (
                    'No similar existing memory'
                  )
                }
                note={data.checks.similar ? `cosine ${data.checks.similar.score.toFixed(2)}` : '< 0.75'}
              />
              <Check ok={data.checks.has_provenance} warn label="Provenance attached" note={data.checks.has_provenance ? `${data.branches.length + data.sources.length} items` : 'none'} last />
            </div>
          )}
        </>
      )}

      {data.history.length > 0 && (
        <div className="sm muted">
          {data.history.map((h, i) => (
            <div key={i}>
              {h.event_type.replace('review.', '').replace('_', ' ')} by {h.actor_id} · {fmtRelative(h.timestamp).toLowerCase()}
              {h.comment ? ` — “${h.comment}”` : ''}
            </div>
          ))}
        </div>
      )}

      {data.can_decide ? (
        <div className="rq-decide">
          <div className="f">
            <label htmlFor="rq-reason">
              Decision reason <span className="err">*</span>
            </label>
            <textarea
              id="rq-reason"
              className={`in ${tried && !reason.trim() ? 'invalid' : ''}`}
              style={{ minHeight: 56 }}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={kind === 'contradiction' ? 'Newer memory matches the release notes; older one superseded.' : 'Why are you deciding this way?'}
            />
            <span className={`sm ${tried && !reason.trim() ? 'err' : 'muted'}`}>
              {tried && !reason.trim() ? 'A reason is required for every decision.' : 'Shown to reporters and owners · stored in the tenant audit.'}
            </span>
          </div>
          <div className="rq-actions">
            {kind === 'approval' || kind === 'promotion' ? (
              <>
                <button
                  type="button"
                  className="btn bp"
                  disabled={!!busy || self}
                  title={self ? 'You can never decide your own request' : undefined}
                  onClick={() => decide('approve', 'Approved and published to agents.')}
                >
                  {kind === 'approval' ? 'Approve & publish' : 'Approve promotion'}
                </button>
                <button type="button" className="btn bs" disabled={!!busy || self} onClick={() => decide('reject', 'Rejected. The proposal never reached agents.')}>
                  Reject
                </button>
                <button type="button" className="link-btn" disabled={!!busy || self} onClick={() => decide('request_changes', 'Changes requested.')}>
                  Request changes
                </button>
              </>
            ) : kind === 'contradiction' ? (
              <>
                <button type="button" className="btn bp" disabled={!!busy} onClick={() => decide('approve', 'Reports accepted and resolved.')}>
                  Accept report · resolve
                </button>
                <a className="btn bs" href={memoryHref(data.id)}>
                  Revise memory
                </a>
                <button type="button" className="btn bs" disabled={!!busy} onClick={() => decide('reject', 'Memory kept; reports resolved.')}>
                  Reject report · memory kept
                </button>
              </>
            ) : kind === 'quarantine' ? (
              <>
                <button type="button" className="btn bs" disabled={!!busy} onClick={() => decide('restore', 'Restored — agents can read it again.')}>
                  Restore
                </button>
                <button type="button" className="link-btn" disabled={!!busy} onClick={() => decide('reject', 'Deleted. The write is kept for forensics.')}>
                  Delete
                </button>
                <a className="link-btn" href={buildHash('/audit', { tab: 'grants' })}>
                  Escalate to incident
                </a>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn bd"
                  disabled={!!busy || self}
                  title={self ? 'The requester can’t approve their own hard delete' : undefined}
                  onClick={() => decide('approve', 'Hard delete approved — every version is removed.')}
                >
                  Approve as second admin
                </button>
                <button type="button" className="link-btn" disabled={!!busy} onClick={() => decide('reject', 'Hard delete declined.')}>
                  Decline
                </button>
                <span className="sm muted">Non-user scope only · requester can’t approve</span>
              </>
            )}
          </div>
          {self && kind !== 'contradiction' && kind !== 'quarantine' && <p className="sm muted" style={{ margin: 0 }}>This is your own request — someone else has to decide it.</p>}
        </div>
      ) : (
        <p className="sm muted" role="status">
          You can view this item, but your role does not allow review decisions.
        </p>
      )}
    </>
  );
};

const Check: React.FC<{ ok: boolean; warn?: boolean; label: React.ReactNode; note: string; last?: boolean }> = ({ ok, warn, label, note, last }) => (
  <div className="chk" style={last ? { borderBottom: 0 } : undefined}>
    <span className={ok ? 'ok' : warn ? 'warn' : 'err'} style={{ fontWeight: 700 }}>
      {ok ? '✓' : '!'}
    </span>
    <span style={{ flex: 1 }}>{label}</span>
    <span className="sm muted">{note}</span>
  </div>
);

const QuarantineCard: React.FC<{ count: number }> = ({ count }) => {
  const { me } = useApp();
  const { data } = useApi(() => api.reviewQueue('quarantine'), []);
  const first = (data?.items?.[0] as ReviewSummary | undefined) ?? null;
  const open = first ? buildHash('/review', { tab: 'quarantine', item: first.id }) : buildHash('/review', { tab: 'quarantine' });
  const hidden = first?.scope === 'user' && !me?.access?.break_glass;
  return (
    <section className="card">
      <div className="card-head">
        <h3>Quarantine follow-up</h3>
        <span className="lbl ylw">{count}</span>
      </div>
      {first ? (
        <>
          <div className="sm" style={{ marginTop: 10, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <b className="mono">{hidden ? shortId(first.id) : truncate(first.stub, 50)}</b> · <ScopePill scope={first.scope} /> ·{' '}
            {str(meta(first).owner_request) ?? str(meta(first).reason) ?? 'held by a curation rule'}
          </div>
          {hidden && <p className="sm muted" style={{ margin: '6px 0 0' }}>Content stays hidden from you. Decide on metadata and the policy finding, or escalate.</p>}
        </>
      ) : (
        <SkLines lines={2} />
      )}
      <div className="rq-actions" style={{ marginTop: 12 }}>
        <a className="btn bs sm-btn" href={open}>
          Restore…
        </a>
        <a className="link-btn" href={open}>
          Keep quarantined
        </a>
        <a className="link-btn" href={buildHash('/audit', { tab: 'grants' })}>
          Escalate to incident
        </a>
      </div>
    </section>
  );
};

const HardDeleteCard: React.FC<{ count: number; viewer: string }> = ({ count, viewer }) => {
  const { data } = useApi(() => api.reviewQueue('hard_delete'), []);
  const first = (data?.items?.[0] as ReviewSummary | undefined) ?? null;
  const open = buildHash('/review', { tab: 'hard_delete', item: first?.id });
  const self = first && (first.actor_id ?? first.owner_id) === viewer;
  return (
    <section className="card">
      <div className="card-head">
        <h3>Hard delete · two people</h3>
        <span className="lbl ylw">{count} pending</span>
      </div>
      {first ? (
        <p className="sm" style={{ margin: '10px 0 0' }}>
          <span className="mono">{shortId(first.id)}</span> · requested by {first.actor_id ?? first.owner_id}
          {str(meta(first).reason) ? ` · “${meta(first).reason}”` : ''}. Irreversible, removes every version.
        </p>
      ) : (
        <SkLines lines={2} />
      )}
      <div className="rq-actions" style={{ marginTop: 12 }}>
        <a className={`btn bd sm-btn ${self ? 'disabled' : ''}`} href={open} aria-disabled={self || undefined}>
          Approve as second admin
        </a>
        <a className="link-btn" href={open}>
          Decline
        </a>
        <span className="sm muted">Non-user scope only · requester can’t approve</span>
      </div>
    </section>
  );
};

const decisionLabel = (t: string) => {
  const k = t.replace('review.', '');
  if (/approve|accept|publish/.test(k)) return { label: 'Approved', cls: 'grn' };
  if (/reject|decline|delete/.test(k)) return { label: 'Rejected', cls: 'red' };
  if (/restore/.test(k)) return { label: 'Restored', cls: 'blue' };
  if (/change/.test(k)) return { label: 'Changes requested', cls: 'ylw' };
  return { label: k.replace(/_/g, ' '), cls: 'g' };
};

const RecentDecisions: React.FC = () => {
  const { data, loading } = useApi(() => api.reviewQueue('history'), []);
  const items = ((data?.items ?? []) as AuditEvent[]).filter((e) => e.event_type.startsWith('review.')).slice(0, 4);
  return (
    <section className="card">
      <div className="card-head">
        <h3>History</h3>
        <a className="sm" href={buildHash('/review', { tab: 'history' })}>
          All decisions
        </a>
      </div>
      {loading && !data ? (
        <SkLines lines={3} />
      ) : items.length === 0 ? (
        <p className="sm muted" style={{ marginTop: 10 }}>
          No decisions yet.
        </p>
      ) : (
        <ul className="rq-hist">
          {items.map((e) => {
            const d = decisionLabel(e.event_type);
            return (
              <li key={e.id}>
                <span className={`lbl ${d.cls}`}>{d.label}</span>
                <span className="sm">
                  {e.scope === 'user' ? shortId(e.memory_id) : truncate(e.memory_stub ?? shortId(e.memory_id), 40)} · {e.actor_id} ·{' '}
                  {new Date(e.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
};

const History: React.FC<{ items: AuditEvent[]; loading: boolean }> = ({ items, loading }) => (
  <section className="card" style={{ padding: 0 }}>
    {loading ? (
      <SkLines lines={6} />
    ) : items.length === 0 ? (
      <Empty title="No decisions yet">Approvals, rejections and change requests made here are listed with their reasons.</Empty>
    ) : (
      <div className="scroll">
        <table className="tbl" style={{ minWidth: 760 }}>
          <thead>
            <tr>
              <th>Timestamp (UTC)</th>
              <th>Decision</th>
              <th>Reviewer</th>
              <th>Record</th>
              <th>Scope</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => {
              const d = decisionLabel(e.event_type);
              return (
                <tr key={e.id}>
                  <td className="mono muted">{fmtUtc(e.timestamp)}</td>
                  <td>
                    <span className={`lbl ${d.cls}`}>{d.label}</span>
                  </td>
                  <td className="sm">{actorName(e)}</td>
                  <td style={{ maxWidth: 320 }}>
                    {e.memory_id ? e.scope === 'user' ? <span className="mono sm">{shortId(e.memory_id)}</span> : <a href={memoryHref(e.memory_id)}>{truncate(e.memory_stub ?? e.memory_id, 60)}</a> : '—'}
                  </td>
                  <td>{e.scope && e.scope !== 'session' ? <ScopePill scope={e.scope} /> : '—'}</td>
                  <td className="sm muted">{(e.metadata?.comment as string) || '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    )}
  </section>
);

export default Review;
