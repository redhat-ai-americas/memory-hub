export const SCOPE_ORDER = ['user', 'project', 'campaign', 'role', 'organizational', 'enterprise'] as const;

/** Label class, display name and solid hue for each scope tier. */
export const SCOPE_META: Record<string, { cls: string; label: string; color: string }> = {
  user: { cls: 's-user', label: 'User', color: '#0066cc' },
  project: { cls: 's-project', label: 'Project', color: '#009596' },
  campaign: { cls: 's-campaign', label: 'Campaign', color: '#5e40be' },
  role: { cls: 's-role', label: 'Role', color: '#ca6c0f' },
  organizational: { cls: 's-org', label: 'Organizational', color: '#3d7317' },
  enterprise: { cls: 's-ent', label: 'Enterprise', color: '#ee0000' },
};

export const scopeMeta = (scope: string) =>
  SCOPE_META[scope] ?? { cls: 'g', label: scope ? scope[0].toUpperCase() + scope.slice(1) : 'Unknown', color: '#8a8d90' };

export const fmtInt = (n: number | null | undefined): string =>
  n === null || n === undefined ? '—' : n.toLocaleString('en-US');

/** 31402 → "31.4k", 117 → "117". */
export const fmtCompact = (n: number): string => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
};

export const fmtAxis = (n: number): string => (n >= 1000 ? `${Math.round(n / 100) / 10}k`.replace('.0k', 'k') : String(n));

export const fmtWeight = (w: number | null | undefined) => (w === null || w === undefined ? '—' : w.toFixed(2));

/** UUID → design-style short id "mem_7f3a…c21". */
export const shortId = (id: string | null | undefined, prefix = 'mem'): string => {
  if (!id) return '—';
  const hex = id.replace(/-/g, '');
  return `${prefix}_${hex.slice(0, 4)}…${hex.slice(-3)}`;
};

const toDate = (value: string | Date) => (value instanceof Date ? value : new Date(value));

export const fmtRelative = (value: string | Date | null | undefined, now = new Date()): string => {
  if (!value) return 'Never';
  const d = toDate(value);
  const diff = (now.getTime() - d.getTime()) / 1000;
  if (diff < 45) return 'Just now';
  if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (d.getTime() >= startToday - 86400_000) return 'Yesterday';
  if (diff < 86400 * 60 && d.getFullYear() === now.getFullYear()) return fmtMonthDay(d);
  if (diff < 86400 * 365) return `${Math.round(diff / 86400)} days ago`;
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
};

export const fmtMonthDay = (value: string | Date) =>
  toDate(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

export const fmtTime = (value: string | Date) =>
  toDate(value).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

export const fmtDateTime = (value: string | Date | null | undefined) =>
  value
    ? toDate(value).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
    : '—';

export const fmtShortDateTime = (value: string | Date) =>
  toDate(value).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });

/** "2026-10-16 14:48:12" in UTC, as in the audit log. */
export const fmtUtc = (value: string | Date) => toDate(value).toISOString().replace('T', ' ').slice(0, 19);

export const initials = (name: string): string => {
  const parts = name.replace(/[._-]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

const AVATAR_COLORS = ['#5e40be', '#8f4700', '#3d7317', '#004d4d', '#a60000', '#004d99', '#383838', '#ca6c0f'];
export const avatarColor = (key: string): string => {
  let h = 0;
  for (let i = 0; i < key.length; i += 1) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
};

export const truncate = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text);

export const plural = (n: number, one: string, many = `${one}s`) => `${fmtInt(n)} ${n === 1 ? one : many}`;

export const errorMessage = (err: unknown): string => (err instanceof Error ? err.message : String(err));
