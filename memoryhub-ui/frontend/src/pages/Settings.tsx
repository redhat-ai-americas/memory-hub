import React, { useEffect, useRef, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs } from '@/components/Shell';
import { ErrorState, Icon, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash } from '@/hooks/useHashRoute';
import type { CurationPolicy, SettingsResponse, TenantQuotas, TenantSettingsValues } from '@/types';
import { errorMessage, fmtInt, fmtRelative } from '@/utils/format';

const SECTIONS = [
  { id: 'tenant', label: 'Tenant' },
  { id: 'mcp', label: 'MCP endpoint' },
  { id: 'retrieval', label: 'Retrieval' },
  { id: 'governance', label: 'Isolation & governance' },
  { id: 'moderation', label: 'Moderation & compaction' },
  { id: 'audit', label: 'Audit & retention' },
  { id: 'quotas', label: 'Quotas' },
  { id: 'models', label: 'Models' },
] as const;

const CURATION_DEFAULTS: CurationPolicy = {
  dreaming_schedule: 'Daily 06:00',
  age_trigger_days: 90,
  size_trigger_records: 5000,
  auto_quarantine_score: 0.9,
  compaction: 'suggest',
  compaction_preview: true,
  keep_provenance: 'always',
  org_compaction_approval: true,
};
const ZONES = ['UTC', 'Europe/Dublin', 'Europe/London', 'Europe/Berlin', 'Europe/Prague', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Asia/Tokyo', 'Asia/Singapore', 'Australia/Sydney'];
const RETENTION_DAYS = [7, 14, 30, 60, 90, 180, 365, 400];

const Settings: React.FC = () => {
  const toast = useToast();
  const { data, error, loading, reload, setData } = useApi<SettingsResponse>(() => api.settings(), []);
  const [values, setValues] = useState<TenantSettingsValues | null>(null);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<string>('tenant');
  const refs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    if (data) setValues(structuredClone(data.values));
  }, [data]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible) setActive(visible.target.id.replace('set-', ''));
      },
      { rootMargin: '-120px 0px -60% 0px' },
    );
    Object.values(refs.current).forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [values !== null]);

  const dirty = data && values ? JSON.stringify(data.values) !== JSON.stringify(values) : false;
  const set = <S extends keyof TenantSettingsValues, K extends keyof NonNullable<TenantSettingsValues[S]>>(section: S, key: K, value: NonNullable<TenantSettingsValues[S]>[K]) =>
    setValues((v) => (v ? { ...v, [section]: { ...(v[section] as object), [key]: value } } : v));
  const setCuration = <K extends keyof CurationPolicy>(key: K, value: CurationPolicy[K]) =>
    setValues((v) => (v ? { ...v, curation: { ...CURATION_DEFAULTS, ...(v.curation ?? {}), [key]: value } } : v));
  const setQuota = <K extends keyof TenantQuotas>(key: K, value: TenantQuotas[K]) => setValues((v) => (v ? { ...v, quotas: { ...(v.quotas ?? {}), [key]: value } } : v));

  const save = async () => {
    if (!values) return;
    setBusy(true);
    try {
      const res = await api.saveSettings(values);
      setData(res);
      toast('Settings saved. The change is recorded in the audit log.');
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setBusy(false);
    }
  };

  const num = (v: string, fallback: number) => (v.trim() === '' || Number.isNaN(Number(v.replace(/,/g, ''))) ? fallback : Number(v.replace(/,/g, '')));
  const sec = (id: string) => (el: HTMLElement | null) => {
    refs.current[id] = el;
  };
  const jump = (id: string) => {
    refs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setActive(id);
  };
  const rerankerReady = data?.models.reranker.status === 'healthy';
  const pushReady = data?.services?.valkey?.status === 'healthy';

  return (
    <>
      <PageHeader
        title="Tenant settings"
        crumbs={[{ label: 'Tenant settings' }]}
        description="Settings this tenant controls, within the limits Super Admins set for the platform. Locked values show where they come from."
        actions={
          <>
            {dirty && (
              <button type="button" className="btn bg" disabled={busy} onClick={() => data && setValues(structuredClone(data.values))}>
                Discard
              </button>
            )}
            <button type="button" className="btn bp" disabled={!dirty || busy} onClick={save}>
              {busy ? 'Saving…' : 'Save changes'}
            </button>
          </>
        }
        tabs={<Tabs label="Settings sections" value={active} onChange={(v) => jump(v)} tabs={SECTIONS.map((s) => ({ value: s.id, label: s.label }))} />}
      />
      <div className="body">
        {error && !data ? (
          <div className="card">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : loading && !values ? (
          <div className="card">
            <SkLines lines={12} />
          </div>
        ) : (
          values &&
          data && (
            <>
              <div className="set-grid">
                {/* Tenant */}
                <section className="card" id="set-tenant" ref={sec('tenant')}>
                  <h3>Tenant</h3>
                  <Field id="org-name" label="Display name">
                    <input id="org-name" className="in" value={values.organization.name} onChange={(e) => set('organization', 'name', e.target.value)} />
                  </Field>
                  <Field id="tid" label="Tenant ID" hint="Set by the platform at creation">
                    <input id="tid" className="in mono" value={data.tenant.tenant_id} readOnly disabled />
                  </Field>
                  <Field id="tz" label="Default time zone">
                    <select id="tz" className="in" value={values.organization.time_zone ?? 'UTC'} onChange={(e) => set('organization', 'time_zone', e.target.value)}>
                      {[...new Set([...ZONES, values.organization.time_zone ?? 'UTC'])].map((z) => (
                        <option key={z}>{z}</option>
                      ))}
                    </select>
                  </Field>
                  <Field id="org-mail" label="Contact email" hint="Shown on sign-up and in invitations">
                    <input id="org-mail" className="in" type="email" value={values.organization.contact_email} onChange={(e) => set('organization', 'contact_email', e.target.value)} />
                  </Field>
                </section>

                {/* MCP endpoint */}
                <section className="card" id="set-mcp" ref={sec('mcp')}>
                  <h3>MCP endpoint</h3>
                  <dl className="set-kv">
                    <dt>Public URL</dt>
                    <dd className="mono">{data.mcp.public_url}</dd>
                    <dt>In-cluster service</dt>
                    <dd className="mono">{data.mcp.internal_url}</dd>
                    <dt>Auth service</dt>
                    <dd>
                      <span className={data.mcp.status === 'healthy' ? 'ok' : data.mcp.status === 'degraded' ? 'warn' : 'err'}>
                        ● {data.mcp.status === 'healthy' ? 'Healthy' : data.mcp.status === 'degraded' ? 'Degraded' : data.mcp.status === 'down' ? 'Not responding' : 'Not configured'} · OAuth 2.1
                      </span>
                      <div className="sm muted mono" style={{ overflowWrap: 'anywhere' }}>
                        {data.tenant.auth_url}
                      </div>
                    </dd>
                  </dl>
                  <Field id="prof" label="MCP tool profile" hint="Global default: full · tenant may restrict. Compact exposes 4 action tools, full exposes 14.">
                    <select id="prof" className="in" value={values.audit.mcp_profile} onChange={(e) => set('audit', 'mcp_profile', e.target.value as 'compact' | 'full')}>
                      <option value="compact">compact</option>
                      <option value="full">full</option>
                    </select>
                  </Field>
                </section>

                {/* Retrieval */}
                <section className="card" id="set-retrieval" ref={sec('retrieval')}>
                  <h3>Retrieval</h3>
                  <Check
                    label="Cross-encoder reranking"
                    checked={values.retrieval.rerank && !!rerankerReady}
                    disabled={!rerankerReady}
                    hint={rerankerReady ? undefined : 'Reranker service unavailable'}
                    onChange={(v) => set('retrieval', 'rerank', v)}
                  />
                  <Check label="Cache-optimized ordering" checked={values.retrieval.cache_optimized_ordering} onChange={(v) => set('retrieval', 'cache_optimized_ordering', v)} />
                  <Check
                    label="Real-time push to sessions"
                    checked={values.retrieval.realtime_push && !!pushReady}
                    disabled={!pushReady}
                    hint={pushReady ? undefined : 'Valkey unavailable'}
                    onChange={(v) => set('retrieval', 'realtime_push', v)}
                  />
                  <Field id="ct" label="Contradiction revision threshold" hint="Reports needed before the owner is asked to revise">
                    <input id="ct" className="in" type="number" min={1} value={values.governance.contradiction_threshold} onChange={(e) => set('governance', 'contradiction_threshold', num(e.target.value, 3))} />
                  </Field>
                  <div className="set-two">
                    <Field id="mr" label="Max results">
                      <input id="mr" className="in" type="number" min={1} max={50} value={values.retrieval.max_results} onChange={(e) => set('retrieval', 'max_results', num(e.target.value, 10))} />
                    </Field>
                    <Field id="tk" label="Max response tokens">
                      <input id="tk" className="in" type="number" min={100} value={values.retrieval.max_response_tokens} onChange={(e) => set('retrieval', 'max_response_tokens', num(e.target.value, 4000))} />
                    </Field>
                    <Field id="fw" label="Session focus weight">
                      <input id="fw" className="in" type="number" step="0.05" min={0} max={1} value={values.retrieval.session_focus_weight} onChange={(e) => set('retrieval', 'session_focus_weight', num(e.target.value, 0.4))} />
                    </Field>
                    <Field id="st" label="Full-content threshold">
                      <input id="st" className="in" type="number" step="0.05" min={0} max={1} value={values.retrieval.full_content_threshold} onChange={(e) => set('retrieval', 'full_content_threshold', num(e.target.value, 0.8))} />
                    </Field>
                  </div>
                </section>

                {/* Isolation & governance */}
                <section className="card" id="set-governance" ref={sec('governance')}>
                  <h3>Isolation &amp; governance</h3>
                  <Check label="Project isolation" checked={values.governance.project_isolation} disabled hint="Set at deploy time" />
                  <Check label="Role isolation" checked={values.governance.role_isolation} disabled hint="Set at deploy time" />
                  <Field id="ea" label="Enterprise approvers required" hint="Requesters can never approve their own proposal">
                    <input id="ea" className="in" type="number" min={1} value={values.governance.enterprise_approvers} onChange={(e) => set('governance', 'enterprise_approvers', num(e.target.value, 1))} />
                  </Field>
                  <Check label="Hard delete needs a second admin" checked={values.governance.hard_delete_two_person ?? true} onChange={(v) => set('governance', 'hard_delete_two_person', v)} />
                  <Locked label="Admins read personal memory" value="Never · platform rule" />
                  <Locked label="Notify owners of incident reads" value={values.privacy.notify_owner ? 'Always on · Global policy' : 'Off · Global policy'} lockValue />
                  <Check label="Notify owners of review reads" checked={values.governance.notify_review_reads ?? true} onChange={(v) => set('governance', 'notify_review_reads', v)} />
                </section>

                {/* Moderation & compaction */}
                <section className="card" id="set-moderation" ref={sec('moderation')}>
                  <h3>Moderation &amp; compaction</h3>
                  {(() => {
                    const c = { ...CURATION_DEFAULTS, ...(values.curation ?? {}) };
                    const mode = c.compaction === 'suggest' ? (c.compaction_preview ? 'suggest_preview' : 'suggest') : c.compaction;
                    return (
                      <>
                        <Field id="aq" label="Auto-quarantine threshold" hint="Policy score at or above this quarantines a write">
                          <input id="aq" className="in" type="number" min={0.5} max={1} step={0.01} value={c.auto_quarantine_score} onChange={(e) => setCuration('auto_quarantine_score', num(e.target.value, 0.9))} />
                        </Field>
                        <Field id="cm" label="Compaction mode">
                          <select
                            id="cm"
                            className="in"
                            value={mode}
                            onChange={(e) => {
                              const v = e.target.value;
                              setValues((s) =>
                                s
                                  ? {
                                      ...s,
                                      curation: {
                                        ...CURATION_DEFAULTS,
                                        ...(s.curation ?? {}),
                                        compaction: v === 'suggest_preview' ? 'suggest' : (v as CurationPolicy['compaction']),
                                        compaction_preview: v === 'suggest_preview',
                                      },
                                    }
                                  : s,
                              );
                            }}
                          >
                            <option value="off">Off</option>
                            <option value="suggest_preview">Suggest, preview required</option>
                            <option value="suggest">Suggest, no preview</option>
                            <option value="auto">Automatic</option>
                          </select>
                        </Field>
                        <Check label="Org compaction needs approval" checked={c.org_compaction_approval} onChange={(v) => setCuration('org_compaction_approval', v)} />
                        <a className="sm" href={buildHash('/curation')} style={{ display: 'inline-block', marginTop: 12 }}>
                          Dreaming schedule and curation rules →
                        </a>
                      </>
                    );
                  })()}
                </section>

                {/* Audit & retention */}
                <section className="card" id="set-audit" ref={sec('audit')}>
                  <h3>Audit &amp; retention</h3>
                  {(() => {
                    const ceil = values.audit.retention?.ceilings;
                    const maxFull = ceil?.data?.[0] ?? 90;
                    const maxConv = ceil?.conversations?.[0] ?? 30;
                    const conv = values.audit.retention?.conversation_days ?? 14;
                    return (
                      <>
                        <Field id="far" label="Full-detail audit retention" lock="Maximum set by Global policies · Super Admin">
                          <select id="far" className="in" value={values.audit.full_retention_days} onChange={(e) => set('audit', 'full_retention_days', Number(e.target.value))}>
                            {[...new Set([...RETENTION_DAYS.filter((d) => d <= maxFull), values.audit.full_retention_days])]
                              .sort((a, b) => a - b)
                              .map((d) => (
                                <option key={d} value={d}>
                                  {d} days (max {maxFull})
                                </option>
                              ))}
                          </select>
                        </Field>
                        <Field id="cr" label="Conversation retention">
                          <select
                            id="cr"
                            className="in"
                            value={conv}
                            onChange={(e) => set('audit', 'retention', { ...(values.audit.retention ?? {}), conversation_days: Number(e.target.value) })}
                          >
                            {[...new Set([...RETENTION_DAYS.filter((d) => d <= maxConv), conv])]
                              .sort((a, b) => a - b)
                              .map((d) => (
                                <option key={d} value={d}>
                                  {d} days
                                </option>
                              ))}
                          </select>
                        </Field>
                        <Field id="rd" label="Read operation detail" hint="Writes and governance decisions are always logged in full">
                          <select id="rd" className="in" value={values.audit.read_detail} onChange={(e) => set('audit', 'read_detail', e.target.value as 'full' | 'summary' | 'sample')}>
                            <option value="full">full</option>
                            <option value="sample">sample 1/N</option>
                            <option value="summary">summary</option>
                          </select>
                        </Field>
                        <a className="sm" href={buildHash('/audit', { tab: 'retention' })} style={{ display: 'inline-block', marginTop: 12 }}>
                          Retention per record type →
                        </a>
                      </>
                    );
                  })()}
                </section>

                {/* Quotas & client policy */}
                <section className="card" id="set-quotas" ref={sec('quotas')}>
                  <h3>Quotas &amp; client policy</h3>
                  <Field id="tq" label="Tenant memory quota" lock="Set per tenant by Super Admin in Tenants">
                    <input id="tq" className="in" value={values.quotas?.tenant_memory_quota ? fmtInt(values.quotas.tenant_memory_quota) : 'No limit'} readOnly disabled />
                  </Field>
                  <Field id="pq" label="Default project quota" hint="Records per new project; leave empty for no limit">
                    <input
                      id="pq"
                      className="in"
                      inputMode="numeric"
                      value={values.quotas?.default_project_quota ? fmtInt(values.quotas.default_project_quota) : ''}
                      placeholder="No limit"
                      onChange={(e) => setQuota('default_project_quota', e.target.value.trim() ? num(e.target.value, 0) : null)}
                    />
                  </Field>
                  <Field id="cmth" label="Allowed connection methods">
                    <select id="cmth" className="in" value={values.quotas?.connection_methods ?? 'oauth_keys'} onChange={(e) => setQuota('connection_methods', e.target.value as TenantQuotas['connection_methods'])}>
                      <option value="oauth_keys">OAuth 2.1 + API keys</option>
                      <option value="oauth">OAuth 2.1 only</option>
                    </select>
                  </Field>
                  <div className="set-two">
                    <Field id="kl" label={`Key lifetime · max ${values.quotas?.key_lifetime_max_days ?? 365} d`}>
                      <input
                        id="kl"
                        className="in"
                        type="number"
                        min={1}
                        max={values.quotas?.key_lifetime_max_days ?? 365}
                        value={values.quotas?.key_lifetime_days ?? 90}
                        onChange={(e) => setQuota('key_lifetime_days', num(e.target.value, 90))}
                      />
                    </Field>
                    <Field id="rs" label="Revoke stale after · days">
                      <input id="rs" className="in" type="number" min={7} value={values.quotas?.revoke_stale_days ?? 60} onChange={(e) => setQuota('revoke_stale_days', num(e.target.value, 60))} />
                    </Field>
                  </div>
                </section>

                {/* Models */}
                <section className="card" id="set-models" ref={sec('models')}>
                  <h3>Models</h3>
                  <dl className="set-kv">
                    {(['embedding', 'reranker'] as const).map((k) => {
                      const m = data.models[k];
                      return (
                        <React.Fragment key={k}>
                          <dt>{k === 'embedding' ? 'Embedding' : 'Reranker'}</dt>
                          <dd>
                            {m.detail ?? m.name ?? (m.url ? 'configured' : 'not configured')} <span className="sm muted">· platform managed</span>
                            <div className="sm">
                              <span className={m.status === 'healthy' ? 'ok' : m.status === 'degraded' ? 'warn' : m.status === 'down' ? 'err' : 'muted'}>
                                ●{' '}
                                {m.status === 'healthy'
                                  ? `Ready · ${m.latency_ms} ms`
                                  : m.status === 'degraded'
                                    ? `Degraded · ${m.latency_ms} ms`
                                    : m.status === 'down'
                                      ? 'Not responding'
                                      : 'Not configured'}
                              </span>
                            </div>
                          </dd>
                        </React.Fragment>
                      );
                    })}
                  </dl>
                  <p className="sm muted" style={{ marginTop: 14 }}>
                    Model changes are made by Super Admins in Global policies &amp; models.
                  </p>
                </section>
              </div>
              {data.meta.updated_at && (
                <p className="sm muted" style={{ margin: 0 }}>
                  Last saved {fmtRelative(data.meta.updated_at).toLowerCase()}
                  {data.meta.updated_by ? ` by ${data.meta.updated_by}` : ''} · every change is recorded as an administrative event.
                </p>
              )}
              {dirty && (
                <div className="savebar" role="status">
                  <span style={{ flex: 1 }}>You have unsaved changes.</span>
                  <button type="button" className="btn bg" onClick={() => setValues(structuredClone(data.values))}>
                    Discard
                  </button>
                  <button type="button" className="btn bp" disabled={busy} onClick={save}>
                    Save changes
                  </button>
                </div>
              )}
            </>
          )
        )}
      </div>
    </>
  );
};

const Field: React.FC<{ id: string; label: string; hint?: string; lock?: string; children: React.ReactNode }> = ({ id, label, hint, lock, children }) => (
  <div className="f set-f">
    <label htmlFor={id}>{label}</label>
    {children}
    {lock ? (
      <span className="hint set-lock">
        <Icon.Lock size={12} /> {lock}
      </span>
    ) : (
      hint && <span className="hint">{hint}</span>
    )}
  </div>
);

const Check: React.FC<{ label: string; checked: boolean; disabled?: boolean; hint?: string; onChange?: (v: boolean) => void }> = ({ label, checked, disabled, hint, onChange }) => (
  <label className={`set-check ${disabled ? 'dis' : ''}`}>
    <span>
      {label}
      {hint && <span className="hint">{hint}</span>}
    </span>
    <input type="checkbox" checked={checked} disabled={disabled || !onChange} onChange={(e) => onChange?.(e.target.checked)} />
  </label>
);

const Locked: React.FC<{ label: string; value: string; lockValue?: boolean }> = ({ label, value, lockValue }) => (
  <div className="set-check dis">
    <span style={{ display: 'inline-flex', flexDirection: 'row', gap: 6, alignItems: 'center' }}>
      {!lockValue && <Icon.Lock size={13} />}
      {label}
    </span>
    <span className="sm" style={{ display: 'inline-flex', gap: 6, alignItems: 'center', whiteSpace: 'nowrap' }}>
      {lockValue && <Icon.Lock size={13} />}
      {value}
    </span>
  </div>
);

export default Settings;
