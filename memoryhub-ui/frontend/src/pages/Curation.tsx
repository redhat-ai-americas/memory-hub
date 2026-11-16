import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Modal, SkLines, SkTable, Switch, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { CurationPolicy, CurationRule, RuleTestResult } from '@/types';
import { errorMessage, fmtInt, fmtRelative, SCOPE_ORDER, truncate } from '@/utils/format';
import { ConfirmModal } from './common';
import { LockIcon } from './MemoryGraph';

const ACTIONS = ['quarantine', 'flag', 'block', 'reject_with_pointer', 'decay_weight', 'merge'];
const ACTION_LABEL: Record<string, string> = {
  block: 'Block',
  quarantine: 'Quarantine',
  reject_with_pointer: 'Route to project',
  flag: 'Flag for review',
  decay_weight: 'Decay weight',
  merge: 'Suggest merge',
};
const actionLabel = (a: string) => ACTION_LABEL[a] ?? a;
const APPLIES: Record<string, string> = {
  '': 'All scopes',
  user: 'Personal scope · all users',
  project: 'Project scope',
  campaign: 'Campaign scope',
  role: 'Role scope',
  organizational: 'Organizational scope',
  enterprise: 'Enterprise scope',
};
const LAYER: Record<string, { cls: string; label: string }> = {
  system: { cls: 'g', label: 'System' },
  organizational: { cls: 'pur', label: 'Organization' },
  user: { cls: 'blue', label: 'User' },
};

const describeConfig = (r: CurationRule): string => {
  const c = r.config || {};
  if (typeof c.pattern_set === 'string') return c.pattern_set === 'secrets' ? 'AWS, GCP, Azure, GitHub tokens; private keys' : c.pattern_set === 'pii' ? 'Email, phone, SSN, card numbers' : `${c.pattern_set} patterns`;
  if (typeof c.threshold === 'number') return `Cosine ≥ ${c.threshold}`;
  if (Array.isArray(c.similarity_range)) return `Cosine ${c.similarity_range.join('–')}`;
  return '';
};

interface Draft {
  id?: string;
  name: string;
  description: string;
  tier: 'regex' | 'embedding';
  pattern: string;
  pattern_set: string;
  reference: string;
  threshold: number;
  action: string;
  scope_filter: string;
  layer: string;
  owner_id: string;
  priority: number;
  enabled: boolean;
  config: Record<string, unknown>;
}

const toDraft = (r?: CurationRule): Draft => {
  const c = (r?.config ?? {}) as Record<string, unknown>;
  return {
    id: r?.id,
    name: r?.name ?? '',
    description: r?.description ?? '',
    tier: r?.tier === 'embedding' ? 'embedding' : 'regex',
    pattern: typeof c.pattern === 'string' ? c.pattern : '',
    pattern_set: typeof c.pattern_set === 'string' ? c.pattern_set : '',
    reference: typeof c.reference === 'string' ? c.reference : '',
    threshold: typeof c.threshold === 'number' ? c.threshold : 0.92,
    action: r?.action ?? 'flag',
    scope_filter: r?.scope_filter ?? '',
    layer: r?.layer ?? 'organizational',
    owner_id: r?.owner_id ?? '',
    priority: r?.priority ?? 100,
    enabled: r?.enabled ?? true,
    config: c,
  };
};

const Curation: React.FC<{ route: HashRoute }> = ({ route }) => {
  const toast = useToast();
  const { role } = useApp();
  const isUser = role === 'user';
  const layer = route.params.get('layer') || 'all';
  const selectedId = route.params.get('rule');
  const rules = useApi(() => api.rules(), []);
  const matches = useApi(() => (isUser ? Promise.resolve(null as never) : api.ruleMatches()), [isUser]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [scanning, setScanning] = useState(false);
  const [deleting, setDeleting] = useState<CurationRule | null>(null);

  const all = rules.data ?? [];
  const rows = all.filter((r) => layer === 'all' || r.layer === layer);
  const count = (l: string) => all.filter((r) => r.layer === l).length;

  useEffect(() => {
    if (!rules.data) return;
    if (selectedId === 'new') setDraft((d) => (d && !d.id ? d : toDraft()));
    else if (selectedId) {
      const r = rules.data.find((x) => x.id === selectedId);
      if (r) setDraft(toDraft(r));
    } else setDraft(null);
  }, [selectedId, rules.data]);

  const select = (id: string | undefined) => {
    const next = new URLSearchParams(route.params);
    if (id) next.set('rule', id);
    else next.delete('rule');
    navigate('/curation', next, { replace: true });
  };

  const scan = async () => {
    setScanning(true);
    try {
      const res = await api.batchScan();
      const hits = Object.values(res.matches).reduce((a, b) => a + b, 0);
      toast(`Scanned ${fmtInt(res.scanned)} memories with ${res.rules} regex rules · ${hits} match${hits === 1 ? '' : 'es'}.`);
      matches.reload();
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setScanning(false);
    }
  };

  return (
    <>
      <PageHeader
        title={isUser ? 'My curation rules' : 'Curation & compaction'}
        crumbs={[{ label: isUser ? 'My curation rules' : 'Curation & compaction' }]}
        description={
          isUser
            ? 'Personal rules check what your agents write to your memories — block secrets, quarantine sensitive text or flag near-duplicates. System and organization rules always apply and are shown read-only.'
            : 'Rules run inline on every write and again in curator batch scans. Lower priority numbers run first; the first blocking match wins.'
        }
        actions={
          <>
            {!isUser && (
              <button type="button" className="btn bs" disabled={scanning || all.length === 0} onClick={scan}>
                {scanning ? 'Scanning…' : 'Run batch scan now'}
              </button>
            )}
            <button type="button" className="btn bp" onClick={() => select('new')}>
              Create rule
            </button>
          </>
        }
        tabs={
          <Tabs
            label="Rule layer"
            value={layer}
            onChange={(l) => navigate('/curation', l === 'all' ? undefined : { layer: l }, { replace: true })}
            tabs={[
              { value: 'all', label: 'All rules', count: rules.data ? all.length : null },
              { value: 'system', label: 'System', count: rules.data ? count('system') : null },
              { value: 'organizational', label: 'Organization', count: rules.data ? count('organizational') : null },
              { value: 'user', label: 'User', count: rules.data ? count('user') : null },
            ]}
          />
        }
      />
      <div className="body">
        <div className="row-wrap">
          <div className="col-main">
            <section className="card" style={{ padding: 0 }}>
              {rules.error && !rules.data ? (
                <ErrorState error={rules.error} onRetry={rules.reload} />
              ) : rules.loading && !rules.data ? (
                <SkTable rows={8} cols={7} />
              ) : rows.length === 0 ? (
                <Empty
                  title={layer === 'all' ? 'No curation rules' : `No ${LAYER[layer]?.label.toLowerCase() ?? layer} rules`}
                  action={
                    <button type="button" className="btn bp" onClick={() => select('new')}>
                      Create rule
                    </button>
                  }
                >
                  The MCP server seeds the system rules (secrets, PII, duplicates) on its first write for this tenant.
                </Empty>
              ) : (
                <div className="scroll">
                  <table className="tbl mid" style={{ minWidth: 640 }}>
                    <thead>
                      <tr>
                        <th style={{ minWidth: 150 }}>Rule</th>
                        <th>Layer</th>
                        <th>Precedence</th>
                        <th>Protected</th>
                        <th>Type</th>
                        <th>Action</th>
                        <th style={{ whiteSpace: "nowrap" }}>Hits · 7 d</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => {
                        const detail = describeConfig(r);
                        return (
                          <tr key={r.id} className={`clickable ${draft?.id === r.id ? 'is-sel' : ''}`} onClick={() => select(draft?.id === r.id ? undefined : r.id)}>
                            <td>
                              <a
                                href={`#/curation?rule=${r.id}`}
                                style={{ fontWeight: 600, textDecoration: 'none' }}
                                onClick={(e) => {
                                  e.preventDefault();
                                  select(draft?.id === r.id ? undefined : r.id);
                                }}
                              >
                                {r.name}
                              </a>
                              {!r.enabled && <span className="lbl g" style={{ marginLeft: 6 }}>off</span>}
                              <div className="sm muted">{r.description || detail || '—'}</div>
                              {typeof r.config?.pattern === 'string' && <div className="sm mono muted">{truncate(r.config.pattern as string, 40)}</div>}
                            </td>
                            <td>
                              <span className={`lbl ${LAYER[r.layer]?.cls ?? 'g'}`}>
                                {LAYER[r.layer]?.label ?? r.layer}
                                {r.layer === 'user' && r.owner_id ? ` · ${r.owner_id}` : ''}
                              </span>
                            </td>
                            <td className="mono">{r.priority}</td>
                            <td className="sm">
                              {r.layer === 'system' ? (
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                  <LockIcon size={12} /> yes
                                </span>
                              ) : (
                                <span className="muted">no</span>
                              )}
                            </td>
                            <td className="mono sm">{r.tier}</td>
                            <td className="sm">{actionLabel(r.action)}</td>
                            <td title={matches.data?.available ? undefined : 'The MCP server does not record rule names in audit events yet'}>
                              {matches.data?.available ? fmtInt(matches.data.counts[r.name] ?? 0) : '—'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            {draft ? (
              <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <RuleEditor
                  key={draft.id ?? 'new'}
                  initial={draft}
                  rule={all.find((r) => r.id === draft.id)}
                  onClose={() => select(undefined)}
                  onDelete={(r) => setDeleting(r)}
                  onSaved={(saved) => {
                    rules.reload();
                    select(saved.id);
                  }}
                />
              </section>
            ) : (
              rows.length > 0 && <p className="sm muted" style={{ margin: '-8px 0 0' }}>Click a rule to edit it below.</p>
            )}
          </div>

          <aside className="col-side" style={{ flex: '1 1 320px', maxWidth: 380 }}>
            <div className="card">
              <h2 data-h="3" style={{ marginBottom: 6 }}>How rules are layered</h2>
              <div className="layer">
                <span className="num">1</span>
                <div>
                  <b>System</b> <span className="muted">— shipped defaults: secrets and PII scanning, near-duplicate detection. Can be tuned, not deleted.</span>
                </div>
              </div>
              <div className="layer">
                <span className="num">2</span>
                <div>
                  <b>Organization</b>{' '}
                  <span className="muted">— policies set by administrators, such as “no source code in memories”. Apply to every scope they filter on.</span>
                </div>
              </div>
              <div className="layer" style={{ borderBottom: 0 }}>
                <span className="num">3</span>
                <div>
                  <b>User</b>{' '}
                  <span className="muted">
                    — personal rules created through <span className="mono">set_curation_rule</span>; only affect that user’s writes.
                  </span>
                </div>
              </div>
            </div>
            {!isUser && <PolicyCard />}
          </aside>
        </div>
      </div>
      {deleting && (
        <ConfirmModal
          title={`Delete ${deleting.name}?`}
          confirmLabel="Delete rule"
          danger
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await api.deleteRule(deleting.id);
            toast('Rule deleted. Its version history is kept.');
            select(undefined);
            rules.reload();
          }}
        >
          New writes are no longer checked against <b>{deleting.name}</b>. Earlier versions of the rule stay in the database as an audit trail.
        </ConfirmModal>
      )}
    </>
  );
};

const RuleEditor: React.FC<{
  initial: Draft;
  rule?: CurationRule;
  onClose: () => void;
  onSaved: (r: CurationRule) => void;
  onDelete: (r: CurationRule) => void;
}> = ({ initial, rule, onClose, onSaved, onDelete }) => {
  const toast = useToast();
  const { me, role } = useApp();
  const isUser = role === 'user';
  const readOnly = isUser && !!rule && !(rule.layer === 'user' && rule.owner_id === me?.username);
  const [d, setD] = useState<Draft>(isUser && !rule ? { ...initial, layer: 'user', owner_id: me?.username ?? '' } : initial);
  const [sample, setSample] = useState('');
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<RuleTestResult | null>(null);
  const [testErr, setTestErr] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (!sample.trim()) {
      setTest(null);
      setTestErr(null);
      return undefined;
    }
    const t = window.setTimeout(() => {
      api
        .testRule({
          tier: d.tier,
          sample,
          pattern: d.pattern || undefined,
          pattern_set: d.pattern_set || undefined,
          reference: d.reference || undefined,
          threshold: d.threshold,
          action: d.action,
        })
        .then((r) => {
          setTest(r);
          setTestErr(null);
        })
        .catch((e) => {
          setTest(null);
          setTestErr(errorMessage(e));
        });
    }, 300);
    return () => window.clearTimeout(t);
  }, [sample, d.tier, d.pattern, d.pattern_set, d.reference, d.threshold, d.action]);

  const save = async () => {
    setBusy(true);
    setErr(null);
    const config: Record<string, unknown> = { ...d.config };
    if (d.tier === 'regex') {
      delete config.reference;
      if (d.pattern_set) config.pattern_set = d.pattern_set;
      else {
        delete config.pattern_set;
        config.pattern = d.pattern;
      }
    } else {
      delete config.pattern;
      delete config.pattern_set;
      config.threshold = d.threshold;
      if (d.reference) config.reference = d.reference;
    }
    const payload = {
      name: d.name.trim(),
      description: d.description.trim() || null,
      tier: d.tier,
      config,
      action: d.action,
      scope_filter: d.scope_filter || null,
      layer: d.layer,
      owner_id: d.layer === 'user' ? d.owner_id || me?.username || null : null,
      priority: d.priority,
      enabled: d.enabled,
    };
    try {
      const saved = d.id ? await api.updateRule(d.id, { ...payload, edited_by: me?.username }) : await api.createRule(payload as never);
      toast(d.id ? `Saved ${saved.name} as v${saved.version}.` : `Rule ${saved.name} created.`);
      onSaved(saved);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const firstMatch = test?.matches?.[0];
  const lay = LAYER[d.layer];
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div>
          <h2 data-h="3" style={{ fontSize: 18 }}>{d.id ? `Edit rule · ${rule?.name ?? d.name}` : 'Create rule'}</h2>
          {rule && (
            <span className="sm muted">
              v{rule.version}
              {rule.edited_by ? ` · edited by ${rule.edited_by}` : ''} · {fmtRelative(rule.updated_at)}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {lay && <span className={`lbl ${lay.cls}`}>{lay.label}</span>}
          <button type="button" className="btn bl" aria-label="Close editor" onClick={onClose}>
            ✕
          </button>
        </div>
      </div>
      {readOnly && (
        <div className="alert">
          This is a {d.layer === 'system' ? 'system' : d.layer === 'organizational' ? 'organization' : 'another person’s'} rule. It applies to your memories too; only
          platform admins can change it.
        </div>
      )}
      <div className="rule-edit-grid">
        <div className="f">
          <label htmlFor="rn">Name</label>
          <input id="rn" className="in" value={d.name} onChange={(e) => set('name', e.target.value)} />
        </div>
        <div className="f">
          <label htmlFor="pr">Precedence</label>
          <input id="pr" className="in" type="number" value={d.priority} onChange={(e) => set('priority', Number(e.target.value))} />
        </div>
        <div className="f">
          <label htmlFor="tp">Type</label>
          <select id="tp" className="in" value={d.tier} onChange={(e) => set('tier', e.target.value as Draft['tier'])}>
            <option value="regex">regex</option>
            <option value="embedding">embedding</option>
          </select>
        </div>
        {d.tier === 'regex' ? (
          d.pattern_set ? (
            <div className="f">
              <label>Pattern set</label>
              <div className="sm" style={{ padding: '8px 0' }}>
                Built-in <span className="mono">{d.pattern_set}</span> scanner.{' '}
                <button type="button" className="link-btn" onClick={() => set('pattern_set', '')}>
                  Use a custom pattern
                </button>
              </div>
            </div>
          ) : (
            <div className="f">
              <label htmlFor="pt">Pattern</label>
              <input id="pt" className="in mono" value={d.pattern} onChange={(e) => set('pattern', e.target.value)} placeholder="(def |class |import )" />
            </div>
          )
        ) : (
          <div className="f">
            <label htmlFor="th">Similarity threshold</label>
            <input
              id="th"
              className="in"
              type="number"
              min={0.5}
              max={1}
              step={0.01}
              value={d.threshold}
              onChange={(e) => set('threshold', Math.min(1, Math.max(0, Number(e.target.value))))}
            />
          </div>
        )}
        <div className="f">
          <label htmlFor="ac">Action</label>
          <select id="ac" className="in" value={d.action} onChange={(e) => set('action', e.target.value)}>
            {[...new Set([...ACTIONS, d.action])].map((a) => (
              <option key={a} value={a}>
                {actionLabel(a)}
              </option>
            ))}
          </select>
        </div>
        <div className="f">
          <label htmlFor="sf">Applies to</label>
          <select id="sf" className="in" value={d.scope_filter} onChange={(e) => set('scope_filter', e.target.value)}>
            <option value="">{APPLIES['']}</option>
            {SCOPE_ORDER.map((sc) => (
              <option key={sc} value={sc}>
                {APPLIES[sc] ?? sc}
              </option>
            ))}
            {d.scope_filter && !SCOPE_ORDER.includes(d.scope_filter as never) && <option value={d.scope_filter}>{d.scope_filter}</option>}
          </select>
        </div>
        {d.tier === 'embedding' && (
          <div className="f" style={{ gridColumn: '1 / -1' }}>
            <label htmlFor="ref">Reference text</label>
            <textarea id="ref" className="in" style={{ minHeight: 56 }} value={d.reference} onChange={(e) => set('reference', e.target.value)} placeholder="weekly sync notes" />
          </div>
        )}
        <div className="f" style={{ gridColumn: '1 / -1' }}>
          <label htmlFor="rdsc">Description</label>
          <input id="rdsc" className="in" value={d.description} onChange={(e) => set('description', e.target.value)} />
        </div>
        {!d.id && !isUser && (
          <div className="f">
            <label htmlFor="ly">Layer</label>
            <select id="ly" className="in" value={d.layer} onChange={(e) => set('layer', e.target.value)}>
              <option value="organizational">Organization</option>
              <option value="user">User</option>
              <option value="system">System</option>
            </select>
          </div>
        )}
        <div className="f" style={{ justifyContent: 'flex-end' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14, minHeight: 38 }}>
            <Switch on={d.enabled} label="Rule enabled" onChange={(v) => set('enabled', v)} />
            <span>{d.enabled ? 'Enabled' : 'Disabled'}</span>
          </div>
        </div>
      </div>
      {testing && (
        <div style={{ border: '1px solid #d2d2d2', borderRadius: 12, padding: 14 }}>
          <div className="f">
            <label htmlFor="tt">Sample text</label>
            <textarea id="tt" className="in mono" style={{ minHeight: 70 }} value={sample} onChange={(e) => setSample(e.target.value)} placeholder="Paste text an agent might write…" autoFocus />
          </div>
          {test && (
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 10, background: test.matched ? '#fff0dd' : '#f3faf0', borderRadius: 8, padding: '8px 12px', fontSize: 14, flexWrap: 'wrap' }}>
              <span className={`lbl ${test.matched ? 'org' : 'grn'}`}>{test.matched ? 'match' : 'no match'}</span>
              {test.matched ? (
                <span>
                  Would <b>{actionLabel(test.action)}</b>
                  {firstMatch?.text !== undefined && (
                    <>
                      {' '}
                      — matched <span className="mono">{firstMatch.text}</span> at col {firstMatch.col}
                      {firstMatch.line && firstMatch.line > 1 ? `, line ${firstMatch.line}` : ''}
                    </>
                  )}
                  {firstMatch?.name && <> — {firstMatch.detail}</>}
                  {test.score !== undefined && <> — cosine {test.score.toFixed(2)} ≥ {test.threshold}</>}
                </span>
              ) : (
                <span>Would allow{test.score !== undefined ? ` — cosine ${test.score.toFixed(2)} < ${test.threshold}` : ''}</span>
              )}
            </div>
          )}
          {testErr && <div className="sm err" style={{ marginTop: 8 }}>{testErr}</div>}
        </div>
      )}
      {err && <div className="alert err-a">{err}</div>}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <button type="button" className="btn bp" disabled={readOnly || busy || !d.name.trim() || (d.tier === 'regex' && !d.pattern && !d.pattern_set)} onClick={save}>
          {busy ? 'Saving…' : 'Save · audited'}
        </button>
        <button type="button" className={`btn ${testing ? 'bg' : 'bs'}`} onClick={() => setTesting((t) => !t)}>
          {testing ? 'Hide test' : 'Test on sample'}
        </button>
        {rule && rule.layer !== 'system' && !readOnly && (
          <button type="button" className="link-btn" style={{ color: '#c9190b', textDecoration: 'none', marginLeft: 6 }} onClick={() => onDelete(rule)}>
            Delete
          </button>
        )}
      </div>
    </>
  );
};

const POLICY_DEFAULTS: CurationPolicy = {
  dreaming_schedule: 'Daily 06:00',
  age_trigger_days: 90,
  size_trigger_records: 5000,
  auto_quarantine_score: 0.9,
  compaction: 'suggest',
  compaction_preview: true,
  keep_provenance: 'always',
  org_compaction_approval: true,
};
const COMPACTION: Record<CurationPolicy['compaction'], string> = { off: 'Off', suggest: 'Suggest', auto: 'Automatic' };
const PROVENANCE: Record<CurationPolicy['keep_provenance'], string> = { always: 'Always', '90d': '90 days', never: 'Not kept' };

/** Tenant-wide dreaming and compaction policy, summarised next to the curation rules. */
const PolicyCard: React.FC = () => {
  const toast = useToast();
  const settings = useApi(() => api.settings(), []);
  const [editing, setEditing] = useState(false);
  const saved = settings.data?.values.curation;
  const p: CurationPolicy = { ...POLICY_DEFAULTS, ...(saved ?? {}) };
  const save = async (next: CurationPolicy) => {
    try {
      await api.saveSettings({ curation: next });
      toast('Dreaming & compaction policy saved.');
      setEditing(false);
      settings.reload();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
  };
  return (
    <section className="card">
      <div className="card-head">
        <h2 data-h="3">Dreaming &amp; compaction policy</h2>
        <button type="button" className="link-btn" style={{ textDecoration: 'none' }} onClick={() => setEditing(true)} disabled={!settings.data}>
          Edit
        </button>
      </div>
      {settings.loading && !settings.data ? (
        <SkLines lines={6} />
      ) : (
        <dl className="policy-kv">
          <dt>Dreaming schedule</dt>
          <dd>{p.dreaming_schedule}</dd>
          <dt>Age trigger</dt>
          <dd>{p.age_trigger_days} days unused</dd>
          <dt>Size trigger</dt>
          <dd>&gt; {fmtInt(p.size_trigger_records)} records in a project</dd>
          <dt>Auto-quarantine threshold</dt>
          <dd>Policy score ≥ {p.auto_quarantine_score.toFixed(2)}</dd>
          <dt>Compaction</dt>
          <dd>
            {COMPACTION[p.compaction]}
            {p.compaction !== 'off' && p.compaction_preview ? ' · preview required' : ''}
          </dd>
          <dt>Keep provenance &amp; history</dt>
          <dd>{PROVENANCE[p.keep_provenance]}</dd>
          <dt>Approval for org compaction</dt>
          <dd>{p.org_compaction_approval ? 'Required' : 'Not required'}</dd>
        </dl>
      )}
      <p className="sm muted" style={{ marginTop: 14 }}>
        For personal records you only see an aggregate
        {p.personal_suggestions ? ` (${fmtInt(p.personal_suggestions.suggestions)} suggestions sent to ${fmtInt(p.personal_suggestions.owners)} owners)` : ''}; the decision stays with the owner or an
        addressed incident process.
      </p>
      {settings.data && !saved && <p className="sm muted" style={{ marginTop: 6 }}>Showing defaults — no tenant policy saved yet.</p>}
      {editing && <PolicyModal initial={p} onClose={() => setEditing(false)} onSave={save} />}
    </section>
  );
};

const PolicyModal: React.FC<{ initial: CurationPolicy; onClose: () => void; onSave: (p: CurationPolicy) => Promise<void> }> = ({ initial, onClose, onSave }) => {
  const [p, setP] = useState(initial);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof CurationPolicy>(k: K, v: CurationPolicy[K]) => setP((x) => ({ ...x, [k]: v }));
  return (
    <Modal
      title="Dreaming & compaction policy"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn bp"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              await onSave(p);
              setBusy(false);
            }}
          >
            {busy ? 'Saving…' : 'Save · audited'}
          </button>
        </>
      }
    >
      <div className="rule-edit-grid" style={{ marginTop: 12 }}>
        <div className="f">
          <label htmlFor="pds">Dreaming schedule</label>
          <select id="pds" className="in" value={p.dreaming_schedule} onChange={(e) => set('dreaming_schedule', e.target.value)}>
            {[...new Set(['Daily 02:00', 'Daily 06:00', 'Weekly · Sunday 03:00', 'Off', p.dreaming_schedule])].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </div>
        <div className="f">
          <label htmlFor="pag">Age trigger · days unused</label>
          <input id="pag" className="in" type="number" min={1} value={p.age_trigger_days} onChange={(e) => set('age_trigger_days', Number(e.target.value))} />
        </div>
        <div className="f">
          <label htmlFor="psz">Size trigger · records in a project</label>
          <input id="psz" className="in" type="number" min={100} step={100} value={p.size_trigger_records} onChange={(e) => set('size_trigger_records', Number(e.target.value))} />
        </div>
        <div className="f">
          <label htmlFor="paq">Auto-quarantine · policy score ≥</label>
          <input id="paq" className="in" type="number" min={0.5} max={1} step={0.01} value={p.auto_quarantine_score} onChange={(e) => set('auto_quarantine_score', Number(e.target.value))} />
        </div>
        <div className="f">
          <label htmlFor="pcm">Compaction</label>
          <select id="pcm" className="in" value={p.compaction} onChange={(e) => set('compaction', e.target.value as CurationPolicy['compaction'])}>
            <option value="off">Off</option>
            <option value="suggest">Suggest</option>
            <option value="auto">Automatic</option>
          </select>
        </div>
        <div className="f">
          <label htmlFor="ppv">Keep provenance &amp; history</label>
          <select id="ppv" className="in" value={p.keep_provenance} onChange={(e) => set('keep_provenance', e.target.value as CurationPolicy['keep_provenance'])}>
            <option value="always">Always</option>
            <option value="90d">90 days</option>
            <option value="never">Not kept</option>
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14 }}>
          <Switch on={p.compaction_preview} label="Preview required" onChange={(v) => set('compaction_preview', v)} />
          Preview required before compaction
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14 }}>
          <Switch on={p.org_compaction_approval} label="Approval for org compaction" onChange={(v) => set('org_compaction_approval', v)} />
          Approval for org compaction
        </div>
      </div>
    </Modal>
  );
};

export default Curation;
