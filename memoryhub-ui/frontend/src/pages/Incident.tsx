import React, { useState } from 'react';
import { api } from '@/api/client';
import { platform, type GrantRequest } from '@/api/platform';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Icon, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { AuditEvent, BreakGlassGrant, BreakGlassReport, BreakGlassState, MemoryContext } from '@/types';
import { errorMessage, fmtInt, shortId } from '@/utils/format';

/*
 * #667: the only way to open personal memory content. A Super Admin asks for an addressed,
 * time-bound grant for one incident; every read is audited and shown to the owner.
 */

const grantId = (id: string) => (/^grt_/.test(id) ? id : shortId(id, 'grt'));
const tShort = (iso: string | null | undefined, sec = false) =>
  iso ? new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', ...(sec ? { second: '2-digit' } : {}) }) : '—';
const dShort = (iso: string) => new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
const grantType = (g: BreakGlassGrant) => (/remediate|delete|restore|quarantine/i.test(g.justification) ? 'remediate' : 'inspect');
const TypeLabel: React.FC<{ t: 'inspect' | 'remediate' }> = ({ t }) => <span className={`lbl ${t}`}>{t}</span>;
const Sim: React.FC = () => <span className="sim">Not enforced by this server yet</span>;

const useUseLog = (grant: BreakGlassGrant | null) =>
  useApi<AuditEvent[]>(async () => {
    if (!grant) return [];
    const hours = Math.max(1, Math.ceil((Date.now() - Date.parse(grant.created_at)) / 3600000) + 1);
    const res = await api.audit({ hours, per_page: 200 });
    return res.items
      .filter((e) => {
        const m = (e.metadata ?? {}) as Record<string, unknown>;
        return m.grant_id === grant.id || m.incident_ref === grant.incident_ref || (/incident|break/.test(e.event_type) && e.actor_id === grant.username);
      })
      .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));
  }, [grant?.id]);

const Incident: React.FC<{ route: HashRoute }> = ({ route }) => {
  const { me } = useApp();
  const tab = route.params.get('tab') || 'grants';
  const { data, error, loading, reload } = useApi<BreakGlassState>(() => api.breakGlass(), []);
  const requests = useApi(() => platform.grantRequests(), []);
  const month = new Date().toISOString().slice(0, 7);
  const report = useApi<BreakGlassReport>(() => api.breakGlassReport(month), [month]);
  const all = data ? [...(data.active && !data.grants.some((g) => g.id === data.active!.id) ? [data.active] : []), ...data.grants] : [];
  const sel = all.find((g) => g.id === route.params.get('grant')) ?? all.find((g) => g.active) ?? all[0] ?? null;
  const history = all.filter((g) => !g.active);
  const toApprove = requests.data?.to_approve ?? [];
  const mine = requests.data?.mine ?? [];
  const setTab = (t: string) => navigate('/incident', t === 'grants' ? undefined : { tab: t }, { replace: true });

  return (
    <>
      <PageHeader
        title="Incident access"
        crumbs={[{ label: 'Incident access' }]}
        description="The only way to open personal memory content. Grants live on the server, need a second approver and MFA, expire on their own, and every read is audited and shown to the owner."
        actions={
          <a className="btn bp" href={buildHash('/incident-request')}>
            Request incident access…
          </a>
        }
        tabs={
          <Tabs
            label="Incident access"
            value={tab}
            onChange={setTab}
            tabs={[
              { value: 'grants', label: 'Grants' },
              { value: 'approve', label: 'Requests to approve', count: requests.data ? toApprove.length : null },
              { value: 'mine', label: 'My requests', count: requests.data ? mine.length : null },
              { value: 'history', label: 'History', count: data ? history.length : null },
              { value: 'report', label: 'Monthly report' },
              { value: 'rules', label: 'Rules' },
            ]}
          />
        }
      />
      <div className="body">
        {error && !data ? (
          <section className="card">
            <ErrorState error={error} onRetry={reload} />
          </section>
        ) : loading && !data ? (
          <section className="card">
            <SkLines lines={8} />
          </section>
        ) : (
          <div className="row-wrap">
            <div className="col-main" style={{ minWidth: 0 }}>
              {(tab === 'grants' || tab === 'history') && (
                <GrantsTable
                  grants={tab === 'history' ? history : all}
                  selected={sel?.id ?? null}
                  onSelect={(id) => navigate('/incident', { ...(tab === 'grants' ? {} : { tab }), grant: id }, { replace: true })}
                />
              )}
              {(tab === 'grants' || tab === 'approve') && (
                <ApproveCards
                  items={toApprove}
                  me={me?.username ?? ''}
                  single={requests.data?.source === 'single-tenant'}
                  onDone={() => {
                    requests.reload();
                    reload();
                  }}
                  showEmpty={tab === 'approve'}
                />
              )}
              {tab === 'mine' && <MineTable items={mine} single={requests.data?.source === 'single-tenant'} />}
              {(tab === 'grants' || tab === 'history') && sel && <UseLog grant={sel} onRevoked={reload} />}
              {tab === 'report' && <ReportCard report={report} wide />}
              {tab === 'rules' && <RulesCard hours={data?.policy.hours ?? 4} notify={data?.policy.notify_owner ?? true} />}
            </div>
            <aside className="col-side" style={{ flex: '1 1 300px', maxWidth: 400 }}>
              {tab !== 'rules' && <RulesCard hours={data?.policy.hours ?? 4} notify={data?.policy.notify_owner ?? true} />}
              {tab !== 'report' && <ReportCard report={report} />}
              <div className="alert" role="note">
                <Icon.Info size={16} />
                <span className="sm">Platform Admins see grants on their tenant (read-only) under Audit &amp; forensics.</span>
              </div>
            </aside>
          </div>
        )}
      </div>
    </>
  );
};

const GrantsTable: React.FC<{ grants: BreakGlassGrant[]; selected: string | null; onSelect: (id: string) => void }> = ({ grants, selected, onSelect }) => {
  const { tenant } = useApp();
  return (
    <section className="card">
      <div className="card-head">
        <h3>Grants</h3>
        <span className="sm muted">State read from /api/break-glass on every load</span>
      </div>
      {grants.length === 0 ? (
        <Empty compact title="No grants">Request incident access when an incident needs personal content.</Empty>
      ) : (
        <div className="scroll">
          <table className="tbl mid" style={{ minWidth: 640, marginTop: 8 }}>
            <thead>
              <tr>
                <th>Grant</th>
                <th>Type</th>
                <th>Incident</th>
                <th>Tenant · target</th>
                <th>Requested / approved</th>
                <th>Window</th>
                <th>Reads</th>
              </tr>
            </thead>
            <tbody>
              {grants.map((g) => (
                <tr key={g.id} className={`clickable ${selected === g.id ? 'is-sel' : ''}`} onClick={() => onSelect(g.id)} onDoubleClick={() => navigate(`/grant/${g.id}`)}>
                  <td className="mono sm">
                    <a href={buildHash(`/grant/${g.id}`)} onClick={(e) => e.stopPropagation()}>
                      {grantId(g.id)}
                    </a>
                  </td>
                  <td>
                    <TypeLabel t={grantType(g)} />
                  </td>
                  <td>{g.incident_ref}</td>
                  <td className="sm">
                    {tenant}
                    {g.owners ? ` · ${g.owners} owner${g.owners === 1 ? '' : 's'}` : ''}
                  </td>
                  <td className="sm">{g.username} / —</td>
                  <td className="sm">
                    {g.active ? `${tShort(g.created_at)} → ${tShort(g.expires_at)}` : `${dShort(g.created_at)} · ${Math.round((Date.parse(g.ended_at ?? g.expires_at) - Date.parse(g.created_at)) / 3600000) || '<1'} h`}
                  </td>
                  <td>{g.reads ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};

const ApproveCards: React.FC<{ items: GrantRequest[]; me: string; single: boolean; showEmpty: boolean; onDone: () => void }> = ({ items, me, single, showEmpty, onDone }) => {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  if (items.length === 0)
    return showEmpty ? (
      <section className="card">
        <Empty compact title="Nothing to approve">
          {single ? 'This server starts a grant without a second approver; the platform service adds the independent approval step.' : 'Requests from other Super Admins wait here.'}
        </Empty>
      </section>
    ) : null;
  const decide = async (r: GrantRequest, d: 'approve' | 'decline') => {
    setBusy(r.id);
    try {
      await platform.decideGrant(r.id, d);
      toast(d === 'approve' ? `${r.id} approved. The requester activates it with step-up MFA.` : `${r.id} declined.`);
      onDone();
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(null);
    }
  };
  return (
    <>
      {items.map((r) => (
        <section className="card" key={r.id}>
          <div className="card-head">
            <h3>Waiting for your approval</h3>
            <TypeLabel t={r.type} />
          </div>
          <dl className="detail-kv">
            <dt>Request</dt>
            <dd className="mono">
              {r.id} · {r.incident_ref}
            </dd>
            <dt>Requested by</dt>
            <dd>
              {r.requested_by} · {tShort(r.requested_at)}
            </dd>
            <dt>Action</dt>
            <dd>{r.action ?? `${r.operations.join(', ')} · ${r.targets.length} record${r.targets.length === 1 ? '' : 's'} of ${r.owner}`}</dd>
            <dt>Reason</dt>
            <dd>{r.reason}</dd>
            <dt>Window</dt>
            <dd>{r.window_hours < 1 ? `${Math.round(r.window_hours * 60)} min` : `${r.window_hours} h`} after activation</dd>
          </dl>
          <div className="rq-actions" style={{ marginTop: 14 }}>
            <button type="button" className="btn bd-solid btn" disabled={busy === r.id || r.requested_by === me} onClick={() => decide(r, 'approve')}>
              Approve · step-up MFA
            </button>
            <button type="button" className="link-btn" disabled={busy === r.id} onClick={() => decide(r, 'decline')}>
              Decline
            </button>
            <span className="sm muted">Independent approver · requester can’t approve own grant</span>
          </div>
        </section>
      ))}
    </>
  );
};

const MineTable: React.FC<{ items: GrantRequest[]; single: boolean }> = ({ items, single }) => (
  <section className="card">
    <h3>My requests</h3>
    {items.length === 0 ? (
      <Empty compact title="No open requests">
        {single ? 'On this server a request starts the grant at once — it appears under Grants.' : 'Requests you send wait for another Super Admin.'}
      </Empty>
    ) : (
      <table className="tbl mid" style={{ marginTop: 8 }}>
        <thead>
          <tr>
            <th>Request</th>
            <th>Type</th>
            <th>Incident</th>
            <th>Target</th>
            <th>Requested</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td className="mono sm">{r.id}</td>
              <td>
                <TypeLabel t={r.type} />
              </td>
              <td>{r.incident_ref}</td>
              <td className="sm">
                {r.tenant} · {r.targets.length} of {r.owner}
              </td>
              <td>{tShort(r.requested_at)}</td>
              <td>
                <span className={`lbl ${r.status === 'pending' ? 'ylw' : r.status === 'declined' ? 'red' : 'grn'}`}>{r.status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    )}
  </section>
);

const UseLog: React.FC<{ grant: BreakGlassGrant; onRevoked: () => void; actions?: boolean }> = ({ grant, onRevoked, actions = true }) => {
  const toast = useToast();
  const log = useUseLog(grant);
  const revoke = async () => {
    try {
      await api.endBreakGlass();
      toast('Grant revoked. Personal content closes on every open screen.');
      onRevoked();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };
  return (
    <section className="card">
      <div className="card-head">
        <h3>{grantId(grant.id)} · use log</h3>
        <span className="sm muted">immutable · high severity</span>
      </div>
      {log.loading && !log.data ? (
        <SkLines lines={4} />
      ) : (log.data ?? []).length === 0 ? (
        <p className="sm muted" style={{ marginTop: 10 }}>
          Nothing recorded under this grant yet.
        </p>
      ) : (
        <table className="tbl mid" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Record</th>
              <th>Owner notified</th>
            </tr>
          </thead>
          <tbody>
            {log.data!.map((e) => {
              const n = (e.metadata as Record<string, unknown> | null)?.owner_notified_at as string | undefined;
              return (
                <tr key={e.id}>
                  <td className="mono">{tShort(e.timestamp, true)}</td>
                  <td className="mono sm">{e.operation || e.event_type}</td>
                  <td className="mono sm">{e.memory_id ? shortId(e.memory_id) : '—'}</td>
                  <td className="sm">{n ? <span className="ok">● {tShort(n)}</span> : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {actions && grant.active && (
        <div className="rq-actions" style={{ marginTop: 14 }}>
          <a className="btn bs sm-btn" href={buildHash(`/grant/${grant.id}`)}>
            Open records under grant
          </a>
          <a className="link-btn" href={buildHash('/incident-request', { extend: grant.incident_ref })}>
            Request extension…
          </a>
          <button type="button" className="btn bd-solid sm-btn" onClick={revoke}>
            Revoke
          </button>
        </div>
      )}
    </section>
  );
};

const RulesCard: React.FC<{ hours: number; notify: boolean }> = ({ hours, notify }) => (
  <section className="card">
    <h3>Rules</h3>
    <ul className="rule-list">
      <li>Super Admins are set by the deployment, never in the dashboard.</li>
      <li>A second Super Admin approves; you can’t approve your own.</li>
      <li>
        <TypeLabel t="inspect" /> <span>reads named records and versions only, {hours} hours at most, no export.</span>
      </li>
      <li>
        <TypeLabel t="remediate" /> <span>performs one named quarantine, restore or delete, 1 hour at most, approved separately.</span>
      </li>
      <li>No grant opens a whole tenant or widens the SA’s own agents.</li>
      <li>Every memory opened is audited with incident and justification.</li>
      <li>{notify ? 'Owners see each access in notifications and My activity.' : 'Owner notices are off for this tenant.'}</li>
    </ul>
  </section>
);

const ReportCard: React.FC<{ report: ReturnType<typeof useApi<BreakGlassReport>>; wide?: boolean }> = ({ report, wide }) => {
  const r = report.data;
  const download = () => {
    if (!r) return;
    const csv = [['actor', 'incident', 'owner', 'reads', 'first', 'last'], ...r.accesses.map((a) => [a.actor, a.incident_ref ?? '', a.owner, a.reads, a.first, a.last])]
      .map((x) => x.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = `incident-access-${r.month}.csv`;
    a.click();
  };
  return (
    <section className="card">
      <h3>Monthly report · {new Date().toLocaleDateString('en-US', { month: 'long' })}</h3>
      <button type="button" className="link-btn" style={{ textDecoration: 'none', marginTop: 6 }} disabled={!r} onClick={download}>
        Download
      </button>
      {report.error ? (
        <ErrorState compact error={report.error} onRetry={report.reload} />
      ) : !r ? (
        <SkLines lines={4} />
      ) : (
        <>
          <dl className="detail-kv nums">
            <dt>Grants</dt>
            <dd>{fmtInt(r.totals.grants)}</dd>
            <dt>Records read</dt>
            <dd>{fmtInt(r.totals.reads)}</dd>
            <dt>Owners affected</dt>
            <dd>{fmtInt(r.totals.owners)}</dd>
          </dl>
          {wide && r.accesses.length > 0 && (
            <table className="tbl mid" style={{ marginTop: 14 }}>
              <thead>
                <tr>
                  <th>Super Admin</th>
                  <th>Incident</th>
                  <th>Owner</th>
                  <th>Opened</th>
                  <th>First – last</th>
                </tr>
              </thead>
              <tbody>
                {r.accesses.map((a) => (
                  <tr key={`${a.actor}-${a.incident_ref}-${a.owner}`}>
                    <td>{a.actor}</td>
                    <td>{a.incident_ref ?? '—'}</td>
                    <td>{a.owner}</td>
                    <td>{a.reads}</td>
                    <td className="sm">
                      {dShort(a.first)} {tShort(a.first)} – {tShort(a.last)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="sm muted" style={{ marginTop: 10 }}>
            Sent to each affected tenant’s Platform Admins and the security team.
          </p>
        </>
      )}
    </section>
  );
};

/* ------------------------------------------------------------------ */
/* Request wizard                                                       */
/* ------------------------------------------------------------------ */

const STEPS = ['Incident', 'Grant type & target', 'Reason & window', 'Independent approver', 'Step-up MFA & activate'];

export const IncidentRequest: React.FC = () => {
  const toast = useToast();
  const { tenant: myTenant } = useApp();
  const bg = useApi<BreakGlassState>(() => api.breakGlass(), []);
  const sec = useApi(() => platform.security(), []);
  const tenants = useApi(() => platform.tenants(), []);
  const [step, setStep] = useState(0);
  const [incident, setIncident] = useState('');
  const [type, setType] = useState<'inspect' | 'remediate'>('inspect');
  const [tenant, setTenant] = useState('');
  const [owner, setOwner] = useState('');
  const [targets, setTargets] = useState('');
  const [ops, setOps] = useState<string[]>(['Read content', 'Read version history']);
  const [action, setAction] = useState('quarantine');
  const [reason, setReason] = useState('');
  const [hours, setHours] = useState(4);
  const [busy, setBusy] = useState(false);
  const maxHours = type === 'inspect' ? bg.data?.policy.hours ?? 4 : 1;
  const incidents = (sec.data?.incidents ?? []).filter((i) => i.status !== 'closed');
  const tenantList = (tenants.data?.items ?? []).map((t) => t.id);
  const t = tenant || tenantList[0] || myTenant;
  const targetList = targets
    .split(/[\s,]+/)
    .map((x) => x.trim())
    .filter(Boolean);
  const pattern = bg.data?.policy.pattern;
  const refOk = (() => {
    try {
      return !!pattern && new RegExp(pattern).test(incident.trim());
    } catch {
      return incident.trim().length >= 3;
    }
  })();
  const ok = [refOk, !!owner.trim() && targetList.length > 0, reason.trim().length >= 20 && hours > 0 && hours <= maxHours, true, true];
  const toggle = (o: string) => setOps((x) => (x.includes(o) ? x.filter((y) => y !== o) : [...x, o]));
  const submit = async () => {
    setBusy(true);
    try {
      const r = await platform.requestGrant({
        incident_ref: incident.trim(),
        type,
        tenant: t,
        owner: owner.trim(),
        targets: targetList,
        operations: type === 'inspect' ? ops : [action],
        action: type === 'remediate' ? `${action} ${targetList.join(', ')}` : null,
        reason: reason.trim(),
        window_hours: Math.min(hours, maxHours),
      });
      if (r.started) {
        toast(`Grant ${incident} started — this server does not ask for a second approver or MFA yet.`);
        window.location.hash = buildHash(`/grant/${r.id}`);
        window.location.reload();
      } else {
        toast(`Request ${r.id} sent. Another Super Admin approves it in their own session.`);
        navigate('/incident', { tab: 'mine' });
      }
    } catch (e) {
      toast(errorMessage(e), 'err');
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Request incident access"
        crumbs={[{ label: 'Incident access', href: buildHash('/incident') }, { label: 'New request' }]}
        description="An addressed, time-bound grant for one incident: which tenant, which records, which operations, why and for how long. It starts only after an independent Super Admin approves and you pass step-up MFA."
      />
      <div className="body">
        <section className="card">
          <div className="wizard">
            {STEPS.map((s, i) => (
              <div key={s} className={`wz-step ${i < step ? 'done' : i === step ? 'on' : ''}`}>
                <span className="wz-dot">{i < step ? <Icon.Check size={14} /> : i + 1}</span>
                {s}
              </div>
            ))}
          </div>
        </section>
        <div className="row-wrap">
          <section className="card col-main" style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {step === 0 && (
              <div className="f">
                <label htmlFor="rq-i">
                  Incident <span className="err">*</span>
                </label>
                {incidents.length > 0 ? (
                  <select id="rq-i" className="in" value={incident} onChange={(e) => setIncident(e.target.value)}>
                    <option value="">Choose an open incident…</option>
                    {incidents.map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.id} · {i.title}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input id="rq-i" className="in mono" value={incident} onChange={(e) => setIncident(e.target.value)} placeholder="INC-2291" />
                )}
                <span className="hint">A grant cannot exist without an open incident{incident && !refOk ? ` · use the tracker reference (${pattern})` : '.'}</span>
              </div>
            )}
            {step === 1 && (
              <>
                <div className="f">
                  <label>
                    Grant type <span className="err">*</span>
                  </label>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {(
                      [
                        ['inspect', 'Read named records', `Content and versions of the target records, and only the search results needed for them. Read-only, no export. Up to ${bg.data?.policy.hours ?? 4} h.`],
                        ['remediate', 'One named action', 'Quarantine, restore or delete the target records. Approved separately from any inspect grant. Up to 1 h. Hard delete adds its own reason and confirmation and writes a sanitized audit entry.'],
                      ] as const
                    ).map(([v, l, d]) => (
                      <label key={v} className={`choice ${type === v ? 'on' : ''}`}>
                        <input type="radio" name="gtype" checked={type === v} onChange={() => setType(v)} />
                        <span>
                          <TypeLabel t={v} /> <b>{l}</b>
                          <span className="sm muted" style={{ display: 'block', marginTop: 6 }}>
                            {d}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="f">
                  <label htmlFor="rq-t">
                    Tenant <span className="err">*</span>
                  </label>
                  <select id="rq-t" className="in" value={t} onChange={(e) => setTenant(e.target.value)}>
                    {[...new Set([...tenantList, myTenant])].filter(Boolean).map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </select>
                  <span className="hint">One tenant per grant.</span>
                </div>
                <div className="f">
                  <label htmlFor="rq-o">
                    Owner <span className="err">*</span>
                  </label>
                  <input id="rq-o" className="in" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="Tom Becker (tbecker)" />
                </div>
                <div className="f">
                  <label htmlFor="rq-r">
                    Target records <span className="err">*</span>
                  </label>
                  <input id="rq-r" className="in mono" value={targets} onChange={(e) => setTargets(e.target.value)} placeholder="mem_4e21…b90, mem_4e22…0c1" />
                  <span className="hint">Named IDs only. “Whole personal scope” and “whole tenant” are not available.</span>
                </div>
                {type === 'inspect' ? (
                  <div className="f">
                    <label>Operations</label>
                    {['Read content', 'Read version history', 'Run search limited to the targets'].map((o) => (
                      <label key={o} className="set-check" style={{ justifyContent: 'flex-start', paddingTop: 6 }}>
                        <input type="checkbox" checked={ops.includes(o)} onChange={() => toggle(o)} />
                        <span>{o}</span>
                      </label>
                    ))}
                    {['Export · never available', 'Use my agents under this grant · never available'].map((o) => (
                      <label key={o} className="set-check dis" style={{ justifyContent: 'flex-start', paddingTop: 6 }}>
                        <input type="checkbox" disabled checked={false} />
                        <span>{o}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="f">
                    <label htmlFor="rq-a">Action</label>
                    <select id="rq-a" className="in" value={action} onChange={(e) => setAction(e.target.value)}>
                      <option value="quarantine">Quarantine</option>
                      <option value="restore">Restore</option>
                      <option value="hard delete">Hard delete (all versions)</option>
                    </select>
                  </div>
                )}
              </>
            )}
            {step === 2 && (
              <>
                <div className="f">
                  <label htmlFor="rq-w">
                    Reason <span className="err">*</span>
                  </label>
                  <textarea id="rq-w" className="in" style={{ minHeight: 80 }} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Confirm whether customer IDs left the tenant through gpt-reports." />
                  <span className="hint">At least 20 characters. Stored with every read and shown to the owner and in the monthly report.</span>
                </div>
                <div className="f">
                  <label htmlFor="rq-h">Window · hours (max {maxHours})</label>
                  <input id="rq-h" className="in" type="number" min={0.5} max={maxHours} step={0.5} value={Math.min(hours, maxHours)} onChange={(e) => setHours(Number(e.target.value))} />
                  <span className="hint">Starts at activation; ends earlier when the incident closes.</span>
                </div>
              </>
            )}
            {step === 3 && (
              <div>
                <h3>Independent approver</h3>
                <p className="sm" style={{ margin: '8px 0' }}>
                  Another Super Admin approves in their own session. You cannot approve your own request, and approval does not start the grant — activation does.
                </p>
                {requestsSingle(tenants.data?.source) && (
                  <p className="sm muted">
                    <Sim /> This server starts the grant when you activate it, without a second approver.
                  </p>
                )}
              </div>
            )}
            {step === 4 && (
              <div>
                <h3>Step-up MFA &amp; activate</h3>
                <p className="sm" style={{ margin: '8px 0' }}>
                  At activation you confirm with your second factor. The grant then opens exactly these records for {Math.min(hours, maxHours)} h:
                </p>
                <dl className="detail-kv">
                  <dt>Incident</dt>
                  <dd>{incident}</dd>
                  <dt>Type</dt>
                  <dd>
                    <TypeLabel t={type} />
                  </dd>
                  <dt>Target</dt>
                  <dd>
                    {t} · {targetList.length} record{targetList.length === 1 ? '' : 's'} of {owner}
                  </dd>
                  <dt>Allowed</dt>
                  <dd>{type === 'inspect' ? ops.join(' · ') : action}</dd>
                </dl>
                {requestsSingle(tenants.data?.source) && (
                  <p className="sm muted" style={{ marginTop: 10 }}>
                    <Sim /> Step-up MFA is not checked by this server.
                  </p>
                )}
              </div>
            )}
            <div className="rq-actions" style={{ justifyContent: 'flex-end' }}>
              <button type="button" className="link-btn" onClick={() => (step === 0 ? navigate('/incident') : setStep(step - 1))}>
                Back
              </button>
              {step < 4 ? (
                <button type="button" className="btn bp" disabled={!ok[step]} onClick={() => setStep(step + 1)}>
                  Next: {STEPS[step + 1].toLowerCase()}
                </button>
              ) : (
                <button type="button" className="btn bp" disabled={busy || !ok.every(Boolean)} onClick={submit}>
                  {requestsSingle(tenants.data?.source) ? 'Activate grant' : 'Send for approval'}
                </button>
              )}
            </div>
          </section>
          <aside className="col-side" style={{ flex: '1 1 300px', maxWidth: 420 }}>
            <section className="card">
              <h3>What happens next</h3>
              <ul className="next-list">
                <li>
                  <Icon.Check size={14} />
                  <span>
                    <b>Independent approver</b>
                    <span className="sm muted" style={{ display: 'block' }}>
                      Another Super Admin approves in their own session. Self-approval is impossible.
                    </span>
                  </span>
                </li>
                <li>
                  <Icon.Shield size={14} />
                  <span>
                    <b>Step-up MFA</b>
                    <span className="sm muted" style={{ display: 'block' }}>
                      At activation, not at sign-in.
                    </span>
                  </span>
                </li>
                <li>
                  <Icon.Clock size={14} />
                  <span>
                    <b>Automatic expiry</b>
                    <span className="sm muted" style={{ display: 'block' }}>
                      At the end of the window or when the incident closes. Extension is a new approval.
                    </span>
                  </span>
                </li>
                <li>
                  <Icon.EyeOff size={14} />
                  <span>
                    <b>Every use is HIGH severity</b>
                    <span className="sm muted" style={{ display: 'block' }}>
                      Incident ID, justification and owner on each event.
                    </span>
                  </span>
                </li>
                <li>
                  <Icon.Bell size={14} />
                  <span>
                    <b>Owner notice</b>
                    <span className="sm muted" style={{ display: 'block' }}>
                      {bg.data?.policy.notify_owner === false ? 'Off for this tenant.' : 'By policy; any delay is recorded with a reason.'}
                    </span>
                  </span>
                </li>
              </ul>
            </section>
            <div className="alert" role="note">
              <Icon.Info size={16} />
              <span className="sm">Your own memories need no grant — open them in My workspace.</span>
            </div>
          </aside>
        </div>
      </div>
    </>
  );
};
const requestsSingle = (source?: string) => source === 'single-tenant';

/* ------------------------------------------------------------------ */
/* Grant detail                                                         */
/* ------------------------------------------------------------------ */

export const GrantDetail: React.FC<{ route: HashRoute }> = ({ route }) => {
  const id = decodeURIComponent(route.path.slice('/grant/'.length));
  const toast = useToast();
  const { data, error, loading, reload } = useApi<BreakGlassState>(() => api.breakGlass(), []);
  const g = data ? [...(data.active ? [data.active] : []), ...data.grants].find((x) => x.id === id) ?? null : null;
  const log = useUseLog(g);
  const records = [...new Set((log.data ?? []).filter((e) => e.memory_id).map((e) => e.memory_id!))];
  const [idx, setIdx] = useState(0);
  const recId = records[idx] ?? null;
  const rec = useApi<MemoryContext | null>(() => (recId && g?.active ? api.memoryContext(recId) : Promise.resolve(null)), [recId, g?.active]);

  if (error && !data)
    return (
      <div className="body">
        <section className="card">
          <ErrorState error={error} onRetry={reload} />
        </section>
      </div>
    );
  if (loading || !data)
    return (
      <div className="body">
        <section className="card">
          <SkLines lines={8} />
        </section>
      </div>
    );
  if (!g)
    return (
      <div className="body">
        <section className="card">
          <Empty title="Grant not found" action={<a className="btn bs" href={buildHash('/incident')}>Back to Incident access</a>}>
            The server returns only grants that exist; an expired grant moves to History.
          </Empty>
        </section>
      </div>
    );
  const t = grantType(g);
  const m = rec.data?.memory;
  const revoke = async () => {
    try {
      await api.endBreakGlass();
      toast('Grant revoked.');
      window.location.reload();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };

  return (
    <>
      <PageHeader
        title={`Grant ${grantId(g.id)} · ${g.incident_ref}`}
        crumbs={[{ label: 'Incident access', href: buildHash('/incident') }, { label: grantId(g.id) }]}
        description="The grant is read from the server on every load: after a reload it is shown only while it is valid. Expiry or revocation closes content on every open screen."
        actions={
          <>
            <TypeLabel t={t} />
            <span className={`lbl ${g.active ? 'grn' : 'g'}`}>{g.active ? '✓ Active' : 'Expired'}</span>
          </>
        }
      />
      <div className="body">
        <div className="row-wrap">
          <div className="col-main" style={{ minWidth: 0 }}>
            <section className="card">
              <div className="card-head">
                <h3>Record under investigation</h3>
                <span className="lbl ylw">
                  <Icon.EyeOff size={12} /> This read is audited
                </span>
              </div>
              {!g.active ? (
                <p className="sm muted" style={{ marginTop: 10 }}>
                  Content is closed: this grant is no longer valid. Its read log stays below.
                </p>
              ) : !recId ? (
                <p className="sm muted" style={{ marginTop: 10 }}>
                  No record opened under this grant yet. Open one from Content moderation (personal records show their ID) or by its ID.
                </p>
              ) : rec.loading && !rec.data ? (
                <SkLines lines={5} />
              ) : rec.error ? (
                <ErrorState error={rec.error} compact onRetry={rec.reload} />
              ) : (
                m && (
                  <>
                    <dl className="detail-kv" style={{ gridTemplateColumns: '140px 1fr' }}>
                      <dt>Memory</dt>
                      <dd className="mono">
                        {shortId(m.id)} · v{m.version}
                      </dd>
                      <dt>Owner</dt>
                      <dd>
                        {m.owner_id} · <span className="lbl blue">Personal</span>
                      </dd>
                      <dt>Written by</dt>
                      <dd>
                        {m.actor_id ?? '—'}
                        {m.driver_id ? ` on behalf of ${m.driver_id}` : ''} · {dShort(m.created_at)} {tShort(m.created_at)}
                      </dd>
                      <dt>Content</dt>
                      <dd>
                        <div className="quote" style={{ background: '#fffbeb', borderColor: '#f0ab00' }}>
                          {m.content}
                        </div>
                      </dd>
                    </dl>
                    <div className="rq-actions" style={{ marginTop: 14 }}>
                      {records.length > 1 && (
                        <button type="button" className="btn bs sm-btn" onClick={() => setIdx((idx + 1) % records.length)}>
                          Next record ({((idx + 1) % records.length) + 1} of {records.length})
                        </button>
                      )}
                      <a className="link-btn" href={buildHash(`/memory/${m.id}`)}>
                        Open full record
                      </a>
                    </div>
                  </>
                )
              )}
            </section>
            <UseLog grant={g} onRevoked={reload} actions={false} />
          </div>
          <aside className="col-side" style={{ flex: '1 1 300px', maxWidth: 400 }}>
            <section className="card">
              <h3>Grant record</h3>
              <dl className="detail-kv">
                <dt>Requested by</dt>
                <dd>{g.username}</dd>
                <dt>Approved by</dt>
                <dd>
                  — <Sim />
                </dd>
                <dt>Incident</dt>
                <dd>{g.incident_ref}</dd>
                <dt>Reason</dt>
                <dd>{g.justification}</dd>
                <dt>Activated</dt>
                <dd>{tShort(g.created_at)}</dd>
                <dt>Expires</dt>
                <dd>
                  {tShort(g.expires_at)} · or when {g.incident_ref} closes
                </dd>
                <dt>Reads so far</dt>
                <dd>
                  {g.reads ?? records.length} · {g.owners ?? 0} owner{g.owners === 1 ? '' : 's'}
                </dd>
              </dl>
              {g.active && (
                <div className="rq-actions" style={{ marginTop: 14 }}>
                  <button type="button" className="btn bd-solid sm-btn" onClick={revoke}>
                    Revoke grant
                  </button>
                  <a className="link-btn" href={buildHash('/incident-request', { extend: g.incident_ref })}>
                    Request extension…
                  </a>
                </div>
              )}
            </section>
            <section className="card">
              <h3>After expiry</h3>
              <p className="sm" style={{ margin: '10px 0 0', lineHeight: 1.55 }}>
                Content disappears from every open screen, the API returns “not available” again, and the grant moves to History with its full read log. The monthly
                privileged-access report lists it for the tenant owner.
              </p>
            </section>
          </aside>
        </div>
      </div>
    </>
  );
};

export default Incident;
