import React, { useEffect, useRef, useState } from 'react';
import { platform, type PlatformPolicies } from '@/api/platform';
import { PageHeader, Tabs } from '@/components/Shell';
import { ErrorState, Icon, Modal, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import type { HashRoute } from '@/hooks/useHashRoute';
import { errorMessage, fmtInt } from '@/utils/format';
import { Note, SingleTenant } from './common';

const SECTIONS = [
  { id: 'security', label: 'Security & access' },
  { id: 'rules', label: 'System curation rules' },
  { id: 'models', label: 'Models' },
  { id: 'limits', label: 'Limits & quotas' },
  { id: 'retention', label: 'Retention ceilings' },
  { id: 'registration', label: 'Registration' },
];
type Editable = Omit<PlatformPolicies, 'source' | 'system_rules'>;
const pick = (p: PlatformPolicies): Editable => ({ privileged: p.privileged, models: p.models, limits: p.limits, registration: p.registration });
const ACTION: Record<string, string> = { block: 'Block', quarantine: 'Quarantine', flag: 'Flag', redact: 'Redact', reject_with_pointer: 'Route', merge: 'Merge', decay_weight: 'Decay' };

const Policies: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { data, error, reload, setData } = useApi<PlatformPolicies>(() => platform.policies(), []);
  const [v, setV] = useState<Editable | null>(null);
  const [active, setActive] = useState(route.params.get('tab') ?? 'security');
  const [confirm, setConfirm] = useState<null | 'save' | 'preview'>(null);
  const [newRule, setNewRule] = useState(false);
  const refs = useRef<Record<string, HTMLElement | null>>({});
  useEffect(() => {
    if (data) setV(structuredClone(pick(data)));
  }, [data]);
  useEffect(() => {
    const t = route.params.get('tab');
    if (t && refs.current[t]) refs.current[t]!.scrollIntoView({ block: 'start' });
  }, [v !== null]);
  const dirty = data && v ? JSON.stringify(pick(data)) !== JSON.stringify(v) : false;
  const sec = (id: string) => (el: HTMLElement | null) => {
    refs.current[id] = el;
  };
  const jump = (id: string) => {
    refs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setActive(id);
  };
  const upd = <K extends keyof Editable>(k: K, patch: Partial<Editable[K]>) => setV((x) => (x ? { ...x, [k]: { ...x[k], ...patch } } : x));
  const num = (s: string) => (s.trim() === '' ? null : Number(s.replace(/,/g, '')));

  return (
    <>
      <PageHeader
        title="Global policies & models"
        crumbs={[{ label: 'Global policies & models' }]}
        description="Defaults and limits every tenant inherits. Tenants can be stricter, never looser. Each change asks for a reason and lists the tenants it affects."
        actions={
          <>
            <button type="button" className="btn bs" disabled={!dirty} onClick={() => setConfirm('preview')}>
              Preview impact
            </button>
            <button type="button" className="btn bp" disabled={!dirty} onClick={() => setConfirm('save')}>
              Save · audited
            </button>
          </>
        }
        tabs={
          <Tabs
            label="Policy sections"
            value={active}
            onChange={jump}
            tabs={SECTIONS.map((s) => ({ value: s.id, label: s.label, count: s.id === 'rules' && data ? data.system_rules.length : undefined }))}
          />
        }
      />
      <div className="body">
        <SingleTenant source={data?.source} />
        {error && !data ? (
          <section className="card">
            <ErrorState error={error} onRetry={reload} />
          </section>
        ) : !v || !data ? (
          <section className="card">
            <SkLines lines={10} />
          </section>
        ) : (
          <>
            <div className="pol-grid">
              <section className="card" id="pol-security" ref={sec('security')}>
                <h3>Privileged access</h3>
                <div className="set-check dis">
                  <span>Incident grants need an independent second Super Admin</span>
                  <span className="sm" style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}>
                    <Icon.Lock size={12} /> Always · no self-approval
                  </span>
                </div>
                <div className="f set-f">
                  <label htmlFor="pl-i">Maximum inspect grant window</label>
                  <select id="pl-i" className="in" value={v.privileged.inspect_max_hours} onChange={(e) => upd('privileged', { inspect_max_hours: Number(e.target.value) })}>
                    {[1, 2, 4, 8, 24].map((h) => (
                      <option key={h} value={h}>
                        {h} hour{h === 1 ? '' : 's'}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="f set-f">
                  <label htmlFor="pl-r">Maximum remediate grant window</label>
                  <select id="pl-r" className="in" value={v.privileged.remediate_max_hours} onChange={(e) => upd('privileged', { remediate_max_hours: Number(e.target.value) })}>
                    <option value={0.5}>30 min · one named action</option>
                    <option value={1}>1 hour · one named action</option>
                    <option value={2}>2 hours · one named action</option>
                  </select>
                </div>
                <label className="set-check dis">
                  <span>Hard delete under remediate needs an extra confirmation</span>
                  <input type="checkbox" checked disabled />
                </label>
                <label className="set-check">
                  <span>Step-up MFA at activation</span>
                  <input type="checkbox" checked={v.privileged.stepup_mfa} onChange={(e) => upd('privileged', { stepup_mfa: e.target.checked })} />
                </label>
                <label className="set-check">
                  <span>Owner notification (tenants may not disable)</span>
                  <input type="checkbox" checked={v.privileged.owner_notification} onChange={(e) => upd('privileged', { owner_notification: e.target.checked })} />
                </label>
                <div className="set-check dis">
                  <span style={{ display: 'inline-flex', flexDirection: 'row', gap: 6, alignItems: 'center' }}>
                    <Icon.Lock size={12} /> Admin read of personal memory
                  </span>
                  <span className="sm">Never · fixed</span>
                </div>
              </section>

              <section className="card" id="pol-models" ref={sec('models')}>
                <h3>Models</h3>
                <div className="f set-f">
                  <label htmlFor="pl-e">Embedding model</label>
                  <select id="pl-e" className="in" value={v.models.embedding} onChange={(e) => upd('models', { embedding: e.target.value })}>
                    {[...new Set([v.models.embedding, ...v.models.embedding_options])].map((m) => (
                      <option key={m}>{m}</option>
                    ))}
                  </select>
                  <span className="hint">Changing it triggers re-embedding in every tenant</span>
                </div>
                <div className="f set-f">
                  <label htmlFor="pl-rr">Reranker</label>
                  <select id="pl-rr" className="in" value={v.models.reranker} onChange={(e) => upd('models', { reranker: e.target.value })}>
                    {[...new Set([v.models.reranker, ...v.models.reranker_options])].map((m) => (
                      <option key={m}>{m}</option>
                    ))}
                  </select>
                </div>
                <div className="f set-f">
                  <label htmlFor="pl-mp">Default MCP tool profile</label>
                  <select id="pl-mp" className="in" value={v.models.mcp_profile} onChange={(e) => upd('models', { mcp_profile: e.target.value as 'compact' | 'full' })}>
                    <option value="full">full</option>
                    <option value="compact">compact</option>
                  </select>
                  <span className="hint">Tenants may restrict to compact</span>
                </div>
              </section>

              <section className="card" id="pol-rules" ref={sec('rules')}>
                <div className="card-head">
                  <h3>System curation rules</h3>
                  <button type="button" className="link-btn" style={{ textDecoration: 'none' }} onClick={() => setNewRule(true)}>
                    <Icon.Plus size={12} /> New
                  </button>
                </div>
                {data.system_rules.length === 0 ? (
                  <p className="sm muted" style={{ marginTop: 10 }}>
                    The MCP server seeds system rules on the first write of each tenant.
                  </p>
                ) : (
                  <table className="tbl" style={{ marginTop: 8 }}>
                    <thead>
                      <tr>
                        <th>Rule</th>
                        <th>Type</th>
                        <th>Action</th>
                        <th>Hits · 7 d</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.system_rules.map((r) => (
                        <tr key={r.id}>
                          <td>{r.name}</td>
                          <td>
                            <span className="tag">{r.tier}</span>
                          </td>
                          <td>{ACTION[r.action] ?? r.action}</td>
                          <td>{r.hits !== null ? fmtInt(r.hits) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              <section className="card" id="pol-limits" ref={sec('limits')}>
                <h3>Limits &amp; retention ceilings</h3>
                <div className="set-two">
                  <div className="f set-f">
                    <label htmlFor="pl-rl">Rate limit per tenant · /min</label>
                    <input id="pl-rl" className="in" type="number" min={0} value={v.limits.rate_limit_per_min ?? ''} placeholder="Unlimited" onChange={(e) => upd('limits', { rate_limit_per_min: num(e.target.value) })} />
                  </div>
                  <div className="f set-f">
                    <label htmlFor="pl-mq">Default memory quota</label>
                    <input id="pl-mq" className="in" type="number" min={0} value={v.limits.memory_quota ?? ''} placeholder="No limit" onChange={(e) => upd('limits', { memory_quota: num(e.target.value) })} />
                  </div>
                </div>
                <div className="set-two" id="pol-retention" ref={sec('retention')}>
                  <div className="f set-f">
                    <label htmlFor="pl-fa">Max full-detail audit · days</label>
                    <select id="pl-fa" className="in" value={v.limits.max_full_audit_days} onChange={(e) => upd('limits', { max_full_audit_days: Number(e.target.value) })}>
                      {[30, 60, 90, 180, 365].map((d) => (
                        <option key={d} value={d}>
                          {d} days
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="f set-f">
                    <label>Privileged access events</label>
                    <input className="in" value={`${v.limits.privileged_years} years · immutable`} disabled readOnly />
                  </div>
                </div>
                <div className="f set-f" id="pol-registration" ref={sec('registration')}>
                  <label htmlFor="pl-ss">Self sign-up allowed</label>
                  <select
                    id="pl-ss"
                    className="in"
                    value={v.registration.self_signup}
                    onChange={(e) => upd('registration', { self_signup: e.target.value as 'per_tenant' | 'invite_only' })}
                  >
                    <option value="per_tenant">Per tenant</option>
                    <option value="invite_only">Invite only, everywhere</option>
                  </select>
                </div>
                <label className="set-check">
                  <span>Require MFA for every administrator</span>
                  <input type="checkbox" checked={v.registration.require_mfa_admins} onChange={(e) => upd('registration', { require_mfa_admins: e.target.checked })} />
                </label>
              </section>
            </div>
            <Note>Saving shows the tenants that would be affected and records the change in Global audit, visible to each tenant’s Platform Admins.</Note>
          </>
        )}
      </div>
      {confirm && v && (
        <SaveModal
          mode={confirm}
          values={v}
          onClose={() => setConfirm(null)}
          onSaved={(res) => {
            setConfirm(null);
            setData(res);
            toast('Global policies saved · recorded in Global audit.');
          }}
        />
      )}
      {newRule && <NewRuleModal onClose={() => setNewRule(false)} onDone={() => { setNewRule(false); reload(); }} />}
    </>
  );
};

const SaveModal: React.FC<{ mode: 'save' | 'preview'; values: Editable; onClose: () => void; onSaved: (p: PlatformPolicies) => void }> = ({ mode, values, onClose, onSaved }) => {
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const preview = useApi(() => platform.previewPolicies(values), []);
  return (
    <Modal
      title={mode === 'save' ? 'Save global policies' : 'Impact of these changes'}
      onClose={onClose}
      actions={
        <>
          {mode === 'save' && (
            <button
              type="button"
              className="btn bp"
              disabled={busy || reason.trim().length < 4}
              onClick={async () => {
                setBusy(true);
                try {
                  onSaved(await platform.savePolicies({ ...values, reason: reason.trim() }));
                } catch (e) {
                  toast(errorMessage(e), 'err');
                } finally {
                  setBusy(false);
                }
              }}
            >
              Save · audited
            </button>
          )}
          <button type="button" className="btn bg" onClick={onClose}>
            {mode === 'save' ? 'Cancel' : 'Close'}
          </button>
        </>
      }
    >
      <h4 style={{ margin: '0 0 8px' }}>Tenants affected</h4>
      {preview.loading && !preview.data ? (
        <SkLines lines={3} />
      ) : preview.error ? (
        <p className="sm muted">{errorMessage(preview.error)}</p>
      ) : preview.data!.tenants.length === 0 ? (
        <p className="sm muted">No tenant changes: every tenant is already stricter than the new values.</p>
      ) : (
        <ul className="rule-list">
          {preview.data!.tenants.map((t) => (
            <li key={t.id}>
              <b>{t.id}</b> <span className="sm muted">{t.change}</span>
            </li>
          ))}
        </ul>
      )}
      {mode === 'save' && (
        <div className="f" style={{ marginTop: 14 }}>
          <label htmlFor="pol-why">Reason</label>
          <input id="pol-why" className="in" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Load growth across tenants" autoFocus />
        </div>
      )}
    </Modal>
  );
};

const NewRuleModal: React.FC<{ onClose: () => void; onDone: () => void }> = ({ onClose, onDone }) => {
  const toast = useToast();
  const [name, setName] = useState('');
  const [tier, setTier] = useState<'regex' | 'embedding'>('regex');
  const [pattern, setPattern] = useState('');
  const [threshold, setThreshold] = useState(0.85);
  const [action, setAction] = useState('block');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title="New system curation rule"
      onClose={onClose}
      actions={
        <>
          <button
            type="button"
            className="btn bp"
            disabled={busy || !name.trim() || (tier === 'regex' && !pattern) || reason.trim().length < 4}
            onClick={async () => {
              setBusy(true);
              try {
                await platform.createSystemRule({ name: name.trim(), tier, pattern: tier === 'regex' ? pattern : undefined, threshold: tier === 'embedding' ? threshold : undefined, action, reason: reason.trim() });
                toast(`${name} added to every tenant.`);
                onDone();
              } catch (e) {
                toast(errorMessage(e), 'err');
              } finally {
                setBusy(false);
              }
            }}
          >
            Create · audited
          </button>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="rule-edit-grid">
        <div className="f">
          <label htmlFor="nr-n">Name</label>
          <input id="nr-n" className="in mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="pii.iban" />
        </div>
        <div className="f">
          <label htmlFor="nr-t">Type</label>
          <select id="nr-t" className="in" value={tier} onChange={(e) => setTier(e.target.value as 'regex' | 'embedding')}>
            <option value="regex">regex</option>
            <option value="embedding">embedding</option>
          </select>
        </div>
        {tier === 'regex' ? (
          <div className="f">
            <label htmlFor="nr-p">Pattern</label>
            <input id="nr-p" className="in mono" value={pattern} onChange={(e) => setPattern(e.target.value)} />
          </div>
        ) : (
          <div className="f">
            <label htmlFor="nr-th">Similarity threshold</label>
            <input id="nr-th" className="in" type="number" step={0.01} min={0.5} max={1} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} />
          </div>
        )}
        <div className="f">
          <label htmlFor="nr-a">Action</label>
          <select id="nr-a" className="in" value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="block">Block</option>
            <option value="quarantine">Quarantine</option>
            <option value="flag">Flag</option>
          </select>
        </div>
        <div className="f" style={{ gridColumn: '1 / -1' }}>
          <label htmlFor="nr-r">Reason</label>
          <input id="nr-r" className="in" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
};

export default Policies;
