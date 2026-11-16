import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/api/client';
import { useApi } from '@/hooks/useApi';
import type { DirectoryEntry } from '@/types';
import { avatarColor, initials } from '@/utils/format';
import { Icon } from './ui';

const KIND_LABEL: Record<DirectoryEntry['kind'], string> = { person: 'People', agent: 'Agents', service: 'Service agents' };

/**
 * Pick people and agents from the directory (/api/directory) instead of typing
 * IDs. Multi-select shows chips; single-select closes on pick. Already-added
 * IDs are listed but disabled. Someone not in the directory yet (an OpenShift
 * user who never signed in) can still be added from the search text.
 */
export const PeoplePicker: React.FC<{
  id: string;
  value: string[];
  onChange: (ids: string[]) => void;
  multiple?: boolean;
  exclude?: string[];
  excludeNote?: string;
  kinds?: DirectoryEntry['kind'][];
  placeholder?: string;
  autoFocus?: boolean;
}> = ({ id, value, onChange, multiple = true, exclude = [], excludeNote = 'already a member', kinds, placeholder = 'Choose people or agents', autoFocus }) => {
  const { data, loading } = useApi(() => api.directory(), []);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', away);
    window.setTimeout(() => search.current?.focus(), 0);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);

  const all = useMemo(() => (data?.items ?? []).filter((p) => !kinds || kinds.includes(p.kind)), [data, kinds]);
  const byId = useMemo(() => new Map(all.map((p) => [p.id, p])), [all]);
  const needle = q.trim().toLowerCase();
  const matches = all.filter((p) => !needle || p.id.toLowerCase().includes(needle) || p.name.toLowerCase().includes(needle) || (p.owner ?? '').toLowerCase().includes(needle));
  const typed = q.trim();
  const canAddTyped = !!typed && /^[A-Za-z0-9][A-Za-z0-9._@-]*$/.test(typed) && !byId.has(typed) && !value.includes(typed) && !exclude.includes(typed);
  const options: (DirectoryEntry & { typed?: boolean })[] = [...matches, ...(canAddTyped ? [{ id: typed, name: typed, kind: 'person' as const, owner: null, typed: true }] : [])];
  const selectable = options.filter((o) => !exclude.includes(o.id));

  const toggle = (pid: string) => {
    if (exclude.includes(pid)) return;
    if (multiple) onChange(value.includes(pid) ? value.filter((x) => x !== pid) : [...value, pid]);
    else {
      onChange([pid]);
      setOpen(false);
    }
    setQ('');
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      setOpen(false);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, selectable.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const pick = selectable[active];
      if (pick) toggle(pick.id);
    } else if (e.key === 'Backspace' && !q && multiple && value.length) {
      onChange(value.slice(0, -1));
    }
  };

  const label = (pid: string) => {
    const p = byId.get(pid);
    return p && p.name !== p.id ? `${p.name} (${p.id})` : pid;
  };

  let lastKind = '';
  return (
    <div className="pp" ref={box}>
      <button
        type="button"
        id={id}
        className={`in pp-field ${open ? 'on' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        autoFocus={autoFocus}
      >
        <span className={value.length ? '' : 'muted'} style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textAlign: 'left' }}>
          {value.length === 0 ? placeholder : multiple ? `${value.length} selected — add more` : label(value[0])}
        </span>
        <Icon.Chevron />
      </button>
      {multiple && value.length > 0 && (
        <div className="pp-chips">
          {value.map((pid) => (
            <span key={pid} className="chip">
              {label(pid)}
              <button type="button" aria-label={`Remove ${pid}`} onClick={() => onChange(value.filter((x) => x !== pid))}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {open && (
        <div className="pp-pop" onKeyDown={onKey}>
          <div className="pp-search">
            <Icon.Search size={14} />
            <input
              ref={search}
              className="in"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setActive(0);
              }}
              placeholder="Search by name or ID"
              aria-label="Search people and agents"
              aria-controls={`${id}-list`}
            />
          </div>
          <ul className="pp-list" role="listbox" id={`${id}-list`} aria-multiselectable={multiple} aria-label="People and agents">
            {loading && !data && <li className="pp-empty">Loading…</li>}
            {!loading && options.length === 0 && <li className="pp-empty">Nobody matches “{typed}”.</li>}
            {options.map((o) => {
              const header = !o.typed && o.kind !== lastKind ? KIND_LABEL[o.kind] : null;
              if (!o.typed) lastKind = o.kind;
              const taken = exclude.includes(o.id);
              const chosen = value.includes(o.id);
              const idx = selectable.indexOf(o);
              return (
                <React.Fragment key={`${o.kind}-${o.id}`}>
                  {header && <li className="pp-head" role="presentation">{header}</li>}
                  <li
                    role="option"
                    aria-selected={chosen}
                    aria-disabled={taken}
                    className={`pp-opt ${idx === active ? 'act' : ''} ${taken ? 'off' : ''}`}
                    onMouseEnter={() => idx >= 0 && setActive(idx)}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => toggle(o.id)}
                  >
                    {multiple && <input type="checkbox" readOnly tabIndex={-1} checked={chosen || taken} disabled={taken} aria-hidden="true" />}
                    <span className="mav" style={{ background: avatarColor(o.id) }} aria-hidden="true">
                      {initials(o.name)}
                    </span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      {o.typed ? (
                        <>
                          Add “<b>{o.id}</b>”<span className="hint" style={{ display: 'block' }}>Not signed in yet — added by ID</span>
                        </>
                      ) : (
                        <>
                          <span className="pp-name">{o.name}</span>
                          <span className="hint" style={{ display: 'block' }}>
                            {o.name !== o.id ? <span className="mono">{o.id}</span> : null}
                            {o.owner ? `${o.name !== o.id ? ' · ' : ''}${o.owner}'s agent` : ''}
                            {taken ? `${o.name !== o.id || o.owner ? ' · ' : ''}${excludeNote}` : ''}
                          </span>
                        </>
                      )}
                    </span>
                    {chosen && !multiple && <span aria-hidden="true">✓</span>}
                  </li>
                </React.Fragment>
              );
            })}
          </ul>
          {multiple && value.length > 0 && (
            <div className="pp-foot">
              <span className="sm muted">{value.length} selected</span>
              <button type="button" className="btn bl sm" onClick={() => setOpen(false)}>
                Done
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
