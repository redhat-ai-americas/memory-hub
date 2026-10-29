import React, { useState } from 'react';
import { api } from '@/api/client';
import { PageHeader } from '@/components/Shell';
import { Empty, ErrorState, Icon, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash } from '@/hooks/useHashRoute';
import type { BreakGlassReport, BreakGlassState } from '@/types';
import { errorMessage, fmtDateTime, fmtInt } from '@/utils/format';

/**
 * #667 tier 3: a super-user opens user memories only for a named incident,
 * for a limited time. Every user memory they open is audited (HIGH severity)
 * and its owner is told. Grants and the monthly report live here.
 */
const Incident: React.FC = () => {
  const toast = useToast();
  const { data, error, loading, reload } = useApi<BreakGlassState>(() => api.breakGlass(), []);
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const report = useApi<BreakGlassReport>(() => api.breakGlassReport(month), [month]);
  const [ref, setRef] = useState('');
  const [why, setWhy] = useState('');
  const [hours, setHours] = useState<number | ''>('');
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);

  const refOk = (() => {
    try {
      return !!data && new RegExp(data.policy.pattern).test(ref.trim());
    } catch {
      return ref.trim().length >= 3;
    }
  })();
  const canStart = !!data?.policy.enabled && refOk && why.trim().length >= 20 && ack && !busy;

  const reloadApp = () => window.location.reload();
  const start = async () => {
    setBusy(true);
    try {
      await api.startBreakGlass({ incident_ref: ref.trim(), justification: why.trim(), hours: hours || undefined });
      toast(`Incident access ${ref.trim()} started.`);
      reloadApp();
    } catch (e) {
      toast(errorMessage(e), 'err');
      setBusy(false);
    }
  };
  const end = async () => {
    setBusy(true);
    try {
      await api.endBreakGlass();
      toast('Incident access ended. User memories are hidden again.');
      reloadApp();
    } catch (e) {
      toast(errorMessage(e), 'err');
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Incident access"
        description="Open user memories for one incident — a data spill, a classified leak, a legal request. Access is time-limited, needs an incident reference, and every memory you open is logged with HIGH severity and reported to its owner."
      />
      <div className="body">
        {error && !data ? (
          <div className="card">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : loading && !data ? (
          <div className="card">
            <SkLines lines={8} />
          </div>
        ) : (
          data && (
            <div className="row-wrap">
              <div className="col-main">
                {data.active ? (
                  <section className="card" aria-labelledby="ia-h">
                    <div className="alert err-a" style={{ marginBottom: 14 }}>
                      <Icon.Warn size={18} />
                      <span>
                        <b id="ia-h">Incident access {data.active.incident_ref} is on</b>
                        <span className="sm" style={{ display: 'block' }}>
                          Until {fmtDateTime(data.active.expires_at)}. You can open and moderate user memories in{' '}
                          <a href={buildHash('/memories', { scope: 'user' })}>Content moderation</a>. Every one you open is logged and its owner is told.
                        </span>
                      </span>
                    </div>
                    <dl className="dl">
                      <dt>Reference</dt>
                      <dd className="mono">{data.active.incident_ref}</dd>
                      <dt>Justification</dt>
                      <dd>{data.active.justification}</dd>
                      <dt>Started</dt>
                      <dd>{fmtDateTime(data.active.created_at)}</dd>
                    </dl>
                    <button type="button" className="btn bd" style={{ marginTop: 16 }} disabled={busy} onClick={end}>
                      End incident access now
                    </button>
                  </section>
                ) : (
                  <section className="card" aria-labelledby="ib-h">
                    <h3 id="ib-h">Start incident access</h3>
                    {!data.policy.enabled ? (
                      <p className="sm muted">Incident access is switched off for this tenant. A platform admin can turn it on in Settings → Privacy.</p>
                    ) : (
                      <>
                        <p className="sm muted" style={{ margin: '6px 0 14px' }}>
                          Without a grant you work as a platform admin: user memories stay metadata only. A grant lasts at most {data.policy.hours} hours.
                        </p>
                        <div className="fg" style={{ marginTop: 0 }}>
                          <div className="f">
                            <label htmlFor="ir">Incident reference</label>
                            <input id="ir" className="in mono" placeholder="INC-1234" value={ref} onChange={(e) => setRef(e.target.value)} aria-invalid={!!ref && !refOk} />
                            <span className="hint">{ref && !refOk ? 'Use the reference from your incident tracker, e.g. INC-1234.' : 'From your incident tracker.'}</span>
                          </div>
                          <div className="f">
                            <label htmlFor="ih">Hours</label>
                            <input
                              id="ih"
                              className="in"
                              type="number"
                              min={1}
                              max={data.policy.hours}
                              placeholder={String(data.policy.hours)}
                              value={hours}
                              onChange={(e) => setHours(e.target.value ? Math.min(Number(e.target.value), data.policy.hours) : '')}
                            />
                          </div>
                        </div>
                        <div className="f">
                          <label htmlFor="ij">Justification</label>
                          <textarea id="ij" className="in" rows={3} value={why} onChange={(e) => setWhy(e.target.value)} placeholder="What happened and why you need to open personal memories" />
                          <span className="hint">At least 20 characters. Stored with every access and shown in the monthly report.</span>
                        </div>
                        <label className="sm" style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginTop: 12 }}>
                          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                          <span>
                            I understand that opening personal memories is privacy-invasive, is logged with HIGH severity
                            {data.policy.notify_owner ? ', and that each owner is told' : ''}.
                          </span>
                        </label>
                        <button type="button" className="btn bd" style={{ marginTop: 16 }} disabled={!canStart} onClick={start}>
                          {busy ? 'Starting…' : 'Start incident access'}
                        </button>
                      </>
                    )}
                  </section>
                )}

                <section className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                    <h3>Monthly report</h3>
                    <input className="in auto" type="month" aria-label="Month" value={month} onChange={(e) => setMonth(e.target.value)} />
                  </div>
                  {report.error ? (
                    <ErrorState compact error={report.error} onRetry={report.reload} />
                  ) : !report.data ? (
                    <SkLines lines={3} />
                  ) : report.data.accesses.length === 0 ? (
                    <Empty compact title="No access to user memories this month">
                      {report.data.totals.grants ? `${report.data.totals.grants} grant(s) started, no user memory opened.` : 'No incident grants either.'}
                    </Empty>
                  ) : (
                    <>
                      <p className="sm" style={{ margin: '8px 0 12px' }}>
                        {fmtInt(report.data.totals.grants)} grants · {fmtInt(report.data.totals.reads)} user memories opened · {fmtInt(report.data.totals.owners)} owners affected
                      </p>
                      <div className="tbl-scroll">
                        <table className="hosts">
                          <thead>
                            <tr>
                              <th>Super-user</th>
                              <th>Incident</th>
                              <th>Owner</th>
                              <th>Opened</th>
                              <th>First – last</th>
                            </tr>
                          </thead>
                          <tbody>
                            {report.data.accesses.map((a) => (
                              <tr key={`${a.actor}-${a.incident_ref}-${a.owner}`}>
                                <td className="mono">{a.actor}</td>
                                <td className="mono">{a.incident_ref ?? '—'}</td>
                                <td className="mono">{a.owner}</td>
                                <td>{fmtInt(a.reads)}</td>
                                <td className="sm">
                                  {fmtDateTime(a.first)} – {fmtDateTime(a.last)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  )}
                </section>
              </div>

              <aside className="col-side">
                <section className="card">
                  <h3>Grants</h3>
                  {data.grants.length === 0 ? (
                    <p className="sm muted">No incident grants yet.</p>
                  ) : (
                    <ul className="vlist" style={{ marginTop: 10 }}>
                      {data.grants.map((g) => (
                        <li key={g.id} className="sm" style={{ padding: '6px 0', borderBottom: '1px solid var(--mh-line)' }}>
                          <b className="mono">{g.incident_ref}</b> · {g.username}
                          {g.active && <span className="lbl red" style={{ marginLeft: 6 }}>Active</span>}
                          <span className="hint" style={{ display: 'block' }}>
                            {fmtDateTime(g.created_at)} · {fmtInt(g.reads ?? 0)} opened · {fmtInt(g.owners ?? 0)} owners
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
                <section className="card">
                  <h3>Rules</h3>
                  <ul className="sm" style={{ margin: '8px 0 0', paddingLeft: 18, listStyle: 'disc', display: 'grid', gap: 6 }}>
                    <li>Super-users are set by the deployment, never in the dashboard.</li>
                    <li>One grant at a time, {data.policy.hours} hours at most.</li>
                    <li>Every user memory opened is audited with the incident and justification.</li>
                    <li>{data.policy.notify_owner ? 'Owners see each access in their notifications and in Who read my memories.' : 'Owner notices are off for this tenant.'}</li>
                  </ul>
                </section>
              </aside>
            </div>
          )
        )}
      </div>
    </>
  );
};

export default Incident;
