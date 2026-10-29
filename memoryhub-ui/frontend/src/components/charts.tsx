import React, { useMemo, useRef, useState } from 'react';
import type { OverviewRange } from '@/types';

/* ------------------------------------------------------------------ */
/* Shared helpers                                                      */
/* ------------------------------------------------------------------ */

export function niceStep(raw: number): number {
  if (raw <= 1) return 1;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const n = raw / mag;
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return nice * mag;
}

export const fmtTick = (v: number) => (v >= 1000 ? `${Math.round(v / 100) / 10}k`.replace('.0k', 'k') : String(Math.round(v)));

/** Monotone cubic (Fritsch–Carlson) path: smooth, never overshoots, so empty buckets stay on the baseline. */
const smoothPath = (pts: [number, number][]): string => {
  const n = pts.length;
  if (n === 0) return '';
  if (n === 1) return `M${pts[0][0]},${pts[0][1]}`;
  const dx = pts.slice(1).map((p, i) => p[0] - pts[i][0]);
  const sl = pts.slice(1).map((p, i) => (p[1] - pts[i][1]) / dx[i]);
  const m = pts.map((_, i) => (i === 0 ? sl[0] : i === n - 1 ? sl[n - 2] : sl[i - 1] * sl[i] <= 0 ? 0 : (sl[i - 1] + sl[i]) / 2));
  for (let i = 0; i < n - 1; i++) {
    if (sl[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / sl[i];
    const b = m[i + 1] / sl[i];
    const h = a * a + b * b;
    if (h > 9) {
      const t = 3 / Math.sqrt(h);
      m[i] = t * a * sl[i];
      m[i + 1] = t * b * sl[i];
    }
  }
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[i + 1];
    const h = dx[i] / 3;
    d += ` C${x0 + h},${y0 + m[i] * h} ${x1 - h},${y1 - m[i + 1] * h} ${x1},${y1}`;
  }
  return d;
};

/* ------------------------------------------------------------------ */
/* Memory operations — PatternFly-style area chart                    */
/* ------------------------------------------------------------------ */

export type ActivityPoint = { date: string; searches: number; writes: number };
type SeriesKey = 'searches' | 'writes';

const SERIES: { key: SeriesKey; label: string; color: string }[] = [
  { key: 'writes', label: 'Writes & updates', color: '#0066cc' },
  { key: 'searches', label: 'Searches', color: '#009596' },
];

export const ACTIVITY_RANGES: { value: OverviewRange; label: string; title: string }[] = [
  { value: 'all', label: 'All time', title: 'All time' },
  { value: '1h', label: '1h', title: 'Last hour' },
  { value: '12h', label: '12h', title: 'Last 12 hours' },
  { value: '1d', label: '1d', title: 'Last 24 hours' },
  { value: '7d', label: '7d', title: 'Last 7 days' },
  { value: '30d', label: '30d', title: 'Last 30 days' },
];

const HOUR = 3600;
const DAY = 86400;

/** Axis label for a bucket start, at a precision that suits the selected range. */
const axisLabel = (iso: string, bucket: number, range?: OverviewRange) => {
  const d = new Date(iso);
  // Multi-day windows always use dates on the x-axis. The tooltip still shows
  // the precise bucket span for shorter windows.
  if (range === 'all' || range === '7d' || range === '30d') {
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  if (bucket < DAY) return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  if (bucket >= 28 * DAY) return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

/** Tooltip heading: the bucket's span, e.g. "Oct 20, 14:00 – 15:00". */
const spanLabel = (iso: string, bucket: number) => {
  const a = new Date(iso);
  const b = new Date(a.getTime() + bucket * 1000);
  const day = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const time = (d: Date) => d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  if (bucket < DAY) return `${day(a)}, ${time(a)} – ${time(b)}`;
  if (bucket === DAY) return a.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  return `${day(a)} – ${day(new Date(b.getTime() - 1))}`;
};

const bucketName = (bucket: number) => {
  if (bucket < HOUR) return `${Math.round(bucket / 60)}-minute`;
  if (bucket === HOUR) return 'hourly';
  if (bucket < DAY) return `${Math.round(bucket / HOUR)}-hour`;
  if (bucket === DAY) return 'daily';
  if (bucket === 7 * DAY) return 'weekly';
  return 'monthly';
};

export const ActivityChart: React.FC<{
  data: ActivityPoint[];
  bucketSeconds: number;
  range?: OverviewRange;
  height?: number;
}> = ({ data, bucketSeconds, range, height = 300 }) => {
  const [hidden, setHidden] = useState<Partial<Record<SeriesKey, boolean>>>({});
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const visible = SERIES.filter((s) => !hidden[s.key]);
  const max = Math.max(1, ...data.flatMap((d) => visible.map((s) => d[s.key])));
  const step = niceStep(max / 4);
  const top = step * 4;
  const totals = useMemo(
    () => Object.fromEntries(SERIES.map((s) => [s.key, data.reduce((a, d) => a + d[s.key], 0)])) as Record<SeriesKey, number>,
    [data],
  );

  const W = 900;
  const H = height;
  const L = 52;
  const R = 16;
  const T = 14;
  const B = range === '30d' ? 54 : 30;
  const base = H - B;
  const n = data.length;
  const x = (i: number) => (n <= 1 ? L + (W - L - R) / 2 : L + (i * (W - L - R)) / (n - 1));
  const y = (v: number) => T + (base - T) * (1 - v / top);
  const ticks = [0, 1, 2, 3, 4].map((k) => step * k);
  const labelCount = range === '7d' ? Math.min(n, 7) : range === 'all' ? Math.min(n, 8) : Math.min(n, 6);
  const labelIdx =
    range === '30d' && n > 1
      ? Array.from({ length: n }, (_, k) => k)
      : labelCount <= 1
        ? [0]
        : Array.from(new Set(Array.from({ length: labelCount }, (_, k) => Math.round((k * (n - 1)) / (labelCount - 1)))));

  const toggle = (key: SeriesKey) => {
    if (!hidden[key] && visible.length === 1) return; // keep at least one series on
    setHidden((h) => ({ ...h, [key]: !h[key] }));
  };

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = svgRef.current?.getBoundingClientRect();
    if (!box || n === 0) return;
    const vx = ((e.clientX - box.left) / box.width) * W;
    const i = n <= 1 ? 0 : Math.round(((vx - L) / (W - L - R)) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  const hp = hover !== null ? data[hover] : null;
  const hx = hover !== null ? x(hover) : 0;
  const tipLeft = hover !== null ? `${(hx / W) * 100}%` : '0';
  const tipFlip = hover !== null && hx > W * 0.66;

  return (
    <div className="ops-chart">
      <div className="ops-legend">
        {SERIES.map((s) => {
          const on = !hidden[s.key];
          return (
            <button key={s.key} type="button" aria-pressed={on} className={on ? 'on' : ''} onClick={() => toggle(s.key)}>
              <i style={{ background: on ? s.color : undefined }} />
              {s.label}
              <b>{totals[s.key].toLocaleString()}</b>
            </button>
          );
        })}
        <span className="ops-note">{bucketName(bucketSeconds)} buckets</span>
      </div>
      <div className="ops-plot">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Memory operations in ${n} ${bucketName(bucketSeconds)} buckets: ${totals.writes} writes and updates, ${totals.searches} searches`}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        >
          <defs>
            {SERIES.map((s) => (
              <linearGradient key={s.key} id={`ops-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.color} stopOpacity="0.16" />
                <stop offset="100%" stopColor={s.color} stopOpacity="0" />
              </linearGradient>
            ))}
          </defs>
          <g className="ops-grid">
            {ticks.slice(1).map((v) => (
              <line key={v} x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
            ))}
          </g>
          <line className="ops-axis" x1={L} x2={W - R} y1={base} y2={base} />
          <g className="ops-ticks">
            {ticks.map((v) => (
              <text key={v} x={L - 10} y={y(v) + 4} textAnchor="end">
                {fmtTick(v)}
              </text>
            ))}
            <text x={12} y={(T + base) / 2} transform={`rotate(-90 12 ${(T + base) / 2})`} textAnchor="middle" className="ops-ytitle">
              Memories
            </text>
            {n > 0 &&
              labelIdx.map((i) => (
                <text
                  key={i}
                  x={x(i)}
                  y={range === '30d' ? H - 10 : H - 8}
                  textAnchor={range === '30d' ? 'end' : n > 1 && i === 0 ? 'start' : n > 1 && i === n - 1 ? 'end' : 'middle'}
                  transform={range === '30d' ? `rotate(-45 ${x(i)} ${H - 10})` : undefined}
                  fontSize={range === '30d' ? 10 : undefined}
                >
                  {axisLabel(data[i].date, bucketSeconds, range)}
                </text>
              ))}
          </g>
          {visible.map((s) => {
            const coords = data.map((d, i) => [x(i), y(d[s.key])] as [number, number]);
            if (!coords.length) return null;
            const line = smoothPath(coords);
            const area = n > 1 ? `${line} L${x(n - 1)},${base} L${x(0)},${base} Z` : '';
            return (
              <g key={s.key}>
                {area && <path d={area} fill={`url(#ops-${s.key})`} />}
                <path d={line} fill="none" stroke={s.color} strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round" />
                {n === 1 && <circle cx={coords[0][0]} cy={coords[0][1]} r="4" fill={s.color} />}
              </g>
            );
          })}
          {totals.writes + totals.searches === 0 && (
            <text x={(L + W - R) / 2} y={(T + base) / 2} textAnchor="middle" className="ops-none">
              No memory operations in this window
            </text>
          )}
          {hp && (
            <g pointerEvents="none">
              <line className="ops-cross" x1={hx} x2={hx} y1={T} y2={base} />
              {visible.map((s) => (
                <circle key={s.key} cx={hx} cy={y(hp[s.key])} r="4.5" fill="#ffffff" stroke={s.color} strokeWidth="2" />
              ))}
            </g>
          )}
        </svg>
        {hp && (
          <div className={`ops-tip ${tipFlip ? 'flip' : ''}`} style={{ left: tipLeft }} role="tooltip">
            <div className="ops-tip-h">{spanLabel(hp.date, bucketSeconds)}</div>
            {visible.map((s) => (
              <div key={s.key} className="ops-tip-r">
                <i style={{ background: s.color }} />
                <span>{s.label}</span>
                <b>{hp[s.key].toLocaleString()}</b>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Pie chart with legend                                               */
/* ------------------------------------------------------------------ */

export const PIE_COLORS = ['#0066cc', '#009596', '#5e40be', '#ca6c0f', '#3d7317', '#c9190b', '#b8bbbe'];

export type PieSlice = { key: string; label: string; value: number; href?: string; color?: string };

const arc = (cx: number, cy: number, r: number, a0: number, a1: number) => {
  const p = (a: number) => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a1);
  return `M${cx},${cy} L${x0},${y0} A${r},${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1},${y1} Z`;
};

export const PieChart: React.FC<{ slices: PieSlice[]; label: string; size?: number }> = ({
  slices,
  label,
  size = 200,
}) => {
  const [hover, setHover] = useState<string | null>(null);
  const total = slices.reduce((a, s) => a + s.value, 0);
  const cx = size / 2;
  const r = size / 2 - 4;
  let acc = 0;
  const shaped = slices.map((s, i) => {
    const a0 = (acc / total) * Math.PI * 2;
    acc += s.value;
    const a1 = (acc / total) * Math.PI * 2;
    return { ...s, a0, a1, color: s.color ?? PIE_COLORS[i % PIE_COLORS.length], pct: total ? (s.value / total) * 100 : 0 };
  });
  const fmtPct = (p: number) => (p > 0 && p < 1 ? '<1%' : `${Math.round(p)}%`);

  return (
    <div className="pie">
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} role="img" aria-label={label} className="pie-svg">
        {shaped.length === 1 ? (
          <circle cx={cx} cy={cx} r={r} fill={shaped[0].color} />
        ) : (
          shaped.map((s) => {
            const mid = (s.a0 + s.a1) / 2;
            const off = hover === s.key ? 5 : 0;
            return (
              <path
                key={s.key}
                d={arc(cx, cx, r - 5, s.a0, s.a1)}
                fill={s.color}
                stroke="#fff"
                strokeWidth="1.5"
                transform={`translate(${off * Math.sin(mid)} ${-off * Math.cos(mid)})`}
                opacity={hover && hover !== s.key ? 0.45 : 1}
                style={{ transition: 'transform .15s ease, opacity .15s ease' }}
                onMouseEnter={() => setHover(s.key)}
                onMouseLeave={() => setHover(null)}
                onClick={() => s.href && (window.location.hash = s.href.replace(/^#/, ''))}
                cursor={s.href ? 'pointer' : undefined}
              >
                <title>{`${s.label}: ${s.value.toLocaleString()} (${fmtPct(s.pct)})`}</title>
              </path>
            );
          })
        )}
      </svg>
      <ul className="pie-legend">
        {shaped.map((s) => (
          <li key={s.key} className={hover === s.key ? 'on' : ''}>
            {React.createElement(
              s.href ? 'a' : 'div',
              {
                className: 'pie-row',
                href: s.href,
                onMouseEnter: () => setHover(s.key),
                onMouseLeave: () => setHover(null),
                onFocus: () => setHover(s.key),
                onBlur: () => setHover(null),
              },
              <>
                <i style={{ background: s.color }} />
              <span className="ellipsis" title={s.label}>
                {s.label}
              </span>
              <b>{s.value.toLocaleString()}</b>
                <span className="muted">{fmtPct(s.pct)}</span>
              </>,
            )}
          </li>
        ))}
      </ul>
    </div>
  );
};
