import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/api/client';
import { useApp } from '@/components/Shell';
import { Empty, ErrorState, Icon, Modal, ScopeLabel, Sk, SkLines, Standby, Switch, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash, type HashRoute } from '@/hooks/useHashRoute';
import type { GraphAll, GraphNeighbourhood, GraphPrefer, NodeBrief } from '@/types';
import { fmtInt, fmtRelative, fmtWeight, SCOPE_ORDER, scopeMeta, shortId, truncate } from '@/utils/format';
import { MemoryPicker, RelationshipModal } from './common';

/**
 * The graph view of the Memory browser.
 *
 * Focus "All memories" draws every readable memory — separate clusters and
 * memories with no relationships at all; selecting one keeps its links bright.
 * Focus "One memory" is the neighbourhood of a memory up to N hops.
 * Layouts: Force and Provenance tree (derived_from / supersedes by scope
 * tier). Time has its own view next to Table and Graph (MemoryTimeline).
 *
 * Scope, project, entity, weight and the selected memory live in the URL and
 * are shared with the table and the timeline, so switching views keeps them.
 * "All memories" draws up to a node limit the viewer picks; when more match,
 * the canvas says how many were left out and which ones were kept.
 */

const W = 640;
const BASE_H = 540;
const EDGE_TYPES = ['related_to', 'derived_from', 'supersedes', 'conflicts_with'] as const;
const EDGE_STYLE: Record<string, { color: string; dash?: string; marker: string }> = {
  derived_from: { color: '#3d7317', marker: 'arg' },
  supersedes: { color: '#5e40be', marker: 'arp' },
  conflicts_with: { color: '#b1380b', dash: '6 5', marker: 'arr' },
  related_to: { color: '#8a8d90', marker: 'ar' },
};
const edgeStyle = (t: string) => EDGE_STYLE[t] ?? EDGE_STYLE.related_to;

export type Layout = 'force' | 'tree';
const LIMITS = [150, 300, 600, 1000, 1500];
const PREFER_LABEL: Record<GraphPrefer, string> = { connected: 'most connected', recent: 'newest', weight: 'strongest' };
type ColorBy = 'scope' | 'recency';
type GNode = NodeBrief & { depth: number; degree?: number };
type GEdge = { id: string; source: string; target: string; type: string };
type Pos = Record<string, { x: number; y: number }>;
type Box = { x: number; y: number; w: number; h: number };
interface Geometry {
  pos: Pos;
  h: number;
  island: Box | null;
  treeLanes?: { scope: string; y: number; h: number }[];
}

/* ------------------------------------------------------------------ */
/* Colour                                                              */
/* ------------------------------------------------------------------ */

const RECENCY_STOPS: [number, [number, number, number]][] = [
  [0, [253, 227, 200]],
  [0.4, [248, 178, 106]],
  [0.75, [240, 96, 44]],
  [1, [224, 0, 15]],
];
export const recencyColor = (t: number) => {
  const x = Math.max(0, Math.min(1, t));
  let i = 0;
  while (i < RECENCY_STOPS.length - 2 && x > RECENCY_STOPS[i + 1][0]) i += 1;
  const [t0, c0] = RECENCY_STOPS[i];
  const [t1, c1] = RECENCY_STOPS[i + 1];
  const f = (x - t0) / (t1 - t0 || 1);
  return `rgb(${c0.map((v, j) => Math.round(v + (c1[j] - v) * f)).join(',')})`;
};

/* ------------------------------------------------------------------ */
/* Layouts                                                             */
/* ------------------------------------------------------------------ */

/** Deterministic force layout inside a box; `pin` stays at the centre. */
function forceIn(ids: string[], edges: GEdge[], box: { x: number; y: number; w: number; h: number }, pin?: string, depth?: Record<string, number>): Pos {
  const pos: Pos = {};
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  const ringOf = (id: string) => (depth ? depth[id] ?? 1 : 1);
  const rings: Record<number, string[]> = {};
  ids.forEach((id) => (rings[ringOf(id)] = [...(rings[ringOf(id)] ?? []), id]));
  const scale = Math.min(box.w, box.h) / 2.4;
  Object.entries(rings).forEach(([d, ring]) => {
    const r = pin ? Number(d) * scale * 0.55 : scale * 0.7;
    ring.forEach((id, i) => {
      const a = (i / ring.length) * Math.PI * 2 + Number(d) * 0.7;
      pos[id] = { x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r * 0.8 };
    });
  });
  if (ids.length === 1) pos[ids[0]] = { x: cx, y: cy };
  const local = edges.filter((e) => pos[e.source] && pos[e.target]);
  const rest = Math.max(70, Math.min(230, Math.sqrt((box.w * box.h) / Math.max(1, ids.length)) * 0.9));
  const repel = rest * rest * 0.8;
  const iterations = ids.length > 400 ? 60 : ids.length > 150 ? 120 : 240;
  for (let iter = 0; iter < iterations; iter += 1) {
    const force: Pos = {};
    ids.forEach((id) => (force[id] = { x: 0, y: 0 }));
    for (let i = 0; i < ids.length; i += 1)
      for (let j = i + 1; j < ids.length; j += 1) {
        const a = pos[ids[i]];
        const b = pos[ids[j]];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) {
          dx = ((i * 7919) % 13) - 6 || 1;
          dy = ((j * 104729) % 11) - 5 || 1;
          d2 = dx * dx + dy * dy;
        }
        const d = Math.sqrt(d2);
        const f = repel / d2;
        force[ids[i]].x += (dx / d) * f;
        force[ids[i]].y += (dy / d) * f;
        force[ids[j]].x -= (dx / d) * f;
        force[ids[j]].y -= (dy / d) * f;
      }
    local.forEach((e) => {
      const a = pos[e.source];
      const b = pos[e.target];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - rest) * 0.04;
      force[e.source].x += (dx / d) * f;
      force[e.source].y += (dy / d) * f;
      force[e.target].x -= (dx / d) * f;
      force[e.target].y -= (dy / d) * f;
    });
    const cool = 1 - iter / iterations;
    ids.forEach((id) => {
      if (id === pin) return;
      const p = pos[id];
      p.x += Math.max(-30, Math.min(30, force[id].x + (cx - p.x) * 0.004)) * cool;
      p.y += Math.max(-30, Math.min(30, force[id].y + (cy - p.y) * 0.004)) * cool;
      p.x = Math.max(box.x + 40, Math.min(box.x + box.w - 40, p.x));
      p.y = Math.max(box.y + 36, Math.min(box.y + box.h - 36, p.y));
    });
    if (pin) pos[pin] = { x: cx, y: cy };
  }
  return pos;
}

/** All memories: one box per connected cluster, unconnected ones in an island. */
function clusterLayout(nodes: GNode[], edges: GEdge[]): { pos: Pos; h: number; island: { x: number; y: number; w: number; h: number } | null } {
  const parent: Record<string, string> = {};
  const find = (x: string): string => (parent[x] === x ? x : (parent[x] = find(parent[x])));
  nodes.forEach((n) => (parent[n.id] = n.id));
  edges.forEach((e) => parent[e.source] && parent[e.target] && (parent[find(e.source)] = find(e.target)));
  const groups: Record<string, string[]> = {};
  nodes.forEach((n) => (groups[find(n.id)] = [...(groups[find(n.id)] ?? []), n.id]));
  const clusters = Object.values(groups)
    .filter((g) => g.length > 1)
    .sort((a, b) => b.length - a.length);
  const orphans = Object.values(groups)
    .filter((g) => g.length === 1)
    .map((g) => g[0]);

  const pos: Pos = {};
  let x = 0;
  let y = 0;
  let rowH = 0;
  clusters.forEach((ids) => {
    const side = Math.min(W, Math.max(220, Math.sqrt(ids.length) * 120));
    const box = { w: ids.length >= 8 ? Math.min(W, side * 1.4) : side, h: side };
    if (x + box.w > W) {
      x = 0;
      y += rowH;
      rowH = 0;
    }
    Object.assign(pos, forceIn(ids, edges, { x, y, ...box }));
    x += box.w;
    rowH = Math.max(rowH, box.h);
  });
  y += rowH;
  let island = null;
  if (orphans.length) {
    const cols = Math.max(1, Math.floor((W - 40) / 46));
    const rows = Math.ceil(orphans.length / cols);
    island = { x: 10, y: y + 16, w: W - 20, h: 44 + rows * 46 };
    orphans.forEach((id, i) => {
      pos[id] = { x: 34 + (i % cols) * 46, y: y + 72 + Math.floor(i / cols) * 46 };
    });
    y = island.y + island.h;
  }
  return { pos, h: Math.max(BASE_H, y + 20), island };
}

const TIERS: string[] = [...SCOPE_ORDER].reverse(); // enterprise … user, top to bottom

/** Provenance tree: scope tiers as lanes, broader scopes on top. */
function treeLayout(nodes: GNode[]): { pos: Pos; h: number; lanes: { scope: string; y: number; h: number }[] } {
  const lanes = TIERS.filter((s) => nodes.some((n) => n.scope === s));
  const perRow = Math.max(1, Math.floor((W - 20) / 150));
  const pos: Pos = {};
  let y = 0;
  const out = lanes.map((scope) => {
    const row = nodes.filter((n) => n.scope === scope).sort((a, b) => a.created_at.localeCompare(b.created_at));
    const rows = Math.ceil(row.length / perRow);
    const laneH = 56 + rows * 60;
    row.forEach((n, j) => {
      const sub = Math.floor(j / perRow);
      const col = j % perRow;
      const count = Math.min(perRow, row.length - sub * perRow);
      pos[n.id] = { x: 10 + ((col + 0.5) / count) * (W - 20), y: y + 62 + sub * 60 };
    });
    const lane = { scope, y, h: laneH };
    y += laneH;
    return lane;
  });
  return { pos, h: Math.max(BASE_H, y + 20), lanes: out };
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

const MemoryGraph: React.FC<{
  route: HashRoute;
  setParams: (changes: Record<string, string | number | string[] | undefined>, resetPage?: boolean) => void;
}> = ({ route, setParams }) => {
  const toast = useToast();
  const { standby, role } = useApp();
  const p = route.params;
  const focusMode: 'all' | 'memory' = p.get('gfocus') === 'memory' && p.get('focus') ? 'memory' : 'all';
  const focusId = p.get('focus') || undefined;
  const depth = Number(p.get('depth') || 2);
  const layout: Layout = p.get('layout') === 'tree' ? 'tree' : 'force';
  const colorBy: ColorBy = (p.get('color') as ColorBy) || 'scope';
  const limit = Number(p.get('glimit') || 300);
  const prefer = (p.get('gprefer') as GraphPrefer) || 'connected';
  const scopes = (p.get('scope') || '').split(',').filter(Boolean);
  const project = p.get('project') || undefined;
  const entity = p.get('entity') || undefined;
  const minWeight = p.get('minw') ? Number(p.get('minw')) : 0;

  const [types, setTypes] = useState<Set<string>>(new Set(EDGE_TYPES));
  const [showOrphans, setShowOrphans] = useState(true);
  const [superseded, setSuperseded] = useState(false);
  const [labels, setLabels] = useState(true);
  const [fade, setFade] = useState(true);
  const selected = p.get('sel') || (focusMode === 'memory' ? focusId ?? null : null);
  const setSelected = (id: string | null) => setParams({ sel: id ?? '' }, false);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [picker, setPicker] = useState(false);
  const [relate, setRelate] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);

  const all = useApi<GraphAll>(
    () =>
      focusMode === 'all'
        ? api.graphAll({ include_superseded: superseded, max_nodes: limit, prefer, scope: scopes, project, entity, min_weight: minWeight || undefined })
        : Promise.resolve(null as unknown as GraphAll),
    [focusMode, superseded, limit, prefer, scopes.join(','), project, entity, minWeight],
    standby ? 5000 : null,
  );
  const hood = useApi<GraphNeighbourhood>(
    () => (focusMode === 'memory' ? api.neighbourhood({ focus: focusId, depth, max_nodes: 300 }) : Promise.resolve(null as unknown as GraphNeighbourhood)),
    [focusMode, focusId, depth],
    standby ? 5000 : null,
  );
  const active = focusMode === 'all' ? all : hood;
  const data = active.data;

  useEffect(() => setView({ x: 0, y: 0, k: 1 }), [focusMode, focusId, layout]);

  const rawNodes: GNode[] = useMemo(() => {
    if (!data) return [];
    return focusMode === 'all' ? (data as GraphAll).nodes : (data as GraphNeighbourhood).nodes;
  }, [data, focusMode]);
  const rawEdges: GEdge[] = (data?.edges as GEdge[]) ?? [];

  const visibleEdges = useMemo(() => rawEdges.filter((e) => types.has(e.type) || !EDGE_TYPES.includes(e.type as never)), [rawEdges, types]);
  const degree = useMemo(() => {
    const d: Record<string, number> = {};
    visibleEdges.forEach((e) => {
      d[e.source] = (d[e.source] ?? 0) + 1;
      d[e.target] = (d[e.target] ?? 0) + 1;
    });
    return d;
  }, [visibleEdges]);

  const nodes = useMemo(() => {
    let list = rawNodes.filter((n) => n.weight >= minWeight - 1e-9 || n.id === focusId);
    if (!superseded && focusMode === 'memory') list = list.filter((n) => n.is_current || n.id === focusId);
    if (!showOrphans) list = list.filter((n) => (degree[n.id] ?? 0) > 0 || n.id === focusId);
    if (layout === 'tree') {
      const prov = new Set<string>();
      visibleEdges.forEach((e) => {
        if (e.type === 'derived_from' || e.type === 'supersedes') {
          prov.add(e.source);
          prov.add(e.target);
        }
      });
      list = list.filter((n) => prov.has(n.id) || n.id === focusId);
    }
    return list;
  }, [rawNodes, minWeight, superseded, focusMode, showOrphans, degree, layout, visibleEdges, focusId]);
  const nodeById = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);
  const edges = useMemo(
    () => visibleEdges.filter((e) => nodeById[e.source] && nodeById[e.target] && (layout !== 'tree' || e.type === 'derived_from' || e.type === 'supersedes')),
    [visibleEdges, nodeById, layout],
  );

  const geometry = useMemo<Geometry>(() => {
    if (!nodes.length) return { pos: {}, h: BASE_H, island: null };
    if (layout === 'tree') {
      const t = treeLayout(nodes);
      return { pos: t.pos, h: t.h, island: null, treeLanes: t.lanes };
    }
    if (focusMode === 'memory') {
      const depthOf = Object.fromEntries(nodes.map((n) => [n.id, n.depth]));
      return { pos: forceIn(nodes.map((n) => n.id), edges, { x: 0, y: 0, w: W, h: BASE_H }, (data as GraphNeighbourhood).focus?.id, depthOf), h: BASE_H, island: null };
    }
    return clusterLayout(nodes, edges);
  }, [nodes, edges, layout, focusMode, data]);
  const pos = geometry.pos;
  const H = geometry.h;

  const times = useMemo(() => nodes.map((n) => new Date(n.created_at).getTime()), [nodes]);
  const tMin = times.length ? Math.min(...times) : 0;
  const tMax = Math.max(Date.now(), ...(times.length ? times : [0]));
  const recency = (n: GNode) => (tMax === tMin ? 1 : (new Date(n.created_at).getTime() - tMin) / (tMax - tMin));
  const colorOf = (n: GNode) => (colorBy === 'recency' ? recencyColor(recency(n)) : scopeMeta(n.scope).color);

  const sel = selected ? nodeById[selected] : undefined;
  const neighbours = useMemo(() => {
    const s = new Set<string>();
    if (!selected) return s;
    edges.forEach((e) => {
      if (e.source === selected) s.add(e.target);
      if (e.target === selected) s.add(e.source);
    });
    return s;
  }, [edges, selected]);
  const dim = fade && !!sel && focusMode === 'all' && layout === 'force';
  const focusNode = focusMode === 'memory' ? (data as GraphNeighbourhood | null)?.focus : null;
  const metadataOnly = role === 'admin';

  const setFocus = (mode: 'all' | 'memory', id?: string) => setParams({ gfocus: mode === 'memory' ? 'memory' : '', focus: id ?? (mode === 'memory' ? focusId : undefined) }, false);
  const setLayout = (l: Layout) => setParams({ layout: l === 'force' ? '' : l, color: '' }, false);

  const exportPng = () => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const xml = new XMLSerializer().serializeToString(svgEl);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = W * 2;
      canvas.height = H * 2;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.fillStyle = '#fafafa';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      const a = document.createElement('a');
      a.download = `memory-graph-${focusNode ? shortId(focusNode.id) : 'all'}.png`;
      a.href = canvas.toDataURL('image/png');
      a.click();
    };
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
  };

  const radius = (n: GNode) => {
    const isFocus = focusNode && n.id === focusNode.id && layout === 'force';
    if (isFocus) return 26;
    return 6 + n.weight * 8;
  };

  const legendScopes = [...new Set(nodes.map((n) => n.scope))];
  const orphanCount = nodes.filter((n) => !(degree[n.id] > 0)).length;
  const stats = data
    ? [
        `${nodes.length} memories`,
        `${edges.length} links`,
        focusMode === 'all' ? `${orphanCount} unconnected` : `${(data as GraphNeighbourhood).hidden_count} hidden`,
      ]
        .filter(Boolean)
        .join(' · ')
    : '';

  const ga = focusMode === 'all' ? (data as GraphAll | null) : null;
  const gh = focusMode === 'memory' ? (data as GraphNeighbourhood | null) : null;
  const nextLimit = LIMITS.find((n) => n > limit && n <= (ga?.limit_ceiling ?? 1500));
  const truncation =
    ga && ga.truncated ? (
      <div className="gtrunc" role="status">
        <span>
          <b>
            Showing {fmtInt(ga.nodes.length)} of {fmtInt(ga.total)} memories
          </b>{' '}
          — the {PREFER_LABEL[ga.prefer]} ones. {fmtInt(ga.left_out)} left out
          {ga.hidden_links ? `, ${fmtInt(ga.hidden_links)} links lead to them` : ''}.
        </span>
        <span style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {nextLimit && (
            <button type="button" className="btn bs sm" onClick={() => setParams({ glimit: String(nextLimit) }, false)}>
              Draw up to {fmtInt(nextLimit)}
            </button>
          )}
          <button type="button" className="btn bl sm" onClick={() => setParams({ view: '' }, false)}>
            Narrow with filters
          </button>
          <button type="button" className="btn bl sm" onClick={() => (selected ? setFocus('memory', selected) : setPicker(true))}>
            Focus on one memory
          </button>
        </span>
      </div>
    ) : gh && gh.cut_count > 0 ? (
      <div className="gtrunc" role="status">
        <span>
          <b>{fmtInt(gh.cut_count)} more connected memories</b> were not drawn (limit {fmtInt(gh.max_nodes)}). Lower the depth or pick a closer memory.
        </span>
      </div>
    ) : null;

  return (
    <div className="row-wrap">
      {/* ---------------- Settings ---------------- */}
      <aside className="card gset" aria-label="Graph settings">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3>Graph settings</h3>
          <button
            type="button"
            className="btn bl sm"
            onClick={() => {
              setTypes(new Set(EDGE_TYPES));
              setShowOrphans(true);
              setSuperseded(false);
              setLabels(true);
              setFade(true);
              setParams({ gfocus: '', focus: undefined, depth: '', layout: '', color: '', glimit: '', gprefer: '', sel: '' }, false);
            }}
          >
            Reset
          </button>
        </div>

        <div>
          <p className="fh">Focus</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label className={`radio ${focusMode === 'all' ? 'on' : ''}`}>
              <input type="radio" name="gfocus" checked={focusMode === 'all'} onChange={() => setFocus('all')} />
              <span>
                <span className="sm b6" style={{ display: 'block' }}>
                  All memories
                </span>
                <span className="hint">Every graph you can read, including memories with no connections.</span>
              </span>
            </label>
            <label className={`radio ${focusMode === 'memory' ? 'on' : ''}`}>
              <input
                type="radio"
                name="gfocus"
                checked={focusMode === 'memory'}
                onChange={() => (selected || focusId ? setFocus('memory', selected ?? focusId) : setPicker(true))}
              />
              <span style={{ minWidth: 0 }}>
                <span className="sm b6" style={{ display: 'block' }}>
                  One memory
                </span>
                <span className="hint" style={{ display: 'block' }}>
                  Its connections only, up to N hops.
                </span>
                <button type="button" className="link-btn sm mono" style={{ marginTop: 4 }} onClick={() => setPicker(true)}>
                  {focusId ? shortId(focusId) : 'Pick a memory'}
                </button>
              </span>
            </label>
          </div>
          <p className="fh" style={{ marginTop: 12 }}>
            Depth
          </p>
          <div className="seg full" role="group" aria-label="Depth">
            {[1, 2, 3].map((d) => (
              <button
                key={d}
                type="button"
                className={focusMode === 'memory' && depth === d ? 'on' : ''}
                aria-pressed={focusMode === 'memory' && depth === d}
                onClick={() => {
                  const id = selected ?? focusId;
                  if (!id) {
                    setPicker(true);
                    return;
                  }
                  setParams({ gfocus: 'memory', focus: id, depth: d === 2 ? '' : String(d) }, false);
                }}
              >
                {d} hop{d === 1 ? '' : 's'}
              </button>
            ))}
          </div>
          <p className="hint" style={{ margin: '6px 0 0' }}>
            Hops from the selected memory. Picking a depth switches to One memory.
          </p>
        </div>

        <hr className="sep" />

        <div>
          <p className="fh">Relationships</p>
          <div className="fx">
            {EDGE_TYPES.map((t) => (
              <label key={t}>
                <span>
                  <input
                    type="checkbox"
                    checked={types.has(t)}
                    onChange={() => {
                      const next = new Set(types);
                      if (next.has(t)) next.delete(t);
                      else next.add(t);
                      setTypes(next);
                    }}
                  />{' '}
                  <span className="ln" style={{ borderTopColor: edgeStyle(t).color, borderTopStyle: edgeStyle(t).dash ? 'dashed' : 'solid' }} />{' '}
                  <span className="sm">{t}</span>
                </span>
                <span className="muted sm">{rawEdges.filter((e) => e.type === t).length}</span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <p className="fh">Colour nodes by</p>
          <div className="seg full" role="group" aria-label="Colour nodes by">
            {(['scope', 'recency'] as const).map((c) => (
              <button key={c} type="button" className={colorBy === c ? 'on' : ''} aria-pressed={colorBy === c} onClick={() => setParams({ color: c }, false)}>
                {c === 'scope' ? 'Scope' : 'Recency'}
              </button>
            ))}
          </div>
        </div>

        <div>
          <GraphWeight value={minWeight} onCommit={(v) => setParams({ minw: v ? v.toFixed(2) : '' }, false)} />
        </div>

        {focusMode === 'all' && (
          <div>
            <p className="fh">Size</p>
            <label className="sm b6" htmlFor="glimit" style={{ display: 'block', marginBottom: 6 }}>
              Draw up to
            </label>
            <div className="seg full" role="group" aria-label="Node limit" id="glimit">
              {LIMITS.map((n) => (
                <button key={n} type="button" className={limit === n ? 'on' : ''} aria-pressed={limit === n} onClick={() => setParams({ glimit: n === 300 ? '' : String(n) }, false)}>
                  {n >= 1000 ? `${n / 1000}k` : n}
                </button>
              ))}
            </div>
            <label className="sm b6" htmlFor="gprefer" style={{ display: 'block', margin: '10px 0 6px' }}>
              When more match, keep
            </label>
            <select id="gprefer" className="in" value={prefer} onChange={(e) => setParams({ gprefer: e.target.value === 'connected' ? '' : e.target.value }, false)}>
              <option value="connected">Most connected — clusters stay whole</option>
              <option value="recent">Newest first</option>
              <option value="weight">Strongest (highest weight)</option>
            </select>
            <p className="hint" style={{ margin: '6px 0 0' }}>
              Large graphs draw slower. Narrow by scope or project in the table filters — they apply here too.
            </p>
          </div>
        )}

        <hr className="sep" />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <p className="fh" style={{ margin: 0 }}>
            Show
          </p>
          {[
            { label: 'Unconnected memories', hint: 'Memories with no relationships', on: showOrphans, set: setShowOrphans },
            { label: 'Superseded versions', hint: 'Older versions, faded', on: superseded, set: setSuperseded },
            { label: 'Labels', hint: metadataOnly ? 'Names on readable nodes; personal memories show IDs' : 'Names on key nodes', on: labels, set: setLabels },
            { label: 'Fade unrelated', hint: 'On select, keep only its links bright', on: fade, set: setFade },
          ].map((s) => (
            <div className="swrow" key={s.label}>
              <span>
                <span style={{ display: 'block' }}>{s.label}</span>
                <span className="hint">{s.hint}</span>
              </span>
              <Switch on={s.on} onChange={s.set} label={s.label} />
            </div>
          ))}
        </div>
      </aside>

      {/* ---------------- Canvas ---------------- */}
      <section className="card gcard" aria-label="Memory graph">
        <div className="gtool">
          <div className="seg" role="group" aria-label="Layout">
            {(
              [
                ['force', 'Force'],
                ['tree', 'Provenance tree'],
              ] as [Layout, string][]
            ).map(([v, label]) => (
              <button key={v} type="button" className={layout === v ? 'on' : ''} aria-pressed={layout === v} onClick={() => setLayout(v)}>
                {label}
              </button>
            ))}
          </div>
          <span className="sm muted" style={{ marginLeft: 'auto' }}>
            {stats}
          </span>
          <button type="button" className="btn bg sm" disabled={!nodes.length} onClick={exportPng}>
            Export PNG
          </button>
        </div>
        {truncation}
        <div className="graph-wrap" style={{ minHeight: 0 }}>
          {standby ? (
            <div className="gstate">
              <Standby compact={false} title="Waiting for the first memory">
                The graph draws memories as nodes, coloured by scope or recency, and their provenance, supersession and conflict links as edges.
              </Standby>
            </div>
          ) : active.error && !data ? (
            <div className="gstate">
              <ErrorState error={active.error} onRetry={active.reload} />
            </div>
          ) : active.loading && !data ? (
            <Sk h={BASE_H} r={0} />
          ) : !nodes.length ? (
            <div className="gstate">
              <Empty title={layout === 'tree' ? 'No provenance links here' : 'No memories to draw'}>
                {layout === 'tree'
                  ? 'The provenance tree shows derived_from and supersedes chains. None of the memories in view have them yet.'
                  : 'Memories and their relationships appear here once agents write them.'}
              </Empty>
            </div>
          ) : (
            <>
              <svg
                ref={svgRef}
                viewBox={`${W / 2 - W / 2 / view.k - view.x} ${H / 2 - H / 2 / view.k - view.y} ${W / view.k} ${H / view.k}`}
                style={{ aspectRatio: `${W} / ${H}`, minHeight: 0 }}
                role="img"
                aria-label={`Memory graph, ${nodes.length} memories and ${edges.length} relationships`}
                onWheel={(e) => setView((v) => ({ ...v, k: Math.max(0.4, Math.min(3, v.k * (e.deltaY < 0 ? 1.1 : 0.9))) }))}
                onPointerDown={(e) => {
                  if ((e.target as Element).closest('g.node')) return;
                  drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
                }}
                onPointerMove={(e) => {
                  if (!drag.current || !svgRef.current) return;
                  const scale = W / view.k / svgRef.current.clientWidth;
                  setView((v) => ({ ...v, x: drag.current!.vx + (e.clientX - drag.current!.x) * scale, y: drag.current!.vy + (e.clientY - drag.current!.y) * scale }));
                }}
                onPointerUp={() => (drag.current = null)}
                onPointerLeave={() => (drag.current = null)}
                onClick={(e) => {
                  if (!(e.target as Element).closest('g.node') && focusMode === 'all') setSelected(null);
                }}
              >
                <defs>
                  <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">
                    <circle cx="2" cy="2" r="1" fill="#d9d9d9" />
                  </pattern>
                  {Object.entries({ ar: '#8a8d90', arg: '#3d7317', arr: '#b1380b', arp: '#5e40be' }).map(([id, fill]) => (
                    <marker key={id} id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                      <path d="M0 0L10 5L0 10z" fill={fill} />
                    </marker>
                  ))}
                </defs>
                <rect x={-W} y={-H} width={W * 3} height={H * 3} fill="url(#dots)" />

                {layout === 'tree' &&
                  geometry.treeLanes?.map((l) => (
                    <g key={l.scope}>
                      <line x1={0} x2={W} y1={l.y + l.h} y2={l.y + l.h} stroke="#e0e0e0" strokeDasharray="4 4" />
                      <text x={14} y={l.y + 24} fontSize="12" fontWeight="600" fill={scopeMeta(l.scope).color} fontFamily="Red Hat Text">
                        {scopeMeta(l.scope).label}
                      </text>
                    </g>
                  ))}
                {geometry.island && (
                  <g>
                    <rect x={geometry.island.x} y={geometry.island.y} width={geometry.island.w} height={geometry.island.h} rx={14} fill="#fff" fillOpacity=".6" stroke="#b8bbbe" strokeDasharray="5 4" />
                    <text x={geometry.island.x + 14} y={geometry.island.y + 22} fontSize="12" fill="#4d4d4d" fontFamily="Red Hat Text">
                      No connections · {orphanCount}
                    </text>
                  </g>
                )}

                <g fill="none" strokeWidth="2">
                  {edges.map((e) => {
                    const a = pos[e.source];
                    const b = pos[e.target];
                    if (!a || !b) return null;
                    const st = edgeStyle(e.type);
                    const touchesSel = selected === e.source || selected === e.target;
                    const touchesFocus = focusNode && (e.source === focusNode.id || e.target === focusNode.id);
                    const dx = b.x - a.x;
                    const dy = b.y - a.y;
                    const d = Math.sqrt(dx * dx + dy * dy) || 1;
                    let cut = radius(nodeById[e.target]) + 4;
                    if (layout === 'tree') cut = Math.min(Math.abs(dx) > 1e-6 ? 70 / Math.abs(dx / d) : 1e9, Math.abs(dy) > 1e-6 ? 27 / Math.abs(dy / d) : 1e9);
                    const opacity = dim ? (touchesSel ? 1 : 0.1) : touchesFocus || touchesSel ? 1 : 0.6;
                    return (
                      <line
                        key={e.id}
                        x1={a.x}
                        y1={a.y}
                        x2={b.x - (dx / d) * cut}
                        y2={b.y - (dy / d) * cut}
                        stroke={st.color}
                        strokeDasharray={st.dash}
                        strokeOpacity={opacity}
                        markerEnd={e.type !== 'related_to' && (layout === 'tree' || touchesSel || touchesFocus) ? `url(#${st.marker})` : undefined}
                      >
                        <title>{e.type}</title>
                      </line>
                    );
                  })}
                </g>

                <g fontFamily="Red Hat Text" fontSize="12" fill="#151515">
                  {nodes.map((n) => {
                    const pt = pos[n.id];
                    if (!pt) return null;
                    const color = colorOf(n);
                    const isSel = selected === n.id;
                    const near = neighbours.has(n.id);
                    const isFocus = focusNode?.id === n.id;
                    let opacity = n.is_current && n.status === 'active' ? 1 : 0.45;
                    if (dim && !isSel && !near) opacity = 0.18;
                    const label = n.redacted ? shortId(n.id) : truncate(n.stub, isFocus ? 34 : 26);
                    const orphan = !(degree[n.id] > 0);
                    const showLabel =
                      (labels || isSel) &&
                      (layout === 'tree' ||
                        isSel ||
                        (focusMode === 'memory' ? isFocus || n.depth === 1 || nodes.length <= 14 : dim ? near : !orphan && (n.weight >= 0.8 || nodes.length <= 14)));
                    const aria = `${scopeMeta(n.scope).label} memory: ${n.redacted ? shortId(n.id) : n.stub}`;
                    if (layout === 'tree') {
                      return (
                        <g key={n.id} className="node" tabIndex={0} role="button" aria-label={aria} onClick={() => setSelected(n.id)} onKeyDown={(e) => e.key === 'Enter' && setSelected(n.id)}>
                          <title>{n.redacted ? 'Content hidden' : n.stub}</title>
                          <rect x={pt.x - 68} y={pt.y - 24} width={136} height={48} rx={10} fill="#fff" stroke={isSel ? '#0066cc' : '#d2d2d2'} strokeWidth={isSel ? 2 : 1} opacity={opacity} />
                          <circle cx={pt.x - 54} cy={pt.y - 8} r={5} fill={color} />
                          <text x={pt.x - 44} y={pt.y - 4} fontSize="12" fontWeight="500">
                            {truncate(label, 16)}
                          </text>
                          <text x={pt.x - 60} y={pt.y + 14} fontSize="10.5" fill="#4d4d4d" fontFamily="Red Hat Mono">
                            v{n.version} · w {fmtWeight(n.weight)}
                          </text>
                        </g>
                      );
                    }
                    const r = radius(n);
                    return (
                      <g key={n.id} className="node" tabIndex={0} role="button" aria-label={aria} onClick={() => setSelected(n.id)} onDoubleClick={() => setFocus('memory', n.id)} onKeyDown={(e) => e.key === 'Enter' && setSelected(n.id)}>
                        <title>{n.redacted ? `${shortId(n.id)} · content hidden` : n.stub}</title>
                        <circle cx={pt.x} cy={pt.y} r={r} fill={color} fillOpacity={opacity} stroke="#fff" strokeWidth={isFocus ? 4 : 3} />
                        {(isFocus || isSel) && <circle cx={pt.x} cy={pt.y} r={r + 7} fill="none" stroke={colorBy === 'recency' ? '#b1380b' : color} strokeWidth="2" strokeDasharray="3 4" />}
                        {showLabel && (
                          <text x={pt.x} y={pt.y + r + 16} textAnchor="middle" fontWeight={isFocus || isSel ? 600 : 400} fill={n.depth > 1 ? '#4d4d4d' : '#151515'} className="glabel">
                            {label}
                            {!n.is_current ? ` (v${n.version})` : ''}
                          </text>
                        )}
                      </g>
                    );
                  })}
                </g>
              </svg>
              <div className="zoom">
                <button type="button" aria-label="Zoom in" onClick={() => setView((v) => ({ ...v, k: Math.min(3, v.k * 1.25) }))}>
                  +
                </button>
                <button type="button" aria-label="Zoom out" onClick={() => setView((v) => ({ ...v, k: Math.max(0.4, v.k / 1.25) }))}>
                  −
                </button>
                <button type="button" aria-label="Fit to screen" onClick={() => setView({ x: 0, y: 0, k: 1 })}>
                  Fit
                </button>
              </div>
            </>
          )}
        </div>
        <div className="glegend">
          {colorBy === 'scope' ? (
            <>
              <b>Scope</b>
              {legendScopes.map((s) => (
                <span key={s}>
                  <i style={{ background: scopeMeta(s).color }} />
                  {scopeMeta(s).label}
                </span>
              ))}
            </>
          ) : (
            <>
              <b>Recency</b>
              <span className="muted">{times.length ? new Date(tMin).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : ''}</span>
              <span className="grad" role="img" aria-label="Light orange for older memories to bright red for the newest" />
              <span className="muted">Now</span>
              <span className="muted">Brighter = written more recently</span>
            </>
          )}
          <span style={{ flexBasis: '100%', height: 0 }} />
          <b>Edge</b>
          {EDGE_TYPES.map((t) => (
            <span key={t}>
              <span className="ln" style={{ borderTopColor: edgeStyle(t).color, borderTopStyle: edgeStyle(t).dash ? 'dashed' : 'solid' }} />
              {t}
            </span>
          ))}
        </div>
      </section>

      {/* ---------------- Selected memory ---------------- */}
      <aside className="card gside" aria-label="Selected memory">
        {standby ? (
          <Standby>Select a node to see its owner, weight, version, connections and conflicts.</Standby>
        ) : active.loading && !data ? (
          <SkLines lines={9} />
        ) : !sel ? (
          <Empty compact title="Nothing selected">
            Click a node to inspect it and see its connections. Double-click to focus the graph on it.
          </Empty>
        ) : (
          <SidePanel
            node={sel}
            content={focusNode && focusNode.id === sel.id ? focusNode.content : undefined}
            edges={rawEdges}
            nodeById={Object.fromEntries(rawNodes.map((n) => [n.id, n]))}
            provenance={focusNode && focusNode.id === sel.id ? (data as GraphNeighbourhood).provenance : []}
            recency={colorBy === 'recency' ? recencyColor(recency(sel)) : undefined}
            focused={focusMode === 'memory' && focusId === sel.id}
            canWrite={role !== 'admin'}
            onSelect={setSelected}
            onClose={() => setSelected(null)}
            onFocus={() => (focusMode === 'memory' && focusId === sel.id ? setFocus('all') : setFocus('memory', sel.id))}
            onRelate={() => setRelate(true)}
          />
        )}
      </aside>

      {picker && (
        <Modal title="Focus memory" onClose={() => setPicker(false)}>
          <MemoryPicker
            autoFocus
            onPick={(m) => {
              setPicker(false);
              setSelected(m.id);
              setFocus('memory', m.id);
            }}
          />
        </Modal>
      )}
      {relate && sel && (
        <RelationshipModal
          sourceIds={[sel.id]}
          onClose={() => setRelate(false)}
          onDone={() => {
            toast('Graph updated.');
            active.reload();
          }}
        />
      )}
    </div>
  );
};

const SidePanel: React.FC<{
  node: GNode;
  content?: string;
  edges: GEdge[];
  nodeById: Record<string, GNode>;
  provenance: NodeBrief[];
  recency?: string;
  focused: boolean;
  canWrite: boolean;
  onSelect: (id: string) => void;
  onClose: () => void;
  onFocus: () => void;
  onRelate: () => void;
}> = ({ node, content, edges, nodeById, provenance, recency, focused, canWrite, onSelect, onClose, onFocus, onRelate }) => {
  const conns = edges
    .filter((e) => e.source === node.id || e.target === node.id)
    .map((e) => ({ e, other: nodeById[e.source === node.id ? e.target : e.source], out: e.source === node.id }))
    .filter((c) => c.other);
  const conflicts = conns.filter((c) => c.e.type === 'conflicts_with');
  const name = (n: NodeBrief) => (n.redacted ? shortId(n.id) : n.stub);
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <ScopeLabel scope={node.scope}>{scopeMeta(node.scope).label} · selected</ScopeLabel>
        <button type="button" className="btn bl" aria-label="Close panel" onClick={onClose}>
          ✕
        </button>
      </div>
      {node.redacted ? (
        <div className="redacted-box">
          <div className="redact">
            <LockIcon />
            Content hidden
          </div>
          <p className="hint" style={{ margin: '6px 0 0' }}>
            <span className="mono">{shortId(node.id)}</span>. Only the owner and those they share it with can read it.
          </p>
        </div>
      ) : (
        <h3 style={{ fontSize: 18, lineHeight: 1.35 }}>{content ?? node.stub}</h3>
      )}
      <dl className="dl">
        <dt>Owner</dt>
        <dd>{node.scope_id ?? node.owner_id}</dd>
        <dt>Weight</dt>
        <dd>{fmtWeight(node.weight)}</dd>
        <dt>Version</dt>
        <dd>
          v{node.version} · {node.is_current ? 'current' : 'superseded'}
          {node.status !== 'active' ? ` · ${node.status}` : ''}
        </dd>
        <dt>Written</dt>
        <dd style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {recency && <i className="ldot" style={{ background: recency }} />}
          {fmtRelative(node.created_at)}
        </dd>
        <dt>Degree</dt>
        <dd>{conns.length} connections</dd>
      </dl>
      <div>
        <div className="sm b6" style={{ marginBottom: 4 }}>
          Connections
        </div>
        {conns.length === 0 ? (
          <p className="sm muted" style={{ margin: 0 }}>
            No relationships yet{canWrite ? '. Create one to link it to the rest of the graph.' : '.'}
          </p>
        ) : (
          conns.map(({ e, other, out }) => (
            <button key={e.id} type="button" className="conn" onClick={() => onSelect(other.id)}>
              <span className="ln" style={{ borderTopColor: edgeStyle(e.type).color, borderTopStyle: edgeStyle(e.type).dash ? 'dashed' : 'solid', flex: 'none' }} />
              <span style={{ minWidth: 0 }}>
                <span className="hint" style={{ display: 'block' }}>
                  {e.type} {out ? '→' : '←'}
                </span>
                <span className="ellipsis" style={{ display: 'block' }}>
                  {name(other)}
                </span>
              </span>
            </button>
          ))
        )}
      </div>
      {provenance.length > 1 && (
        <div>
          <div className="sm b6" style={{ marginBottom: 8 }}>
            Provenance chain
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
            {provenance.map((pn, i) => (
              <React.Fragment key={pn.id}>
                {i > 0 && (
                  <div className="muted" style={{ paddingLeft: 18 }}>
                    ↓ derived_from
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <ScopeLabel scope={pn.scope}>{pn.scope === 'organizational' ? 'org' : pn.scope}</ScopeLabel>
                  {pn.id === node.id ? 'This memory' : truncate(name(pn), 40)}
                </div>
              </React.Fragment>
            ))}
          </div>
        </div>
      )}
      {conflicts.length > 0 && (
        <div className="conflict">
          <b>Conflict detected</b>
          <br />
          <span className="muted">conflicts_with {conflicts.map((c) => `“${truncate(name(c.other), 60)}”`).join(', ')}.</span>
          <div style={{ marginTop: 8 }}>
            <a href={buildHash('/review', { tab: 'contradictions' })}>Resolve in review queue</a>
          </div>
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 'auto' }}>
        <a className="btn bp" href={buildHash(`/memory/${node.id}`)}>
          {node.redacted ? 'Open metadata' : 'Open memory'}
        </a>
        <button type="button" className="btn bg" onClick={onFocus}>
          {focused ? 'Show all memories' : 'Show only its connections'}
        </button>
        {canWrite && (
          <button type="button" className="btn bl" onClick={onRelate}>
            <Icon.Plus />
            Relationship
          </button>
        )}
      </div>
    </>
  );
};

export const LockIcon: React.FC<{ size?: number }> = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 018 0v4" />
  </svg>
);

export default MemoryGraph;

const GraphWeight: React.FC<{ value: number; onCommit: (v: number) => void }> = ({ value, onCommit }) => {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <>
      <p className="fh">Weight ≥ {v.toFixed(2)}</p>
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={Math.round(v * 100)}
        aria-label="Minimum weight"
        style={{ width: '100%' }}
        onChange={(e) => setV(Number(e.target.value) / 100)}
        onMouseUp={() => onCommit(v)}
        onKeyUp={() => onCommit(v)}
        onTouchEnd={() => onCommit(v)}
      />
    </>
  );
};
