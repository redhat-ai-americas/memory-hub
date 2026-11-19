import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api, AUTHORIZATION_CHANGED_EVENT } from '@/api/client';
import type { Me, Role } from '@/types';
import { buildHash, navigate } from '@/hooks/useHashRoute';
import { Dropdown, Icon } from './ui';

/* ------------------------------------------------------------------ */
/* App-wide context: who is viewing, tenant, memory presence           */
/* ------------------------------------------------------------------ */

export interface AppState {
  me: Me | null;
  /** Viewer role from /api/me: the BFF knows only 'user' and 'admin'. 'operator' until it answers. */
  role: Role;
  tenant: string;
  /** null until the first count arrives. */
  memoryCount: number | null;
  /** True while the tenant has no memories yet (standby mode). */
  standby: boolean;
  /** Open contradiction reports this admin may resolve (/api/nav-counts review_queue). */
  reviewCount: number;
  refreshCounts: () => void;
}

const AppContext = createContext<AppState>({
  me: null,
  role: 'operator',
  tenant: '',
  memoryCount: null,
  standby: false,
  reviewCount: 0,
  refreshCounts: () => undefined,
});
export const useApp = () => useContext(AppContext);

const POLL_EMPTY_MS = 5000;
const POLL_IDLE_MS = 60000;
const POLL_ACCESS_MS = 15000;

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [me, setMe] = useState<Me | null>(null);
  const [accessCheck, setAccessCheck] = useState(0);
  const [accessError, setAccessError] = useState(false);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [reviewCount, setReviewCount] = useState(0);
  const [token, setToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.me().then((viewer) => {
      if (cancelled) return;
      setMe(viewer);
      setAccessError(false);
    }).catch(() => {
      if (cancelled) return;
      setMe(null);
      setAccessError(true);
    });
    return () => { cancelled = true; };
  }, [accessCheck]);

  // Project memberships and admin rights can change at any time: ask /api/me again.
  useEffect(() => {
    const refresh = () => setAccessCheck((value) => value + 1);
    const visible = () => { if (document.visibilityState === 'visible') refresh(); };
    const storage = (event: StorageEvent) => { if (event.key === AUTHORIZATION_CHANGED_EVENT) refresh(); };
    const interval = window.setInterval(refresh, POLL_ACCESS_MS);
    window.addEventListener('focus', refresh);
    window.addEventListener('storage', storage);
    window.addEventListener(AUTHORIZATION_CHANGED_EVENT, refresh);
    document.addEventListener('visibilitychange', visible);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener('focus', refresh);
      window.removeEventListener('storage', storage);
      window.removeEventListener(AUTHORIZATION_CHANGED_EVENT, refresh);
      document.removeEventListener('visibilitychange', visible);
    };
  }, []);

  // Remount every screen on an authorization change to discard cached content.
  const authorizationKey = JSON.stringify([me?.tenant_id, me?.username, me?.role, me?.access, me?.write]);

  useEffect(() => {
    if (!me) return;
    let cancelled = false;
    api
      .navCounts()
      .then((c) => {
        if (cancelled) return;
        setMemoryCount(c.memories);
        setReviewCount(c.review_queue);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [token, authorizationKey]);

  // Poll every 5 s while waiting for the first write_memory, then slowly.
  useEffect(() => {
    const id = window.setInterval(() => setToken((t) => t + 1), memoryCount === 0 ? POLL_EMPTY_MS : POLL_IDLE_MS);
    return () => window.clearInterval(id);
  }, [memoryCount]);

  const refreshCounts = useCallback(() => setToken((t) => t + 1), []);
  return (
    <AppContext.Provider
      value={{
        me,
        role: me?.role ?? 'operator',
        tenant: me?.tenant_id ?? '',
        memoryCount,
        standby: memoryCount === 0,
        reviewCount,
        refreshCounts,
      }}
    >
      {me ? <React.Fragment key={authorizationKey}>{children}</React.Fragment> : (
        <div className="body" role="status">
          {accessError ? 'Unable to verify your access. Retrying…' : 'Checking access…'}
          {accessError && <button className="btn bg" onClick={() => setAccessCheck((value) => value + 1)}>Retry</button>}
        </div>
      )}
    </AppContext.Provider>
  );
};

/* ------------------------------------------------------------------ */
/* Navigation                                                          */
/* ------------------------------------------------------------------ */

export interface NavItem {
  path: string;
  label: string;
  badge?: 'review';
}
type NavSection = { group?: string; items: NavItem[] };

/**
 * The user's menu: the memories they may read, their projects, their agents
 * and personal curation rules (backend-admin-user-roles: role "user").
 */
export const USER_NAV: NavSection[] = [
  { items: [{ path: '/overview', label: 'Overview' }] },
  {
    group: 'My memory',
    items: [
      { path: '/memories', label: 'Memory browser' },
      { path: '/search', label: 'Search playground' },
      { path: '/entities', label: 'Entities' },
    ],
  },
  { group: 'Work', items: [{ path: '/projects', label: 'Projects' }] },
  {
    group: 'Agents',
    items: [
      { path: '/identities', label: 'My agents & API keys' },
      { path: '/curation', label: 'My curation rules' },
    ],
  },
];

/** Old user screens and where they live now (the hub path and its view). */
export const USER_MOVED: Record<string, { path: string; view: string }> = {
  '/clients': { path: '/identities', view: 'keys' },
};

/** The platform admin's menu (role "admin"): personal memories stay metadata only. */
export const ADMIN_NAV: NavSection[] = [
  { items: [{ path: '/overview', label: 'Tenant overview' }] },
  {
    group: 'People & access',
    items: [
      { path: '/identities', label: 'Agents & identities' },
      { path: '/clients', label: 'OAuth clients & keys' },
    ],
  },
  { group: 'Work', items: [{ path: '/projects', label: 'Projects' }] },
  {
    group: 'Governance',
    items: [
      { path: '/memories', label: 'Content moderation' },
      { path: '/review', label: 'Contradictions', badge: 'review' },
      { path: '/curation', label: 'Curation rules' },
    ],
  },
];

/** Every screen, for routing before /api/me answers. */
export const NAV: NavSection[] = [...USER_NAV, ...ADMIN_NAV];

/** Admin screens reachable by link only. */
const ADMIN_LINK_ONLY = ['/search'];

/** Where a moved screen lives for this role, if it moved. */
export const movedFor = (role: Role, path: string) => (role === 'user' ? USER_MOVED[path] : undefined);

export const canSee = (path: string, role: Role) =>
  role === 'admin'
    ? ADMIN_NAV.some((s) => s.items.some((i) => i.path === path)) || ADMIN_LINK_ONLY.includes(path)
    : role === 'user'
      ? USER_NAV.some((s) => s.items.some((i) => i.path === path)) || path in USER_MOVED
      : true;

export const navFor = (role: Role): NavSection[] => (role === 'admin' ? ADMIN_NAV : USER_NAV);

export const ROLE_LABEL: Record<Role, string> = { admin: 'Platform admin', user: 'User', operator: 'Signing in' };

const NAV_PREF = 'memoryhub.navOpen';
const readNavPref = () => {
  try {
    return window.localStorage.getItem(NAV_PREF) !== 'false';
  } catch {
    return true;
  }
};

export const Shell: React.FC<{ activePath: string; children: React.ReactNode }> = ({ activePath, children }) => {
  const { me, role, tenant, reviewCount } = useApp();
  const narrow = () => window.innerWidth < 960;
  const [open, setOpen] = useState<boolean>(() => (narrow() ? false : readNavPref()));

  useEffect(() => {
    if (narrow()) setOpen(false);
  }, [activePath]);

  const toggle = () => {
    setOpen((o) => {
      const next = !o;
      if (!narrow()) {
        try {
          window.localStorage.setItem(NAV_PREF, String(next));
        } catch {
          /* storage unavailable */
        }
      }
      return next;
    });
  };

  /** POST /api/auth/logout answers with the oauth-proxy sign-out URL. */
  const onLogout = async () => {
    let target = '/oauth/sign_out';
    try {
      const res = await api.logout();
      if (res.redirect) target = res.redirect;
    } catch {
      /* still leave the app */
    }
    try {
      window.sessionStorage.clear();
    } catch {
      /* storage unavailable */
    }
    window.location.replace(target);
  };

  return (
    <div>
      <header className="mast">
        <button type="button" className="icb" aria-label={open ? 'Hide navigation' : 'Show navigation'} aria-expanded={open} onClick={toggle}>
          <Icon.Menu />
        </button>
        <a className="brand" href={buildHash('/overview')}>
          <span className="mark">
            <Icon.Mark />
          </span>
          <span className="wm">
            MemoryHub<small>for OpenShift AI</small>
          </span>
        </a>
        {role !== 'operator' && (
          <span
            className={`role-pill ${role}`}
            title={role === 'admin' ? 'You moderate every scope except user; personal memories show metadata only' : 'You see memories you are allowed to read'}
          >
            {ROLE_LABEL[role]}
          </span>
        )}
        {tenant && (
          <span className="ctx" title="Each dashboard deployment serves one tenant (MEMORYHUB_UI_TENANT_ID)">
            Tenant: {tenant}
          </span>
        )}
        <div className="mast-r">
          {role === 'user' && (
            <a className="icb" aria-label="Search memories" href={buildHash('/search')}>
              <Icon.Search />
            </a>
          )}
          <Dropdown
            align="right"
            toggle={(p) => (
              <button type="button" className="who" {...p}>
                <span className="av">{me?.initials ?? '··'}</span>
                {me?.name ?? ''}
                <span className="vh"> · account menu</span>
              </button>
            )}
          >
            {() => (
              <>
                <div className="mh">
                  {me ? `Signed in as ${me.username}` : 'Not signed in'}
                  <br />
                  <span className="muted sm">{ROLE_LABEL[role]}</span>
                </div>
                {me && (
                  <button type="button" onClick={onLogout}>
                    Log out
                  </button>
                )}
              </>
            )}
          </Dropdown>
        </div>
      </header>
      <div className={`shell ${open ? 'nav-open' : 'nav-closed'}`}>
        <nav className="nav" aria-label="Primary">
          {navFor(role).map((section, i) => (
            <React.Fragment key={section.group ?? i}>
              {section.group && <div className="ng">{section.group}</div>}
              {section.items.map((item) => (
                <a key={item.path} href={buildHash(item.path)} className={activePath === item.path ? 'on' : ''} aria-current={activePath === item.path ? 'page' : undefined}>
                  {item.label}
                  {item.badge === 'review' && reviewCount > 0 && <span className="cnt">{reviewCount}</span>}
                </a>
              ))}
            </React.Fragment>
          ))}
        </nav>
        <main className="main">{children}</main>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Page header                                                         */
/* ------------------------------------------------------------------ */

export const PageHeader: React.FC<{
  title: React.ReactNode;
  crumbs?: { label: React.ReactNode; href?: string }[];
  description?: React.ReactNode;
  actions?: React.ReactNode;
  tabs?: React.ReactNode;
  long?: boolean;
  topAlign?: boolean;
  below?: React.ReactNode;
}> = ({ title, crumbs, description, actions, tabs, long, topAlign, below }) => {
  const embed = useContext(EmbedContext);
  if (embed) {
    // Inside a hub (My activity, My agents & API keys): the hub owns the page
    // title and crumbs; the screen keeps its own description, actions and tabs.
    return (
      <div className="ph-sub">
        <div className="ph-row">
          <div style={{ minWidth: 0, flex: '1 1 420px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            {embed.showTitle && <h2>{title}</h2>}
            {description && <p className="desc">{description}</p>}
            {below}
            {tabs}
          </div>
          {actions && <div className="ph-actions">{actions}</div>}
        </div>
      </div>
    );
  }
  return (
  <div className={`ph ${tabs ? 'has-tabs' : ''}`}>
    <div className="crumbs">
      <CrumbRoot />
      {(crumbs ?? [{ label: title }]).map((c, i) => (
        <React.Fragment key={i}>
          <span>/</span>
          {c.href ? <a href={c.href}>{c.label}</a> : <span>{c.label}</span>}
        </React.Fragment>
      ))}
    </div>
    <div className={`ph-row ${topAlign ? 'top' : ''}`}>
      <div style={{ minWidth: 0, flex: topAlign ? '1 1 520px' : undefined }}>
        <h1 className={long ? 'long' : ''}>{title}</h1>
        {description && <p className="desc">{description}</p>}
        {below}
      </div>
      {actions && <div className="ph-actions">{actions}</div>}
    </div>
    {tabs}
  </div>
  );
};

const CrumbRoot: React.FC = () => <a href={buildHash('/overview')}>MemoryHub</a>;

/** Set by a hub around the screens it embeds. */
export const EmbedContext = createContext<{ showTitle: boolean } | null>(null);

/**
 * A hub page: one menu item that holds several screens as views. The view is
 * kept in the `view` URL parameter so every screen keeps its own parameters.
 */
export function Hub<T extends string>({
  title,
  description,
  actions,
  route,
  views,
  fallback,
}: {
  title: string;
  description: React.ReactNode;
  actions?: React.ReactNode;
  route: { path: string; params: URLSearchParams };
  views: { value: T; label: string; count?: number | string | null; render: () => React.ReactNode; showTitle?: boolean }[];
  fallback: T;
}) {
  const requested = route.params.get('view') as T | null;
  const current = views.find((v) => v.value === requested) ?? views.find((v) => v.value === fallback)!;
  const go = (v: T) => {
    // Each view starts clean: its own filters and tabs belong to it.
    navigate(route.path, v === fallback ? undefined : { view: v });
  };
  return (
    <>
      <PageHeader
        title={title}
        description={description}
        actions={actions}
        tabs={<Tabs label={title} value={current.value} onChange={go} tabs={views.map(({ value, label, count }) => ({ value, label, count }))} />}
      />
      <EmbedContext.Provider value={{ showTitle: Boolean(current.showTitle) }}>
        <React.Fragment key={current.value}>{current.render()}</React.Fragment>
      </EmbedContext.Provider>
    </>
  );
}

export function Tabs<T extends string>({
  value,
  tabs,
  onChange,
  label,
  inCard,
}: {
  value: T;
  tabs: { value: T; label: string; count?: number | string | null }[];
  onChange: (v: T) => void;
  label: string;
  inCard?: boolean;
}) {
  const embedded = useContext(EmbedContext);
  if (embedded && !inCard) {
    // Inside a hub the hub's tabs are the only tab row; a screen's own tabs
    // become a segmented filter so the page never shows two rows of tabs.
    return (
      <div className="seg sub-seg" role="tablist" aria-label={label}>
        {tabs.map((t) => (
          <button key={t.value} type="button" role="tab" aria-selected={t.value === value} className={t.value === value ? 'on' : ''} onClick={() => onChange(t.value)}>
            {t.label}
            {t.count !== undefined && t.count !== null && <span className="cnt-s">{typeof t.count === 'number' ? t.count.toLocaleString() : t.count}</span>}
          </button>
        ))}
      </div>
    );
  }
  return (
    <nav className={`tabs ${inCard ? 'in-card' : ''}`} aria-label={label} role="tablist">
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          role="tab"
          aria-selected={t.value === value}
          className={`tab ${t.value === value ? 'on' : ''}`}
          onClick={() => onChange(t.value)}
        >
          {t.label}
          {t.count !== undefined && t.count !== null && <span className="muted"> {typeof t.count === 'number' ? t.count.toLocaleString() : t.count}</span>}
        </button>
      ))}
    </nav>
  );
}

/* ------------------------------------------------------------------ */
/* Notifications (the bell)                                            */
/* ------------------------------------------------------------------ */
