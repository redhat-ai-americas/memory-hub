import React, { useMemo, useState } from 'react';
import { api } from '@/api/client';
import { useApp } from '@/components/Shell';
import { Empty, ErrorState, ScopeLabel, Sk, Standby } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, type HashRoute } from '@/hooks/useHashRoute';
import type { TimelineItem, TimelineResponse } from '@/types';
import { fmtInt, fmtRelative, fmtWeight, SCOPE_ORDER, scopeMeta, shortId, truncate } from '@/utils/format';
import { memoryHref } from './common';
import { LockIcon, recencyColor } from './MemoryGraph';

/**
 * The timeline view of the Memory browser: one lane per scope, time left to
 * right, every dot a memory coloured from light orange (older) to bright red
 * (newest). Scope, project, entity, weight and the selected memory come from
 * the URL, shared with the table and the graph.
 */

const W = 760;
const LANE_H = 64;
const TOP = 16;
const LEFT = 118;
const RIGHT = 20;
const AXIS_H = 34;
const HIST_H = 46;
const R = 6;
const PERIODS: [number, string][] = [
  [7, '7 days'],
  [30, '30 days'],
  [90, '90 days'],
  [365, '1 year'],
  [0, 'All time'],
];
const DAY = 86_400_000;

type ColorBy = 'recency' | 'scope';

const MemoryTimeline: React.FC<{
  route: HashRoute;
  setParams: (changes: Record<string, string | number | string[] | undefined>, resetPage?: boolean) => void;
}> = ({ route, setParams }) => {
  const { standby } = useApp();
  const p = route.params;
  const days = p.get('tdays') === null ? 90 : Number(p.get('tdays'));
  const by: 'created' | 'updated' = p.get('tby') === 'updated' ? 'updated' : 'created';
  const colorBy: ColorBy = p.get('tcolor') === 'scope' ? 'scope' : 'recency';
  const scopes = (p.get('scope') || '').split(',').filter(Boolean);
  const project = p.get('project') || undefined;
  const entity = p.get('entity') || undefined;
  const minWeight = p.get('minw') ? Number(p.get('minw')) : 0;
  const selected = p.get('sel');
  const [hover, setHover] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<TimelineResponse>(
    () => api.timeline({ scope: scopes, project, entity, min_weight: minWeight || undefined, days, by, max_items: 1500 }),
    [scopes.join(','), project, entity, minWeight, days, by],
    standby ? 5000 : null,
  );
  const items = data?.items ?? [];
  const now = data ? new Date(data.now).getTime() : Date.now();
  const start = days ? now - days * DAY : data?.first ? new Date(data.first).getTime() : now - 30 * DAY;
  const span = Math.max(DAY, now - start);
  const x = (t: number) => LEFT + ((t - start) / span) * (W - LEFT - RIGHT);
  const t = (it: TimelineItem) => new Date(it.at).getTime();
  const recency = (it: TimelineItem) => Math.max(0, Math.min(1, (t(it) - start) / span));

  const lanes = useMemo(() => [...SCOPE_ORDER].reverse().filter((s) => items.some((i) => i.scope === s)), [items]);

  // Stack dots that would overlap inside a lane.
  const layout = useMemo(() => {
    const pos: Record<string, { x: number; y: number }> = {};
    const laneHeight: Record<string, number> = {};
    lanes.forEach((scope) => {
      const cols: Record<number, number> = {};
      items
        .filter((i) => i.scope === scope)
        .sort((a, b) => t(a) - t(b))
        .forEach((it) => {
          const px = x(t(it));
          const col = Math.round(px / (R * 2 + 2));
          const row = cols[col] ?? 0;
          cols[col] = row + 1;
          pos[it.id] = { x: col * (R * 2 + 2), y: row };
        });
      laneHeight[scope] = Math.max(LANE_H, 26 + Math.max(0, ...Object.values(cols)) * (R * 2 + 2));
    });
    let y = TOP;
    const laneY: Record<string, number> = {};
    lanes.forEach((s) => {
      laneY[s] = y;
      y += laneHeight[s];
    });
    Object.entries(pos).forEach(([id, v]) => {
      const it = items.find((i) => i.id === id)!;
      pos[id] = { x: Math.max(LEFT + R, Math.min(W - RIGHT - R, v.x)), y: laneY[it.scope] + 20 + v.y * (R * 2 + 2) };
    });
    return { pos, laneY, laneHeight, bottom: y };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, lanes, start, span]);

  const H = layout.bottom + AXIS_H + HIST_H + 10;
  const axisY = layout.bottom + 6;

  const buckets = useMemo(() => {
    const n = 48;
    const out = Array.from({ length: n }, () => 0);
    items.forEach((it) => {
      const i = Math.min(n - 1, Math.max(0, Math.floor(((t(it) - start) / span) * n)));
      out[i] += 1;
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, start, span]);
  const maxBucket = Math.max(1, ...buckets);

  const ticks = useMemo(() => {
    const out: { x: number; label: string }[] = [];
    for (let i = 0; i <= 5; i += 1) {
      const tt = start + (span * i) / 5;
      const d = new Date(tt);
      out.push({
        x: x(tt),
        label: i === 5 ? 'Now' : span > 400 * DAY ? d.toLocaleDateString(undefined, { month: 'short', year: '2-digit' }) : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
      });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start, span]);

  const sel = items.find((i) => i.id === selected) ?? null;
  const colorOf = (it: TimelineItem) => (colorBy === 'recency' ? recencyColor(recency(it)) : scopeMeta(it.scope).color);
  const label = (it: TimelineItem) => (it.redacted ? shortId(it.id) : it.stub);
  const newest = [...items].sort((a, b) => t(b) - t(a)).slice(0, 6);

  return (
    <div className="row-wrap">
      <aside className="card gset" aria-label="Timeline settings">
        <h3>Timeline settings</h3>
        <div>
          <p className="fh">Period</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {PERIODS.map(([d, l]) => (
              <button key={d} type="button" className={`tag ${days === d ? 'on' : ''}`} aria-pressed={days === d} onClick={() => setParams({ tdays: d === 90 ? '' : String(d) }, false)}>
                {l}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="fh">Place memories by</p>
          <div className="seg full" role="group" aria-label="Place memories by">
            {(['created', 'updated'] as const).map((v) => (
              <button key={v} type="button" className={by === v ? 'on' : ''} aria-pressed={by === v} onClick={() => setParams({ tby: v === 'created' ? '' : v }, false)}>
                {v === 'created' ? 'Written' : 'Last changed'}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="fh">Colour</p>
          <div className="seg full" role="group" aria-label="Colour">
            {(['recency', 'scope'] as const).map((v) => (
              <button key={v} type="button" className={colorBy === v ? 'on' : ''} aria-pressed={colorBy === v} onClick={() => setParams({ tcolor: v === 'recency' ? '' : v }, false)}>
                {v === 'recency' ? 'Recency' : 'Scope'}
              </button>
            ))}
          </div>
          {colorBy === 'recency' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
              <span className="hint">Older</span>
              <span className="grad" style={{ width: 120 }} role="img" aria-label="Light orange for older memories to bright red for the newest" />
              <span className="hint">Now</span>
            </div>
          )}
        </div>
        <hr className="sep" />
        <p className="hint" style={{ margin: 0 }}>
          Scope, project, entity and weight filters from the table apply here too. The selected memory stays selected when you switch views.
        </p>
      </aside>

      <section className="card gcard" aria-label="Memory timeline">
        <div className="gtool">
          <b className="sm">{data ? `${fmtInt(items.length)} memories` : 'Timeline'}</b>
          <span className="sm muted">
            {data && (days ? `in the last ${PERIODS.find((pp) => pp[0] === days)?.[1] ?? `${days} days`}` : 'all time')}
            {data?.truncated ? ` · newest ${fmtInt(items.length)} of ${fmtInt(data.total)} — pick a shorter period` : ''}
          </span>
        </div>
        <div className="graph-wrap" style={{ minHeight: 0 }}>
          {standby ? (
            <div className="gstate">
              <Standby compact={false} title="Waiting for the first memory">
                Memories appear on the timeline as agents write them, coloured from light orange to bright red as they get newer.
              </Standby>
            </div>
          ) : error && !data ? (
            <div className="gstate">
              <ErrorState error={error} onRetry={reload} />
            </div>
          ) : loading && !data ? (
            <Sk h={420} r={0} />
          ) : !items.length ? (
            <div className="gstate">
              <Empty title="Nothing in this period">Pick a longer period or clear a filter.</Empty>
            </div>
          ) : (
            <svg viewBox={`0 0 ${W} ${H}`} style={{ aspectRatio: `${W} / ${H}`, background: '#fff' }} role="img" aria-label={`Timeline of ${items.length} memories`} onClick={(e) => !(e.target as Element).closest('g.node') && setParams({ sel: '' }, false)}>
              <g fontFamily="Red Hat Text" fontSize="12">
                {lanes.map((s, i) => (
                  <g key={s}>
                    <rect x={0} y={layout.laneY[s]} width={W} height={layout.laneHeight[s]} fill={i % 2 ? '#fafafa' : '#fff'} />
                    <text x={14} y={layout.laneY[s] + 24} fontWeight={600} fill={scopeMeta(s).color}>
                      {scopeMeta(s).label}
                    </text>
                    <text x={14} y={layout.laneY[s] + 40} fontSize="11" fill="#6a6e73">
                      {items.filter((it) => it.scope === s).length}
                    </text>
                  </g>
                ))}
                {ticks.map((tk) => (
                  <g key={tk.x}>
                    <line x1={tk.x} x2={tk.x} y1={TOP} y2={axisY} stroke="#ececec" />
                    <text x={tk.x} y={axisY + 18} textAnchor="middle" fontSize="11" fill="#4d4d4d">
                      {tk.label}
                    </text>
                  </g>
                ))}
                <line x1={x(now)} x2={x(now)} y1={TOP} y2={axisY} stroke="#e0000f" strokeOpacity=".5" strokeDasharray="2 4" strokeWidth={2} />
                <line x1={LEFT} x2={W - RIGHT} y1={axisY} y2={axisY} stroke="#8a8d90" />
              </g>
              {/* density */}
              <g>
                {buckets.map((c, i) => {
                  const bw = (W - LEFT - RIGHT) / buckets.length;
                  const h = (c / maxBucket) * (HIST_H - 8);
                  return (
                    <rect key={i} x={LEFT + i * bw + 1} y={axisY + AXIS_H + (HIST_H - 8 - h)} width={Math.max(1, bw - 2)} height={h} rx={2} fill={recencyColor((i + 0.5) / buckets.length)}>
                      <title>{c} memories</title>
                    </rect>
                  );
                })}
                <text x={14} y={axisY + AXIS_H + HIST_H - 12} fontSize="11" fill="#6a6e73" fontFamily="Red Hat Text">
                  Writes over time
                </text>
              </g>
              <g>
                {items.map((it) => {
                  const pt = layout.pos[it.id];
                  if (!pt) return null;
                  const isSel = it.id === selected;
                  return (
                    <g
                      key={it.id}
                      className="node"
                      tabIndex={0}
                      role="button"
                      aria-label={`${scopeMeta(it.scope).label} memory: ${label(it)}`}
                      onClick={() => setParams({ sel: it.id }, false)}
                      onKeyDown={(e) => e.key === 'Enter' && setParams({ sel: it.id }, false)}
                      onMouseEnter={() => setHover(it.id)}
                      onMouseLeave={() => setHover(null)}
                    >
                      <title>{`${label(it)} · ${new Date(it.at).toLocaleString()}`}</title>
                      <circle cx={pt.x} cy={pt.y} r={R - 1 + it.weight * 2} fill={colorOf(it)} stroke={isSel ? '#151515' : '#fff'} strokeWidth={isSel ? 2.5 : 1.5} />
                      {isSel && <circle cx={pt.x} cy={pt.y} r={R + 6} fill="none" stroke="#b1380b" strokeWidth={2} strokeDasharray="3 4" />}
                    </g>
                  );
                })}
              </g>
              {(() => {
                const it = items.find((i) => i.id === (hover ?? selected));
                const pt = it && layout.pos[it.id];
                if (!it || !pt) return null;
                const right = pt.x < W / 2;
                return (
                  <text x={right ? pt.x + 12 : pt.x - 12} y={pt.y + 4} textAnchor={right ? 'start' : 'end'} fontSize="12" fontWeight={600} fontFamily="Red Hat Text" className="glabel" pointerEvents="none">
                    {truncate(label(it), 46)}
                  </text>
                );
              })()}
            </svg>
          )}
        </div>
      </section>

      <aside className="card gside" aria-label="Selected memory">
        {sel ? (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <ScopeLabel scope={sel.scope}>{scopeMeta(sel.scope).label} · selected</ScopeLabel>
              <button type="button" className="btn bl" aria-label="Close panel" onClick={() => setParams({ sel: '' }, false)}>
                ✕
              </button>
            </div>
            {sel.redacted ? (
              <div className="redacted-box">
                <div className="redact">
                  <LockIcon />
                  Content hidden
                </div>
              </div>
            ) : (
              <h3 style={{ fontSize: 18, lineHeight: 1.35 }}>{sel.stub}</h3>
            )}
            <dl className="dl">
              <dt>Owner</dt>
              <dd>{sel.scope_id ?? sel.owner_id}</dd>
              <dt>Weight</dt>
              <dd>{fmtWeight(sel.weight)}</dd>
              <dt>Written</dt>
              <dd style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <i className="ldot" style={{ background: recencyColor(recency(sel)) }} />
                {fmtRelative(sel.created_at)}
              </dd>
              <dt>Changed</dt>
              <dd>
                {fmtRelative(sel.updated_at)} · v{sel.version}
              </dd>
            </dl>
            {!sel.redacted && sel.domains.length > 0 && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {sel.domains.map((d) => (
                  <span key={d} className="tag">
                    {d}
                  </span>
                ))}
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <a className="btn bs" href={memoryHref(sel.id)}>
                {sel.redacted ? 'Metadata' : 'Open'}
              </a>
              <a className="btn bl" href={buildHash('/memories', { ...Object.fromEntries(p), view: 'graph', gfocus: 'memory', focus: sel.id })}>
                Show in graph
              </a>
            </div>
          </>
        ) : (
          <>
            <h3>Newest</h3>
            {newest.length === 0 ? (
              <p className="sm muted">Nothing here yet.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {newest.map((it) => (
                  <button key={it.id} type="button" className="conn" onClick={() => setParams({ sel: it.id }, false)}>
                    <i className="ldot" style={{ background: colorOf(it) }} />
                    <span className="ellipsis" style={{ minWidth: 0, flex: 1 }}>
                      {label(it)}
                    </span>
                    <span className="hint" style={{ whiteSpace: 'nowrap' }}>
                      {fmtRelative(it.at)}
                    </span>
                  </button>
                ))}
              </div>
            )}
            <p className="hint" style={{ margin: 0 }}>
              Click a dot to see the memory. Brighter red means more recent.
            </p>
          </>
        )}
      </aside>
    </div>
  );
};

export default MemoryTimeline;
