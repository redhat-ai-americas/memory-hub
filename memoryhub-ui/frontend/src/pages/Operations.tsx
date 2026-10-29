import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, useApp } from '@/components/Shell';
import { Empty, ErrorState, Seg, SelectMenu, SkTable, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash } from '@/hooks/useHashRoute';
import type { JobRow, OperationsResponse } from '@/types';
import { errorMessage, fmtInt, fmtRelative, shortId } from '@/utils/format';

const fmtMs = (ms: number | null | undefined) => (ms === null || ms === undefined ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

const STATUS: Record<string, { cls: string; label: string }> = {
  ok: { cls: 'grn', label: 'done' },
  failed: { cls: 'red', label: 'failed' },
  running: { cls: 'blue', label: 'running' },
};

/** What the dashboard did in the background: dreams, rebuilds, checks, reprocesses. */
const Operations: React.FC = () => {
  const toast = useToast();
  const { role } = useApp();
  const [days, setDays] = useState('7');
  const [status, setStatus] = useState('');
  const [kind, setKind] = useState('');
  const [corr, setCorr] = useState<string | null>(null);
  const { data, error, loading, reload } = useApi<OperationsResponse>(
    () => api.operations({ days: Number(days), status: status || undefined, kind: kind || undefined }),
    [days, status, kind],
    15000,
  );
  const items = (data?.items ?? []).filter((j) => !corr || j.correlation_id === corr);
  const retry = async (j: JobRow) => {
    try {
      await api.retryJob(j.id);
      toast(`${j.label} ran again.`);
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      reload();
    }
  };
  return (
    <>
      <PageHeader
        title={role === 'user' ? 'Background jobs' : 'Operations'}
        description={
          role === 'user'
            ? 'Work the dashboard did for you in the background: dreams, knowledge page rebuilds, retrieval check runs and document reprocessing.'
            : 'Every background job in the tenant — dreams, knowledge rebuilds, check runs, document reprocessing and scheduler ticks — with status, duration, attempts and a correlation ID. Metadata only.'
        }
        actions={
          <Seg
            label="Period"
            value={days}
            onChange={setDays}
            options={[
              { value: '1', label: '24 h' },
              { value: '7', label: '7 d' },
              { value: '30', label: '30 d' },
            ]}
          />
        }
      />
      <div className="body">
        {data && data.kinds.length > 0 && (
          <div className="kgrid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
            {data.kinds.map((k) => (
              <button key={k.kind} type="button" className={`card kcard opk ${kind === k.kind ? 'on' : ''}`} onClick={() => setKind(kind === k.kind ? '' : k.kind)}>
                <div className="sm b6">{k.label}</div>
                <div className="statv" style={{ margin: '6px 0 2px' }}>
                  {fmtInt(k.ok + k.failed + k.running)}
                </div>
                <div className="hint">
                  {k.failed ? <span className="err">{k.failed} failed · </span> : null}
                  {k.avg_ms !== undefined ? `avg ${fmtMs(k.avg_ms)} · p95 ${fmtMs(k.p95_ms)}` : ''}
                </div>
              </button>
            ))}
          </div>
        )}
        <section className="card" style={{ padding: 0 }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '14px 20px', flexWrap: 'wrap' }}>
            <SelectMenu
              label="Status"
              prefix="Status: "
              value={status}
              onChange={setStatus}
              options={[
                { value: '', label: 'Any' },
                { value: 'failed', label: 'Failed' },
                { value: 'running', label: 'Running' },
                { value: 'ok', label: 'Done' },
              ]}
            />
            {kind && (
              <span className="chip">
                {data?.kinds.find((k) => k.kind === kind)?.label ?? kind}
                <button type="button" aria-label="Clear kind" onClick={() => setKind('')}>
                  ✕
                </button>
              </span>
            )}
            {corr && (
              <span className="chip">
                Correlation {shortId(corr, 'run')}
                <button type="button" aria-label="Clear correlation" onClick={() => setCorr(null)}>
                  ✕
                </button>
              </span>
            )}
            <span className="sm muted" style={{ marginLeft: 'auto' }}>
              {data?.scope === 'tenant' ? 'All users' : 'Only your jobs'} · refreshes every 15 s
            </span>
          </div>
          {error && !data ? (
            <ErrorState error={error} onRetry={reload} />
          ) : loading && !data ? (
            <SkTable rows={6} cols={6} />
          ) : items.length === 0 ? (
            <Empty compact title="No jobs in this period">Jobs appear when dreams run, knowledge pages rebuild, checks run or documents change.</Empty>
          ) : (
            <div className="scroll">
              <table className="tbl mid">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Status</th>
                    {data?.scope === 'tenant' && <th>For</th>}
                    <th>Trigger</th>
                    <th>Duration</th>
                    <th>Attempts</th>
                    <th>Correlation</th>
                    <th>Started</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {items.map((j) => (
                    <tr key={j.id}>
                      <td>
                        <div className="b6">{j.label}</div>
                        <div className="hint">{detailLine(j)}</div>
                        {j.error && <div className="sm err">{j.error}</div>}
                      </td>
                      <td>
                        <span className={`lbl ${j.stale ? 'ylw' : STATUS[j.status]?.cls ?? 'g'}`}>{j.stale ? 'stuck' : STATUS[j.status]?.label ?? j.status}</span>
                      </td>
                      {data?.scope === 'tenant' && <td className="sm mono">{j.owner}</td>}
                      <td className="sm">{j.trigger}</td>
                      <td className="sm">{fmtMs(j.duration_ms)}</td>
                      <td className="sm">{j.attempts}</td>
                      <td>
                        <button type="button" className="link-btn sm mono" onClick={() => setCorr(j.correlation_id)} title="Show jobs from the same run">
                          {shortId(j.correlation_id, 'run')}
                        </button>
                      </td>
                      <td className="sm muted" style={{ whiteSpace: 'nowrap' }}>
                        {fmtRelative(j.started_at)}
                      </td>
                      <td>
                        {j.retryable && (
                          <button type="button" className="btn bl sm" onClick={() => retry(j)}>
                            Retry
                          </button>
                        )}
                        {role !== 'admin' && link(j)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <p className="hint">
          Not traced here: agents’ own MCP calls (see {role === 'user' ? 'My activity' : 'Audit & forensics'}), LLM calls and webhooks — MemoryHub does not expose them to the dashboard yet.
        </p>
      </div>
    </>
  );
};

const detailLine = (j: JobRow): string => {
  const d = j.detail as Record<string, unknown>;
  const parts: string[] = [];
  if (typeof d.insights === 'number') parts.push(`${d.insights} insights`);
  if (typeof d.pages === 'number') parts.push(`${d.pages} pages rebuilt`);
  if (typeof d.sources === 'number') parts.push(`${d.sources} sources`);
  if (typeof d.checks === 'number') parts.push(`${d.checks} checks`);
  if (typeof d.recall === 'number') parts.push(`recall ${Math.round((d.recall as number) * 100)}%`);
  if (typeof d.created === 'number') parts.push(`${d.created} memories written`);
  if (typeof d.moved === 'number') parts.push(`${d.ok ?? 0} ok · ${d.moved} moved · ${d.changed ?? 0} changed`);
  if (Array.isArray(d.users)) parts.push(`${(d.users as string[]).length} users`);
  if (d.subject_kind) parts.push(d.subject_kind === 'me' ? 'personal page' : `project ${d.subject_id}`);
  return parts.join(' · ');
};

const link = (j: JobRow) => {
  const d = j.detail as Record<string, string>;
  if (j.kind === 'dream') return <a className="btn bl sm" href={buildHash('/hygiene')}>Open</a>;
  if (j.kind === 'eval.run') return <a className="btn bl sm" href={buildHash('/quality', { tab: 'runs' })}>Open</a>;
  if (j.kind.startsWith('document') && d.document_id) return <a className="btn bl sm" href={buildHash(`/knowledge/documents/${d.document_id}`)}>Open</a>;
  if (j.kind === 'knowledge.rebuild') return <a className="btn bl sm" href={buildHash(d.subject_kind === 'project' ? `/knowledge/project/${d.subject_id}` : '/knowledge/me')}>Open</a>;
  return null;
};

export default Operations;
