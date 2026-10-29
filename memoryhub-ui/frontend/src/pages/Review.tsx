import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, ScopeLabel, SkLines, Standby, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { AuditEvent, ReviewItem, ReviewQueue, ReviewSummary } from '@/types';
import { errorMessage, fmtInt, fmtRelative, fmtUtc, scopeMeta, shortId, truncate } from '@/utils/format';
import { actorName, memoryHref } from './common';

type Tab = 'approvals' | 'promotions' | 'contradictions' | 'quarantine' | 'history';

const itemLabel = (s: ReviewSummary, threshold?: number) => {
  if (s.kind === 'approval') return <ScopeLabel scope="enterprise" />;
  if (s.kind === 'promotion')
    return (
      <>
        <ScopeLabel scope={s.scope}>Promotion → {s.scope === 'organizational' ? 'org' : s.scope}</ScopeLabel>
        {s.sources ? <span className="lbl g">{s.sources} source{s.sources === 1 ? '' : 's'}</span> : null}
      </>
    );
  if (s.kind === 'contradiction')
    return (
      <span className="lbl s-role">
        Contradiction {s.reports}/{threshold ?? s.reports}
      </span>
    );
  return <span className="lbl ylw">Quarantined</span>;
};

const itemSub = (s: ReviewSummary) => {
  const who = s.actor_id || s.owner_id;
  if (s.kind === 'promotion') return `${who} · ${(s.metadata.reason as string) || 'proposed promotion'}`;
  if (s.kind === 'contradiction') return `${who} · revision prompt due`;
  if (s.kind === 'quarantine') return `${who} · ${(s.metadata.reason as string) || (s.metadata.quarantine_reason as string) || 'held by a curation rule'}`;
  return `by ${who} · ${s.metadata.promoted_from ? 'promotion' : 'policy proposal'}`;
};

const Review: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { standby, refreshCounts } = useApp();
  const tab = (route.params.get('tab') as Tab) || 'approvals';
  const selectedId = route.params.get('item');
  const [mineOnly, setMineOnly] = useState(false);
  const { data, error, loading, reload } = useApi<ReviewQueue>(() => api.reviewQueue(tab), [tab], standby ? 5000 : 30000);

  const setParam = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(route.params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    navigate('/review', next, { replace: true });
  };

  const items = ((data?.items ?? []) as ReviewSummary[]).filter((i) => !mineOnly || (i.actor_id ?? i.owner_id) !== data?.viewer);
  const selected = items.find((i) => i.id === selectedId) ?? data?.also_waiting.find((i) => i.id === selectedId) ?? items[0];
  const counts = data?.counts;

  return (
    <>
      <PageHeader
        title="Review queue"
        description="Everything waiting on a human: enterprise approvals, curator promotions, contradictions past threshold and quarantined writes."
        actions={
          <button type="button" className={`btn ${mineOnly ? 'bs' : 'bg'}`} aria-pressed={mineOnly} onClick={() => setMineOnly((m) => !m)}>
            {mineOnly ? 'Assigned to me ✓' : 'Assigned to me'}
          </button>
        }
        tabs={
          <Tabs
            label="Queue"
            value={tab}
            onChange={(t) => setParam({ tab: t === 'approvals' ? undefined : t, item: undefined })}
            tabs={[
              { value: 'approvals', label: 'Enterprise approvals', count: counts?.approvals ?? null },
              { value: 'promotions', label: 'Promotions', count: counts?.promotions ?? null },
              { value: 'contradictions', label: 'Contradictions', count: counts?.contradictions ?? null },
              { value: 'quarantine', label: 'Quarantine', count: counts?.quarantine ?? null },
              { value: 'history', label: 'History' },
            ]}
          />
        }
      />
      <div className="body">
        {standby ? (
          <div className="card">
            <Standby compact={false}>
              Enterprise approvals, curator promotions, contradictions past the threshold and quarantined writes will wait here for a decision.
            </Standby>
          </div>
        ) : error && !data ? (
          <div className="card">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : tab === 'history' ? (
          <History items={(data?.items ?? []) as AuditEvent[]} loading={loading && !data} />
        ) : (
          <div className="row-wrap">
            <div style={{ flex: '1 1 340px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
              {loading && !data ? (
                [0, 1, 2].map((k) => (
                  <div className="item" key={k}>
                    <SkLines lines={3} />
                  </div>
                ))
              ) : items.length === 0 ? (
                <div className="card">
                  <Empty compact title={mineOnly ? 'Nothing assigned to you' : 'Queue is clear'}>
                    {EMPTY_TEXT[tab]}
                  </Empty>
                </div>
              ) : (
                items.map((i) => (
                  <button key={i.id} type="button" className={`item ${selected?.id === i.id ? 'on' : ''}`} onClick={() => setParam({ item: i.id })}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
                      {itemLabel(i)}
                      <span className="sm muted">{i.kind === 'approval' ? `requested ${fmtRelative(i.created_at).toLowerCase()}` : fmtRelative(i.updated_at)}</span>
                    </div>
                    <div style={{ fontWeight: 600, lineHeight: 1.4 }}>{truncate(i.content, 160)}</div>
                    <div className="sm muted" style={{ marginTop: 6 }}>
                      {itemSub(i)}
                    </div>
                  </button>
                ))
              )}
              {data && data.also_waiting.length > 0 && (
                <>
                  <div className="sm muted" style={{ padding: '10px 4px 0' }}>
                    Also waiting
                  </div>
                  {data.also_waiting.map((i) => (
                    <a
                      key={i.id}
                      className="item"
                      href={buildHash('/review', { tab: i.kind === 'promotion' ? 'promotions' : 'contradictions', item: i.id })}
                    >
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>{itemLabel(i)}</div>
                      <div style={{ fontWeight: 600, lineHeight: 1.4 }}>{truncate(i.content, 120)}</div>
                      <div className="sm muted" style={{ marginTop: 6 }}>
                        {itemSub(i)}
                      </div>
                    </a>
                  ))}
                </>
              )}
            </div>

            <section className="card" style={{ flex: '999 1 560px', display: 'flex', flexDirection: 'column', gap: 18 }}>
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
          </div>
        )}
      </div>
    </>
  );
};

const EMPTY_TEXT: Record<string, string> = {
  approvals: 'Enterprise-scope memories written by agents or people wait here until an approver signs off.',
  promotions: 'Curator promotions to broader scopes wait here for review.',
  contradictions: 'Memories whose open contradiction reports reach the revision threshold appear here.',
  quarantine: 'Writes held by a quarantine rule appear here to be restored or deleted.',
};

const Detail: React.FC<{ summary: ReviewSummary; viewer: string; onDecided: () => void }> = ({ summary, viewer, onDecided }) => {
  const toast = useToast();
  const { data, error, loading, reload } = useApi<ReviewItem>(() => api.reviewItem(summary.id, summary.kind), [summary.id]);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState<string | null>(null);

  const decide = async (decision: string, done: string) => {
    setBusy(decision);
    try {
      await api.reviewDecision(summary.id, decision, comment.trim() || undefined);
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
  const rationale = data.branches.find((b) => b.branch_type === 'rationale') ?? data.branches[0];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {data.kind === 'approval' && <ScopeLabel scope="enterprise">Enterprise · new memory</ScopeLabel>}
          {data.kind === 'promotion' && <ScopeLabel scope={data.scope}>Promotion → {scopeMeta(data.scope).label}</ScopeLabel>}
          {data.kind === 'contradiction' && <span className="lbl s-role">Contradiction · {data.contradictions.length} open reports</span>}
          {data.kind === 'quarantine' && <span className="lbl ylw">Quarantined write</span>}
          <a className="mono muted" href={memoryHref(data.id)}>
            {shortId(data.id, data.kind === 'approval' ? 'req' : 'mem')}
          </a>
        </div>
        {(data.kind === 'approval' || data.kind === 'promotion') && (
          <span className="sm muted">
            Needs {data.approvers_required} approver{data.approvers_required === 1 ? '' : 's'}: {data.requested_by} (requester, excluded) · <b>{viewer}</b>
          </span>
        )}
      </div>
      <div className="quote">{data.content}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, fontSize: 14 }}>
        <div>
          <div className="sm muted">{data.kind === 'contradiction' ? 'Owner' : 'Requested by'}</div>
          <b>{data.kind === 'contradiction' ? data.owner_id : data.requested_by}</b> · {fmtRelative(data.requested_at).toLowerCase()}
        </div>
        <div>
          <div className="sm muted">Weight</div>
          <b>{data.weight.toFixed(2)}</b> · {data.injection === 'full' ? 'always injected in full' : 'injected as a stub'}
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

      {data.kind === 'contradiction' ? (
        <div>
          <div className="sm" style={{ fontWeight: 600, marginBottom: 6 }}>
            Reports ({data.contradictions.length} of threshold {data.contradiction_threshold})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {data.contradictions.map((c) => (
              <div className="br" key={c.id}>
                “{c.observed_behavior}”
                <div className="sm muted" style={{ marginTop: 4 }}>
                  {c.reporter} · confidence {c.confidence.toFixed(1)} · {fmtRelative(c.created_at)}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : rationale ? (
        <div>
          <div className="sm" style={{ fontWeight: 600, marginBottom: 6 }}>
            {rationale.branch_type ? `${rationale.branch_type[0].toUpperCase()}${rationale.branch_type.slice(1)} branch` : 'Branch'}
          </div>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55 }} className="muted">
            {rationale.content}
          </p>
        </div>
      ) : null}

      {data.sources.length > 0 && (
        <div>
          <div className="sm" style={{ fontWeight: 600, marginBottom: 6 }}>
            Sources
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 14 }}>
            {data.sources.map((s) => (
              <div key={s.id} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <ScopeLabel scope={s.scope} />
                <a href={memoryHref(s.id)}>{truncate(s.stub, 80)}</a>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.kind !== 'contradiction' && (
        <div>
          <div className="sm" style={{ fontWeight: 600, marginBottom: 4 }}>
            Policy checks
          </div>
          <div className="chk">
            <span className={data.checks.scan_clean ? 'ok' : 'err'} style={{ fontWeight: 700 }}>
              {data.checks.scan_clean ? '✓' : '!'}
            </span>
            <span style={{ flex: 1 }}>Secrets &amp; PII scan</span>
            <span className="sm muted">{data.checks.scan_clean ? 'clean' : data.checks.scan_findings.join(', ')}</span>
          </div>
          {data.scope === 'enterprise' && (
            <div className="chk">
              <span className="ok" style={{ fontWeight: 700 }}>
                ✓
              </span>
              <span style={{ flex: 1 }}>Enterprise memories this month</span>
              <span className="sm muted">{data.checks.enterprise_this_month} written</span>
            </div>
          )}
          <div className="chk">
            <span className={data.checks.similar ? 'warn' : 'ok'} style={{ fontWeight: 700 }}>
              {data.checks.similar ? '!' : '✓'}
            </span>
            <span style={{ flex: 1 }}>
              {data.checks.similar ? (
                <>
                  Similar existing memory <a href={memoryHref(data.checks.similar.id)}>“{truncate(data.checks.similar.stub, 60)}”</a>
                </>
              ) : (
                'No similar existing memory'
              )}
            </span>
            <span className="sm muted">{data.checks.similar ? `cosine ${data.checks.similar.score.toFixed(2)}` : '< 0.75'}</span>
          </div>
          <div className="chk" style={{ borderBottom: 0 }}>
            <span className={data.checks.has_provenance ? 'ok' : 'warn'} style={{ fontWeight: 700 }}>
              {data.checks.has_provenance ? '✓' : '!'}
            </span>
            <span style={{ flex: 1 }}>Provenance attached</span>
            <span className="sm muted">
              {data.checks.has_provenance
                ? [...new Set([...data.branches.map((b) => b.branch_type ?? 'branch'), ...(data.sources.length ? ['sources'] : [])])].join(' · ')
                : 'none'}
            </span>
          </div>
        </div>
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

      <div>
        <label htmlFor="cm" className="sm" style={{ fontWeight: 600, display: 'block', marginBottom: 6 }}>
          Decision comment · recorded in the audit trail
        </label>
        <textarea id="cm" className="in" style={{ minHeight: 70 }} placeholder="Why are you approving or rejecting?" value={comment} onChange={(e) => setComment(e.target.value)} />
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {data.kind === 'approval' || data.kind === 'promotion' ? (
          <>
            <button
              type="button"
              className="btn bp"
              disabled={!!busy || (self && data.scope === 'enterprise')}
              title={self && data.scope === 'enterprise' ? 'Requesters can never approve their own proposal' : undefined}
              onClick={() => decide('approve', 'Approved and published to agents.')}
            >
              {data.kind === 'approval' ? 'Approve & publish' : 'Approve promotion'}
            </button>
            <button type="button" className="btn bs" disabled={!!busy || !comment.trim()} title={!comment.trim() ? 'Add a comment that explains what to change' : undefined} onClick={() => decide('request_changes', 'Changes requested.')}>
              Request changes
            </button>
            <button type="button" className="btn bd" disabled={!!busy} onClick={() => decide('reject', 'Rejected. The proposal never reached agents.')}>
              Reject
            </button>
            <span className="sm muted" style={{ marginLeft: 'auto', alignSelf: 'center' }}>
              Approval creates an <span className="mono">approval</span> branch signed by you.
            </span>
          </>
        ) : data.kind === 'contradiction' ? (
          <>
            <a className="btn bp" href={memoryHref(data.id)}>
              Revise memory
            </a>
            <button type="button" className="btn bs" disabled={!!busy} onClick={() => decide('approve', 'Reports accepted and resolved.')}>
              Accept reports
            </button>
            <button type="button" className="btn bg" disabled={!!busy} onClick={() => decide('reject', 'Memory kept; reports resolved.')}>
              Keep memory as is
            </button>
            <span className="sm muted" style={{ marginLeft: 'auto', alignSelf: 'center' }}>
              Resolving closes every open report on this memory.
            </span>
          </>
        ) : (
          <>
            <button type="button" className="btn bp" disabled={!!busy} onClick={() => decide('restore', 'Restored — agents can read it again.')}>
              Restore
            </button>
            <button type="button" className="btn bd" disabled={!!busy} onClick={() => decide('reject', 'Deleted. The write is kept for forensics.')}>
              Delete
            </button>
            <span className="sm muted" style={{ marginLeft: 'auto', alignSelf: 'center' }}>
              Delete is a soft delete of the whole version chain · audited
            </span>
          </>
        )}
      </div>
    </>
  );
};

const History: React.FC<{ items: AuditEvent[]; loading: boolean }> = ({ items, loading }) => (
  <section className="card" style={{ padding: 0 }}>
    {loading ? (
      <SkLines lines={6} />
    ) : items.length === 0 ? (
      <Empty title="No decisions yet">Approvals, rejections and change requests made here are listed with their comments.</Empty>
    ) : (
      <div className="scroll">
        <table className="tbl" style={{ minWidth: 760 }}>
          <thead>
            <tr>
              <th>Timestamp (UTC)</th>
              <th>Decision</th>
              <th>Reviewer</th>
              <th>Memory</th>
              <th>Scope</th>
              <th>Comment</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.id}>
                <td className="mono muted">{fmtUtc(e.timestamp)}</td>
                <td className="mono">{e.event_type.replace('review.', '')}</td>
                <td className="sm">{actorName(e)}</td>
                <td style={{ maxWidth: 320 }}>{e.memory_id ? <a href={memoryHref(e.memory_id)}>{truncate(e.memory_stub ?? e.memory_id, 60)}</a> : '—'}</td>
                <td>{e.scope && e.scope !== 'session' ? <ScopeLabel scope={e.scope} /> : '—'}</td>
                <td className="sm muted">{(e.metadata.comment as string) || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </section>
);

export default Review;
