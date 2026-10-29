import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, Seg, SkTable, Switch, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { CurationRule, RuleTestResult } from '@/types';
import { errorMessage, fmtInt, fmtRelative, SCOPE_ORDER, scopeMeta } from '@/utils/format';
import { ConfirmModal } from './common';

const ACTIONS = ['quarantine', 'flag', 'block', 'reject_with_pointer', 'decay_weight', 'merge'];
const ACTION_CLS: Record<string, string> = { block: 'red', quarantine: 'org', reject_with_pointer: 'blue', flag: 'ylw', decay_weight: 'g', merge: 'pur' };
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
  const { me, role } = useApp();
  const isUser = role === 'user';
  const own = (r: CurationRule) => !isUser || (r.layer === 'user' && r.owner_id === me?.username);
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

  const toggle = async (r: CurationRule) => {
    try {
      await api.updateRule(r.id, { enabled: !r.enabled, edited_by: me?.username });
      toast(`${r.name} ${r.enabled ? 'disabled' : 'enabled'}.`);
      rules.reload();
    } catch (e) {
      toast(errorMessage(e), 'err');
    }
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
        title={isUser ? 'My curation rules' : 'Curation rules'}
        crumbs={[{ label: isUser ? 'My curation rules' : 'Curation rules' }]}
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
                  <table className="tbl mid" style={{ minWidth: 820 }}>
                    <thead>
                      <tr>
                        <th>Prio</th>
                        <th>Rule</th>
                        <th>Layer</th>
                        <th>Tier</th>
                        <th>Action</th>
                        <th>Scope filter</th>
                        <th>Matches · 7 d</th>
                        <th>Enabled</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.id} className={`clickable ${draft?.id === r.id ? 'is-sel' : ''}`} onClick={() => select(r.id)}>
                          <td className="mono">{r.priority}</td>
                          <td>
                            <a
                              href={`#/curation?rule=${r.id}`}
                              style={{ fontWeight: 600, textDecoration: 'none' }}
                              onClick={(e) => {
                                e.preventDefault();
                                select(r.id);
                              }}
                            >
                              {r.name}
                            </a>
                            <div className="sm muted">{r.description || describeConfig(r) || '—'}</div>
                          </td>
                          <td>
                            <span className={`lbl ${LAYER[r.layer]?.cls ?? 'g'}`}>
                              {LAYER[r.layer]?.label ?? r.layer}
                              {r.layer === 'user' && r.owner_id ? ` · ${r.owner_id}` : ''}
                            </span>
                          </td>
                          <td className="mono">{r.tier}</td>
                          <td>
                            <span className={`lbl ${ACTION_CLS[r.action] ?? 'g'}`}>{r.action}</span>
                          </td>
                          <td className="sm">{r.scope_filter ? r.scope_filter.split(',').map((s) => scopeMeta(s.trim()).label).join(', ') : 'All scopes'}</td>
                          <td title={matches.data?.available ? undefined : 'The MCP server does not record rule names in audit events yet'}>
                            {matches.data?.available ? fmtInt(matches.data.counts[r.name] ?? 0) : '—'}
                          </td>
                          <td onClick={(e) => e.stopPropagation()}>
                            <Switch on={r.enabled} label={`${r.name} enabled`} onChange={own(r) ? () => toggle(r) : undefined} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            <div className="card">
              <h3 style={{ marginBottom: 6 }}>How rules are layered</h3>
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
          </div>

          <aside className="card" style={{ flex: '1 1 380px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {draft ? (
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
            ) : (
              <Empty compact title="Select a rule">
                Pick a rule to tune its pattern, action and scope, and test it against sample text before saving.
              </Empty>
            )}
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
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ fontSize: 18 }}>{d.id ? 'Edit rule' : 'Create rule'}</h3>
        <button type="button" className="btn bl" aria-label="Close editor" onClick={onClose}>
          ✕
        </button>
      </div>
      {rule && (
        <span className="sm muted">
          v{rule.version}
          {rule.edited_by ? ` · edited by ${rule.edited_by}` : ''} · {fmtRelative(rule.updated_at)}
        </span>
      )}
      <div className="f">
        <label htmlFor="rn">Name</label>
        <input id="rn" className="in" value={d.name} onChange={(e) => set('name', e.target.value)} />
      </div>
      <div className="f">
        <label htmlFor="rdsc">Description</label>
        <input id="rdsc" className="in" value={d.description} onChange={(e) => set('description', e.target.value)} />
      </div>
      <div className="f">
        <label>Tier</label>
        <Seg
          label="Tier"
          value={d.tier}
          onChange={(v) => set('tier', v)}
          options={[
            { value: 'regex', label: 'regex' },
            { value: 'embedding', label: 'embedding' },
          ]}
        />
      </div>
      {d.tier === 'regex' ? (
        d.pattern_set ? (
          <div className="f">
            <label>Pattern set</label>
            <div className="br sm">
              Built-in <span className="mono">{d.pattern_set}</span> scanner.{' '}
              <button type="button" className="link-btn" onClick={() => set('pattern_set', '')}>
                Use a custom pattern instead
              </button>
            </div>
          </div>
        ) : (
          <div className="f">
            <label htmlFor="pt">Pattern</label>
            <input id="pt" className="in mono" value={d.pattern} onChange={(e) => set('pattern', e.target.value)} placeholder="(def |class |import )" />
            <span className="sm muted">Python-style regex, evaluated on content and branches.</span>
          </div>
        )
      ) : (
        <>
          <div className="f">
            <label htmlFor="ref">Reference text</label>
            <textarea id="ref" className="in" style={{ minHeight: 60 }} value={d.reference} onChange={(e) => set('reference', e.target.value)} placeholder="weekly sync notes" />
          </div>
          <div className="f">
            <label htmlFor="th">Similarity threshold · {d.threshold.toFixed(2)}</label>
            <input id="th" type="range" min={50} max={100} value={Math.round(d.threshold * 100)} onChange={(e) => set('threshold', Number(e.target.value) / 100)} />
          </div>
        </>
      )}
      <div className="f">
        <label htmlFor="ac">Action</label>
        <select id="ac" className="in" value={d.action} onChange={(e) => set('action', e.target.value)}>
          {[...new Set([...ACTIONS, d.action])].map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div className="f">
          <label htmlFor="sf">Scope filter</label>
          <select id="sf" className="in" value={d.scope_filter} onChange={(e) => set('scope_filter', e.target.value)}>
            <option value="">all scopes</option>
            {SCOPE_ORDER.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
            {d.scope_filter && !SCOPE_ORDER.includes(d.scope_filter as never) && <option value={d.scope_filter}>{d.scope_filter}</option>}
          </select>
        </div>
        <div className="f">
          <label htmlFor="pr">Priority</label>
          <input id="pr" className="in" type="number" value={d.priority} onChange={(e) => set('priority', Number(e.target.value))} />
        </div>
      </div>
      {readOnly && (
        <div className="alert">
          This is a {d.layer === 'system' ? 'system' : d.layer === 'organizational' ? 'organization' : 'another person’s'} rule. It applies to your memories too; only
          platform admins can change it.
        </div>
      )}
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
      <div style={{ border: '1px solid #d2d2d2', borderRadius: 12, padding: 14 }}>
        <div className="f">
          <label htmlFor="tt">Test against sample text</label>
          <textarea id="tt" className="in mono" style={{ minHeight: 70 }} value={sample} onChange={(e) => setSample(e.target.value)} placeholder="Paste text an agent might write…" />
        </div>
        {test && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 10, background: test.matched ? '#fff0dd' : '#f3faf0', borderRadius: 8, padding: '8px 12px', fontSize: 14, flexWrap: 'wrap' }}>
            <span className={`lbl ${test.matched ? 'org' : 'grn'}`}>{test.matched ? 'match' : 'no match'}</span>
            {test.matched ? (
              <span>
                Would <b>{test.action}</b>
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
              <span>
                Would allow{test.score !== undefined ? ` — cosine ${test.score.toFixed(2)} < ${test.threshold}` : ''}
              </span>
            )}
          </div>
        )}
        {testErr && <div className="sm err" style={{ marginTop: 8 }}>{testErr}</div>}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 14 }}>
        <span>Enabled</span>
        <Switch on={d.enabled} label="Rule enabled" onChange={(v) => set('enabled', v)} />
      </div>
      {err && <div className="alert err-a">{err}</div>}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" className="btn bp" disabled={readOnly || busy || !d.name.trim() || (d.tier === 'regex' && !d.pattern && !d.pattern_set)} onClick={save}>
          {busy ? 'Saving…' : 'Save rule'}
        </button>
        <button type="button" className="btn bg" onClick={onClose}>
          Cancel
        </button>
        {rule && rule.layer !== 'system' && !readOnly && (
          <button type="button" className="btn bl danger" style={{ marginLeft: 'auto' }} onClick={() => onDelete(rule)}>
            Delete rule
          </button>
        )}
      </div>
    </>
  );
};

export default Curation;
