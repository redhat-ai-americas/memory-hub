import React, { useEffect, useRef, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader } from '@/components/Shell';
import { ErrorState, Seg, SkLines, Status, Switch, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import type { SettingsResponse, TenantSettingsValues } from '@/types';
import { errorMessage, fmtRelative } from '@/utils/format';

const SECTIONS = [
  { id: 'retrieval', label: 'Retrieval' },
  { id: 'models', label: 'Models' },
  { id: 'governance', label: 'Isolation & governance' },
  { id: 'audit', label: 'Audit & retention' },
  { id: 'mcp', label: 'MCP endpoint' },
  { id: 'tenant', label: 'Tenant' },
];

const Settings: React.FC = () => {
  const toast = useToast();
  const { data, error, loading, reload, setData } = useApi<SettingsResponse>(() => api.settings(), []);
  const [values, setValues] = useState<TenantSettingsValues | null>(null);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState('retrieval');
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
      { rootMargin: '-80px 0px -60% 0px' },
    );
    Object.values(refs.current).forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [values !== null]);

  const dirty = data && values ? JSON.stringify(data.values) !== JSON.stringify(values) : false;
  const set = <S extends keyof TenantSettingsValues, K extends keyof TenantSettingsValues[S]>(section: S, key: K, value: TenantSettingsValues[S][K]) =>
    setValues((v) => (v ? { ...v, [section]: { ...v[section], [key]: value } } : v));

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

  const num = (v: string, fallback: number) => (v.trim() === '' || Number.isNaN(Number(v)) ? fallback : Number(v));
  const sec = (id: string) => (el: HTMLElement | null) => {
    refs.current[id] = el;
  };

  return (
    <>
      <PageHeader
        title="Settings"
        description={
          <>
            Tenant-wide defaults. Agents can narrow these per request; project <span className="mono">.memoryhub.yaml</span> files override retrieval defaults.
          </>
        }
        actions={
          <>
            <button type="button" className="btn bg" disabled={!dirty || busy} onClick={() => data && setValues(structuredClone(data.values))}>
              Discard
            </button>
            <button type="button" className="btn bp" disabled={!dirty || busy} onClick={save}>
              {busy ? 'Saving…' : 'Save changes'}
            </button>
          </>
        }
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
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, alignItems: 'flex-start' }}>
              <nav className="jl" aria-label="Settings sections">
                {SECTIONS.map((s) => (
                  <a
                    key={s.id}
                    href={`#set-${s.id}`}
                    className={active === s.id ? 'on' : ''}
                    onClick={(e) => {
                      e.preventDefault();
                      refs.current[s.id]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                      setActive(s.id);
                    }}
                  >
                    {s.label}
                  </a>
                ))}
                {data.meta.updated_at && (
                  <span className="hint" style={{ padding: '12px 14px 0' }}>
                    Last saved {fmtRelative(data.meta.updated_at).toLowerCase()}
                    {data.meta.updated_by ? ` by ${data.meta.updated_by}` : ''}
                  </span>
                )}
              </nav>
              <div className="col-main" style={{ flex: '999 1 560px' }}>
                <section className="card" id="set-retrieval" ref={sec('retrieval')}>
                  <h3>Retrieval</h3>
                  <p className="sm muted" style={{ margin: 0 }}>
                    Defaults for <span className="mono">search_memory</span> when an agent does not pass a value.
                  </p>
                  <div className="fg">
                    <div className="f">
                      <label htmlFor="mr">Max results</label>
                      <input id="mr" className="in" type="number" min={1} max={50} value={values.retrieval.max_results} onChange={(e) => set('retrieval', 'max_results', num(e.target.value, 10))} />
                      <span className="hint">1 – 50</span>
                    </div>
                    <div className="f">
                      <label htmlFor="tk">Max response tokens</label>
                      <input id="tk" className="in" type="number" min={100} value={values.retrieval.max_response_tokens} onChange={(e) => set('retrieval', 'max_response_tokens', num(e.target.value, 4000))} />
                      <span className="hint">Hard cap on assembled context</span>
                    </div>
                    <div className="f">
                      <label htmlFor="fw">Session focus weight</label>
                      <input id="fw" className="in" type="number" step="0.05" min={0} max={1} value={values.retrieval.session_focus_weight} onChange={(e) => set('retrieval', 'session_focus_weight', num(e.target.value, 0.4))} />
                      <span className="hint">0 ignores focus, 1 ignores the query</span>
                    </div>
                    <div className="f">
                      <label htmlFor="st">Full-content weight threshold</label>
                      <input id="st" className="in" type="number" step="0.05" min={0} max={1} value={values.retrieval.full_content_threshold} onChange={(e) => set('retrieval', 'full_content_threshold', num(e.target.value, 0.8))} />
                      <span className="hint">Below this, results return as stubs</span>
                    </div>
                  </div>
                  <div style={{ marginTop: 14 }}>
                    <Row title="Cross-encoder reranking" hint="Adds ~90 ms; improves precision on ambiguous queries.">
                      <Switch on={values.retrieval.rerank} label="Cross-encoder reranking" onChange={(v) => set('retrieval', 'rerank', v)} />
                    </Row>
                    <Row title="Cache-optimized ordering" hint="Deterministic, epoch-locked order so agents share KV-cache prefixes. Epoch rolls every 6 h.">
                      <Switch on={values.retrieval.cache_optimized_ordering} label="Cache-optimized ordering" onChange={(v) => set('retrieval', 'cache_optimized_ordering', v)} />
                    </Row>
                    <Row title="Real-time push to sessions" hint="Broadcast new memories to sessions whose focus matches.">
                      <Switch on={values.retrieval.realtime_push} label="Real-time push" onChange={(v) => set('retrieval', 'realtime_push', v)} />
                    </Row>
                  </div>
                </section>

                <section className="card" id="set-models" ref={sec('models')}>
                  <h3>Models</h3>
                  <p className="sm muted" style={{ margin: '0 0 14px' }}>
                    Served on-cluster through OpenShift AI model serving. Endpoints are set at deploy time (<span className="mono">MEMORYHUB_EMBEDDING_URL</span>,{' '}
                    <span className="mono">MEMORYHUB_RERANKER_URL</span>).
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {(['embedding', 'reranker'] as const).map((k) => {
                      const m = data.models[k];
                      return (
                        <div className="model" key={k}>
                          <div style={{ flex: 1, minWidth: 220 }}>
                            <b>{k === 'embedding' ? 'Embedding' : 'Reranker'}</b>
                            <div className="mono muted">{m.detail && m.status === 'healthy' ? m.detail : k === 'embedding' ? 'TEI-compatible /embed' : 'TEI-compatible /rerank'}</div>
                          </div>
                          <span className="mono muted" style={{ overflowWrap: 'anywhere' }}>
                            {m.url ?? 'not configured'}
                          </span>
                          <span className={`lbl ${m.status === 'healthy' ? 'grn' : m.status === 'degraded' ? 'ylw' : m.status === 'down' ? 'red' : 'g'}`}>
                            {m.status === 'healthy'
                              ? `Ready · ${m.latency_ms} ms`
                              : m.status === 'degraded'
                                ? `Degraded · ${m.latency_ms} ms`
                                : m.status === 'down'
                                  ? 'Not responding'
                                  : 'Not configured'}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </section>

                <section className="card" id="set-governance" ref={sec('governance')}>
                  <h3>Isolation &amp; governance</h3>
                  <Row title="Project isolation" hint="Project memories are readable only by project members.">
                    <Switch on={values.governance.project_isolation} label="Project isolation" onChange={(v) => set('governance', 'project_isolation', v)} />
                  </Row>
                  <Row title="Role isolation" hint="Role memories are readable only by holders of that OpenShift role.">
                    <Switch on={values.governance.role_isolation} label="Role isolation" onChange={(v) => set('governance', 'role_isolation', v)} />
                  </Row>
                  <Row title="Contradiction revision threshold" hint="Reports needed before the curator prompts a revision.">
                    <input className="in" type="number" min={1} value={values.governance.contradiction_threshold} style={{ width: 80 }} aria-label="Contradiction threshold" onChange={(e) => set('governance', 'contradiction_threshold', num(e.target.value, 5))} />
                  </Row>
                  <Row title="Enterprise approvers required" hint="Requesters can never approve their own proposal.">
                    <input className="in" type="number" min={1} value={values.governance.enterprise_approvers} style={{ width: 80 }} aria-label="Approvers required" onChange={(e) => set('governance', 'enterprise_approvers', num(e.target.value, 1))} />
                  </Row>
                </section>

                <section className="card" id="set-audit" ref={sec('audit')}>
                  <h3>Audit &amp; retention</h3>
                  <Row title="Read operation detail" hint="Writes and governance decisions are always logged in full.">
                    <Seg
                      label="Read detail"
                      value={values.audit.read_detail}
                      onChange={(v) => set('audit', 'read_detail', v)}
                      options={[
                        { value: 'full', label: 'full' },
                        { value: 'summary', label: 'summary' },
                        { value: 'sample', label: 'sample 1/N' },
                      ]}
                    />
                  </Row>
                  <Row title="Full-detail retention" hint="Older partitions are summarised, then archived to MinIO.">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <input className="in" type="number" min={1} value={values.audit.full_retention_days} style={{ width: 90 }} aria-label="Full detail retention in days" onChange={(e) => set('audit', 'full_retention_days', num(e.target.value, 90))} />
                      <span className="sm">days</span>
                    </div>
                  </Row>
                  <Row title="MCP tool profile" hint="Compact exposes 4 action-dispatch tools; full exposes 14 individual tools.">
                    <Seg
                      label="Tool profile"
                      value={values.audit.mcp_profile}
                      onChange={(v) => set('audit', 'mcp_profile', v)}
                      options={[
                        { value: 'compact', label: 'compact' },
                        { value: 'full', label: 'full' },
                      ]}
                    />
                  </Row>
                </section>

                <section className="card" id="set-mcp" ref={sec('mcp')}>
                  <h3>MCP endpoint</h3>
                  <Row title="Public URL" hint="What agents outside the cluster connect to.">
                    <span className="mono" style={{ overflowWrap: 'anywhere' }}>{data.mcp.public_url}</span>
                  </Row>
                  <Row title="In-cluster service" hint="Used by this dashboard for health checks.">
                    <span className="mono" style={{ overflowWrap: 'anywhere' }}>{data.mcp.internal_url}</span>
                  </Row>
                  <Row title="Status" hint="Probed when this page loads.">
                    <span className="hrow" style={{ border: 0, padding: 0 }}>
                      <Status status={data.mcp.status ?? 'not_configured'}>
                        {data.mcp.status === 'healthy' ? 'Healthy' : data.mcp.status === 'degraded' ? 'Degraded' : data.mcp.status === 'down' ? 'Not responding' : 'Not configured'}
                      </Status>
                    </span>
                  </Row>
                </section>

                <section className="card" id="set-tenant" ref={sec('tenant')}>
                  <h3>Tenant</h3>
                  <Row title="Tenant ID" hint="One dashboard deployment serves one tenant (MEMORYHUB_UI_TENANT_ID).">
                    <span className="mono">{data.tenant.tenant_id}</span>
                  </Row>
                  <Row title="Auth service" hint="OAuth 2.1 issuer agents authenticate against.">
                    <span className="mono" style={{ overflowWrap: 'anywhere' }}>{data.tenant.auth_url}</span>
                  </Row>
                </section>
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
              </div>
            </div>
          )
        )}
      </div>
    </>
  );
};

const Row: React.FC<{ title: string; hint: string; children: React.ReactNode }> = ({ title, hint, children }) => (
  <div className="row">
    <div>
      <b style={{ fontSize: 14 }}>{title}</b>
      <div className="hint">{hint}</div>
    </div>
    {children}
  </div>
);

export default Settings;
