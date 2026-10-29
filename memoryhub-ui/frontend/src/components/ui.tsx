import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { scopeMeta } from '@/utils/format';

/* ------------------------------------------------------------------ */
/* Icons (stroke icons from the design)                                */
/* ------------------------------------------------------------------ */

type IconProps = { size?: number; stroke?: string; width?: number; style?: React.CSSProperties };
const svg = (path: React.ReactNode, { size = 18, stroke = 'currentColor', width = 2, style }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth={width} aria-hidden="true" style={style}>
    {path}
  </svg>
);

export const Icon = {
  Menu: (p: IconProps) => svg(<path d="M3 6h18M3 12h18M3 18h18" />, { size: 20, ...p }),
  Search: (p: IconProps) => svg(<><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></>, p),
  Bell: (p: IconProps) => svg(<><path d="M6 16V11a6 6 0 0112 0v5l2 2H4z" /><path d="M10 21h4" /></>, p),
  Help: (p: IconProps) => svg(<><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 015 0c0 2-2.5 2-2.5 4M12 17h.01" /></>, p),
  Refresh: (p: IconProps) => svg(<><path d="M20 11a8 8 0 00-14.7-4L4 9" /><path d="M4 4v5h5" /><path d="M4 13a8 8 0 0014.7 4L20 15" /><path d="M20 20v-5h-5" /></>, p),
  Chevron: (p: IconProps) => svg(<path d="M6 9l6 6 6-6" />, { size: 12, width: 2.5, ...p }),
  Arrow: (p: IconProps) => svg(<path d="M5 12h14M13 6l6 6-6 6" />, { size: 16, ...p }),
  Plus: (p: IconProps) => svg(<path d="M12 5v14M5 12h14" />, { size: 14, width: 2.5, ...p }),
  Info: (p: IconProps) => svg(<><circle cx="12" cy="12" r="9" /><path d="M12 8h.01M11 12h1v5h1" /></>, p),
  Warn: (p: IconProps) => svg(<><path d="M12 3l9 16H3z" /><path d="M12 10v4M12 17h.01" /></>, p),
  Mark: (p: IconProps) =>
    svg(
      <>
        <circle cx="6" cy="6" r="2.5" />
        <circle cx="18" cy="6" r="2.5" />
        <circle cx="12" cy="18" r="2.5" />
        <path d="M8 7.5l3 8M16 7.5l-3 8M8.5 6h7" />
      </>,
      { stroke: '#fff', width: 2.2, ...p },
    ),
};

/* ------------------------------------------------------------------ */
/* Labels                                                              */
/* ------------------------------------------------------------------ */

export const ScopeLabel: React.FC<{ scope: string; children?: React.ReactNode; className?: string }> = ({ scope, children, className }) => {
  const meta = scopeMeta(scope);
  return <span className={`lbl ${meta.cls} ${className ?? ''}`}>{children ?? meta.label}</span>;
};

export const Status: React.FC<{ status: string; children?: React.ReactNode }> = ({ status, children }) => {
  const cls = status === 'healthy' ? 'ok' : status === 'degraded' ? 'warn' : status === 'down' ? 'err' : 'muted';
  return (
    <span className={`st ${cls}`}>
      <span className="status-dot" />
      {children}
    </span>
  );
};

/* ------------------------------------------------------------------ */
/* Loading / empty / standby / error states                            */
/* ------------------------------------------------------------------ */

export const Sk: React.FC<{ w?: number | string; h?: number; r?: number; style?: React.CSSProperties }> = ({ w = '100%', h = 14, r, style }) => (
  <span className="sk" style={{ display: 'block', width: w, height: h, borderRadius: r, ...style }} aria-hidden="true" />
);

export const SkLines: React.FC<{ lines?: number; gap?: number }> = ({ lines = 4, gap = 12 }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap }} aria-busy="true" aria-label="Loading">
    {Array.from({ length: lines }, (_, i) => (
      <Sk key={i} w={`${92 - ((i * 17) % 40)}%`} />
    ))}
  </div>
);

export const SkTable: React.FC<{ rows?: number; cols?: number }> = ({ rows = 6, cols = 5 }) => (
  <div style={{ padding: '8px 20px 20px' }} aria-busy="true" aria-label="Loading">
    {Array.from({ length: rows }, (_, r) => (
      <div key={r} style={{ display: 'flex', gap: 16, padding: '14px 0', borderBottom: '1px solid #eee' }}>
        {Array.from({ length: cols }, (_, c) => (
          <Sk key={c} w={c === 0 ? '34%' : `${10 + ((r + c) % 3) * 4}%`} />
        ))}
      </div>
    ))}
  </div>
);

export const MarkIcon: React.FC<{ size?: number }> = ({ size = 48 }) =>
  Icon.Mark({ size, stroke: '#8a8d90', width: 1.5 });

export const Empty: React.FC<{
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  compact?: boolean;
  icon?: boolean;
}> = ({ title, children, action, compact, icon = true }) => (
  <div className={`empty ${compact ? 'compact' : ''}`}>
    {icon && <MarkIcon size={compact ? 36 : 48} />}
    <div className="et">{title}</div>
    {children && <p>{children}</p>}
    {action}
  </div>
);

/**
 * Standby block for memory-driven cards while the tenant has no memories.
 * Mirrors the Overview "Waiting for the first memory" state: neutral icon,
 * what will appear here, and a pulse showing the dashboard keeps checking.
 */
export const Standby: React.FC<{ title?: string; children?: React.ReactNode; compact?: boolean; action?: React.ReactNode }> = ({
  title = 'Waiting for the first memory',
  children,
  compact = true,
  action,
}) => (
  <div className={`empty ${compact ? 'compact' : ''}`} role="status">
    <MarkIcon size={compact ? 32 : 48} />
    <div className="et">{title}</div>
    {children && <p>{children}</p>}
    <span className="standby-pulse">
      <i />
      Checking every 5 s
    </span>
    {action}
  </div>
);

export const ErrorState: React.FC<{ error: Error | null; onRetry?: () => void; title?: string; compact?: boolean }> = ({
  error,
  onRetry,
  title = 'Could not load this data',
  compact,
}) => (
  <div className={`empty ${compact ? 'compact' : ''}`} role="alert">
    <span className="err">
      <Icon.Warn size={compact ? 28 : 40} width={1.6} />
    </span>
    <div className="et">{title}</div>
    <p>{error?.message || 'The request failed.'}</p>
    {onRetry && (
      <button type="button" className="btn bs" onClick={onRetry}>
        Try again
      </button>
    )}
  </div>
);

/* ------------------------------------------------------------------ */
/* Controls                                                            */
/* ------------------------------------------------------------------ */

export const Switch: React.FC<{ on: boolean; onChange?: (on: boolean) => void; label: string; disabled?: boolean }> = ({
  on,
  onChange,
  label,
  disabled,
}) => (
  <button
    type="button"
    className={`sw ${on ? '' : 'off'}`}
    role="switch"
    aria-checked={on}
    aria-label={label}
    disabled={disabled || !onChange}
    onClick={() => onChange?.(!on)}
  />
);

export function Seg<T extends string>({
  value,
  options,
  onChange,
  label,
  disabled,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={o.value === value ? 'on' : ''}
          aria-pressed={o.value === value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Dropdown menu anchored to its toggle. Closes on outside click / Escape. */
export const Dropdown: React.FC<{
  toggle: (props: { onClick: () => void; 'aria-expanded': boolean }) => React.ReactNode;
  children: (close: () => void) => React.ReactNode;
  align?: 'left' | 'right';
  style?: React.CSSProperties;
}> = ({ toggle, children, align = 'left', style }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    const onNav = () => setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('hashchange', onNav);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('hashchange', onNav);
    };
  }, [open]);
  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block', ...style }}>
      {toggle({ onClick: () => setOpen((o) => !o), 'aria-expanded': open })}
      {open && (
        <div className="menu" role="menu" style={{ top: 'calc(100% + 4px)', [align]: 0 }}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
};

/** Select styled as the design's ".sel" pill with a menu of options. */
export function SelectMenu<T extends string>({
  value,
  options,
  onChange,
  prefix,
  label,
  width,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  prefix?: string;
  label: string;
  width?: string;
}) {
  const current = options.find((o) => o.value === value);
  return (
    <Dropdown
      style={width ? { width } : undefined}
      toggle={(p) => (
        <button type="button" className="sel" aria-label={label} aria-haspopup="menu" style={width ? { width: '100%', justifyContent: 'space-between' } : undefined} {...p}>
          {prefix}
          {current?.label ?? value}
          <Icon.Chevron />
        </button>
      )}
    >
      {(close) =>
        options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="menuitemradio"
            aria-checked={o.value === value}
            style={o.value === value ? { fontWeight: 600 } : undefined}
            onClick={() => {
              onChange(o.value);
              close();
            }}
          >
            {o.label}
          </button>
        ))
      }
    </Dropdown>
  );
}

/* ------------------------------------------------------------------ */
/* Modal                                                               */
/* ------------------------------------------------------------------ */

export const Modal: React.FC<{
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  actions?: React.ReactNode;
  wide?: boolean;
}> = ({ title, onClose, children, actions, wide }) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    const first = ref.current?.querySelector<HTMLElement>('input, textarea, select, button');
    first?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
          <h2>{title}</h2>
          <button type="button" className="btn bl" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>
        {children}
        {actions && <div className="modal-actions">{actions}</div>}
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Toasts                                                              */
/* ------------------------------------------------------------------ */

interface Toast {
  id: number;
  text: string;
  kind: 'ok' | 'err';
}
const ToastContext = createContext<(text: string, kind?: 'ok' | 'err') => void>(() => undefined);
export const useToast = () => useContext(ToastContext);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: 'ok' | 'err' = 'ok') => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'err' ? 8000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind === 'err' ? 'err-t' : ''}`}>
            <span>{t.text}</span>
            <button type="button" aria-label="Dismiss" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

/* ------------------------------------------------------------------ */
/* Pagination footer                                                   */
/* ------------------------------------------------------------------ */

export const Pager: React.FC<{
  page: number;
  perPage: number;
  total: number;
  onPage: (p: number) => void;
  onPerPage?: (n: number) => void;
  noun?: string;
}> = ({ page, perPage, total, onPage, onPerPage, noun = '' }) => {
  const pages = Math.max(1, Math.ceil(total / perPage));
  const from = total === 0 ? 0 : (page - 1) * perPage + 1;
  const to = Math.min(total, page * perPage);
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 20px', fontSize: 14, flexWrap: 'wrap', gap: 10 }}>
      <span className="muted">
        {from.toLocaleString()} – {to.toLocaleString()} of {total.toLocaleString()} {noun}
      </span>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        {onPerPage && (
          <SelectMenu
            label="Rows per page"
            value={String(perPage)}
            options={['10', '20', '50', '100'].map((v) => ({ value: v, label: `${v} per page` }))}
            onChange={(v) => onPerPage(Number(v))}
          />
        )}
        <button type="button" className="btn bg" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          ‹
        </button>
        <span style={{ padding: '0 8px' }}>
          {page} / {pages}
        </span>
        <button type="button" className="btn bg" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
          ›
        </button>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Copy helper                                                         */
/* ------------------------------------------------------------------ */

export const copyText = async (text: string): Promise<boolean> => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
};

/** R1-025: memory-context token counts are estimates, never provider usage. */
export const TOKEN_ESTIMATE_NOTE =
  'Estimated at about 4 characters per token. Real model usage and cost on the agent host are not visible to MemoryHub; reads, writes and search do not call an LLM.';

export const Tokens: React.FC<{ n: number | null | undefined; short?: boolean }> = ({ n, short }) => (
  <abbr className="est" title={TOKEN_ESTIMATE_NOTE}>
    ≈{n === null || n === undefined ? '—' : n.toLocaleString('en-US')} {short ? 'tok' : 'tokens'}
  </abbr>
);
