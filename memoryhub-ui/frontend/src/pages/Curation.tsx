import React, { useEffect, useState } from 'react';
import { api } from '@/api/client';
import { PageHeader, Tabs, useApp } from '@/components/Shell';
import { Empty, ErrorState, SkTable, Switch, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { navigate, type HashRoute } from '@/hooks/useHashRoute';
import type { CurationRule } from '@/types';
import { errorMessage, fmtRelative, SCOPE_ORDER, truncate } from '@/utils/format';
import { ConfirmModal } from './common';
import { LockIcon } from './MemoryGraph';

const ACTIONS = ['quarantine', 'flag', 'block', 'reject_with_pointer', 'decay_weight', 'merge'];
const ACTION_LABEL: Record<string, string> = {
  block: 'Block',
  quarantine: 'Quarantine',
  reject_with_pointer: 'Reject with reference',
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
  const [draft, setDraft] = useState<Draft | null>(null);
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

  return (
    <>
      <PageHeader
        title={isUser ? 'My curation rules' : 'Curation rules'}
        crumbs={[{ label: isUser ? 'My curation rules' : 'Curation rules' }]}
        description={
          isUser
            ? 'Personal rules check memory writes owned by your identity — block secrets, quarantine sensitive text or flag near-duplicates. System and organization rules always apply and are shown read-only.'
            : 'Rules run inline on every write. Lower priority numbers run first; the first blocking match wins. You change organizational and your own rules; system rules are shown read-only.'
        }
        actions={
          <button type="button" className="btn bp" onClick={() => select('new')}>
            Create rule
          </button>
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
  // Mirrors the BFF: your own user rules; admins also organizational rules; system rules never.
  const readOnly = !!rule && !(rule.layer === 'user' ? rule.owner_id === me?.username : !isUser && rule.layer === 'organizational');
  const [d, setD] = useState<Draft>(isUser && !rule ? { ...initial, layer: 'user', owner_id: me?.username ?? '' } : initial);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));

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
              {/* Earlier versions stay in the database for audit; the BFF serves no human history view. */}
              {rule.version > 1 && ` · ${rule.version - 1} earlier version${rule.version === 2 ? '' : 's'} kept for audit`}
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
          {d.layer === 'system'
            ? 'This is a system rule. It ships with MemoryHub and cannot be changed from the dashboard.'
            : d.layer === 'organizational'
              ? 'This is an organization rule. It applies to your memories too; only platform admins can change it.'
              : 'This is another person’s rule. Only its owner can change it.'}
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
                {sc === 'user' && d.layer === 'user' ? 'Your personal memories' : APPLIES[sc] ?? sc}
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
      {err && <div className="alert err-a">{err}</div>}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <button type="button" className="btn bp" disabled={readOnly || busy || !d.name.trim() || (d.tier === 'regex' && !d.pattern && !d.pattern_set)} onClick={save}>
          {busy ? 'Saving…' : d.id ? 'Save new version' : 'Create rule'}
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

export default Curation;


