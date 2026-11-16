import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api, AUTHORIZATION_CHANGED_EVENT } from '@/api/client';
import type { BreakGlassGrant, Me, NavFeatures, NotificationsResponse, Role, SwitchTargets } from '@/types';
import { buildHash, navigate } from '@/hooks/useHashRoute';
import { platform } from '@/api/platform';
import { Dropdown, Icon } from './ui';

const REPO_URL = 'https://github.com/redhat-ai-americas/memory-hub';

/* ------------------------------------------------------------------ */
/* App-wide context: who is viewing, tenant, memory presence           */
/* ------------------------------------------------------------------ */

export interface AppState {
  me: Me | null;
  /** Viewer role; 'operator' until /api/me answers and in open development mode.
   * A super-user works as an admin here; ``superuser`` says they are one. */
  role: Role;
  superuser: boolean;
  tenant: string;
  /** null until the first count arrives. */
  memoryCount: number | null;
  /** True while the tenant has no memories yet (standby mode). */
  standby: boolean;
  reviewCount: number;
  /** Which content-backed tabs have something in them (null until loaded). */
  features: NavFeatures | null;
  refreshCounts: () => void;
  /** Super Admin: the tenant whose Tenant Console is open (null = Platform Operations). */
  tenantContext: TenantContext | null;
  /** Super Admin outside a tenant context: the Platform Operations menu. */
  platformMode: boolean;
  enterTenant: (tenant: string, reason: string) => void;
  exitTenant: () => void;
}

export interface TenantContext {
  tenant: string;
  reason: string;
  since: string;
}
const CTX_KEY = 'memoryhub.tenantContext';
const readCtx = (): TenantContext | null => {
  try {
    const raw = window.sessionStorage.getItem(CTX_KEY);
    return raw ? (JSON.parse(raw) as TenantContext) : null;
  } catch {
    return null;
  }
};

const AppContext = createContext<AppState>({
  me: null,
  role: 'operator',
  superuser: false,
  tenant: '',
  memoryCount: null,
  standby: false,
  reviewCount: 0,
  features: null,
  refreshCounts: () => undefined,
  tenantContext: null,
  platformMode: false,
  enterTenant: () => undefined,
  exitTenant: () => undefined,
});
export const useApp = () => useContext(AppContext);

const POLL_EMPTY_MS = 5000;
const POLL_IDLE_MS = 60000;
const POLL_ACCESS_MS = 15000;

function expireGrant(viewer: Me): Me {
  const grant = viewer.access?.break_glass;
  if (!grant || Date.parse(grant.expires_at) > Date.now()) return viewer;
  return { ...viewer, access: { hidden_scopes: [...new Set([...(viewer.access?.hidden_scopes ?? []), 'user'])], break_glass: null } };
}

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [me, setMe] = useState<Me | null>(null);
  const [accessCheck, setAccessCheck] = useState(0);
  const [accessError, setAccessError] = useState(false);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [reviewCount, setReviewCount] = useState(0);
  const [token, setToken] = useState(0);
  const [features, setFeatures] = useState<NavFeatures | null>(null);
  // Which /api/me request produced `me`, and from which request on a tenant context must be confirmed.
  const [meFrom, setMeFrom] = useState(-1);
  const [ctxFrom, setCtxFrom] = useState(0);
  const accessRef = useRef(0);
  accessRef.current = accessCheck;

  useEffect(() => {
    let cancelled = false;
    const at = accessCheck;
    api.me().then((viewer) => {
      if (cancelled) return;
      setMe(expireGrant(viewer));
      setMeFrom(at);
      setAccessError(false);
    }).catch(() => {
      if (cancelled) return;
      setMe(null);
      setAccessError(true);
    });
    return () => { cancelled = true; };
  }, [accessCheck]);

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

  const grantExpiry = me?.access?.break_glass?.expires_at;
  useEffect(() => {
    if (!grantExpiry) return;
    const timer = window.setTimeout(() => {
      // Remove content locally even if the next network request fails.
      setMe((viewer) => viewer ? expireGrant(viewer) : null);
      setAccessCheck((value) => value + 1);
    }, Math.max(0, Date.parse(grantExpiry) - Date.now()));
    return () => window.clearTimeout(timer);
  }, [grantExpiry]);

  // Remount every screen on an authorization change to discard cached content.
  const authorizationKey = JSON.stringify([me?.tenant_id, me?.username, me?.role, me?.real_username, me?.access, me?.write]);

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
    api
      .navFeatures()
      .then((f) => !cancelled && setFeatures(f))
      .catch(() => !cancelled && setFeatures({}));
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
  const [tenantContext, setTenantContext] = useState<TenantContext | null>(readCtx);
  const enterTenant = useCallback((tenant: string, reason: string) => {
    const ctx = { tenant, reason, since: new Date().toISOString() };
    try {
      window.sessionStorage.setItem(CTX_KEY, JSON.stringify(ctx));
    } catch {
      /* storage unavailable */
    }
    setTenantContext(ctx);
    // Ask the server again: the console is kept only if /api/me answers for this tenant.
    setCtxFrom(accessRef.current + 1);
    setAccessCheck((value) => value + 1);
    navigate('/overview');
  }, []);
  const exitTenant = useCallback(() => {
    try {
      window.sessionStorage.removeItem(CTX_KEY);
    } catch {
      /* storage unavailable */
    }
    setTenantContext(null);
    navigate('/platform');
  }, []);
  const isSuper = me?.role === 'superuser';
  // The tenant shown in the console is the server's, never only the browser's: a stored context
  // that /api/me does not confirm is dropped and the Super Admin returns to Platform Operations.
  useEffect(() => {
    if (!me || !tenantContext || meFrom < ctxFrom) return;
    if (me.role === 'superuser' && me.tenant_id === tenantContext.tenant) return;
    try {
      window.sessionStorage.removeItem(CTX_KEY);
    } catch {
      /* storage unavailable */
    }
    setTenantContext(null);
    if (me.role === 'superuser') navigate('/platform', undefined, { replace: true });
  }, [me, meFrom, ctxFrom, tenantContext]);
  const confirmedCtx = isSuper && tenantContext && meFrom >= ctxFrom && me?.tenant_id === tenantContext.tenant ? tenantContext : null;
  const pendingCtx = isSuper && tenantContext && meFrom < ctxFrom ? tenantContext : null;
  return (
    <AppContext.Provider
      value={{
        me,
        role: me?.role === 'superuser' ? 'admin' : (me?.role ?? 'operator'),
        superuser: me?.role === 'superuser',
        tenant: me?.tenant_id ?? '',
        memoryCount,
        standby: memoryCount === 0,
        reviewCount,
        features,
        refreshCounts,
        tenantContext: confirmedCtx ?? pendingCtx,
        platformMode: isSuper && !(confirmedCtx ?? pendingCtx),
        enterTenant,
        exitTenant,
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
  /** Roles that see this item; all roles when omitted. */
  roles?: Role[];
  /** Label override per role. */
  labelFor?: Partial<Record<Role, string>>;
  /**
   * Shown only once the tab has content (any of these counts > 0), so the
   * menu never offers empty pages. Direct links keep working.
   */
  feature?: Partial<Record<Role, (keyof NavFeatures)[]>>;
  /** Beyond Release 1: shown only with MemoryHub Labs on (MEMORYHUB_UI_LABS). */
  labs?: boolean;
  /** #667: super-users only (incident access to user memories). */
  superuser?: boolean;
}

const ADMIN: Role[] = ['admin', 'operator'];
const USER: Role[] = ['user', 'operator'];

/**
 * #667 tiers. Users work with the memories they may read; platform admins run
 * the platform and moderate every scope except user (personal memories are
 * metadata only); super-users are admins who can also open user memories for
 * an incident. The open-mode operator (no sign-in configured) sees everything.
 */
export const NAV: { group?: string; groupFor?: Partial<Record<Role, string>>; items: NavItem[] }[] = [
  { items: [{ path: '/overview', label: 'Overview', labelFor: { user: 'My overview', admin: 'Platform overview' } }] },
  {
    group: 'Memory',
    groupFor: { admin: 'Memory · personal hidden', user: 'My memory' },
    items: [
      { path: '/memories', label: 'Memory browser', labelFor: { admin: 'Content moderation' } },
      {
        path: '/knowledge',
        label: 'Knowledge',
        roles: USER,
        labs: true,
        feature: { user: ['knowledge', 'documents', 'packs'], operator: ['knowledge', 'documents', 'packs'] },
      },
      { path: '/entities', label: 'Entities', roles: USER },
      // QA 2026-11-10 BR-PA-05: the backend serves admins (admin-readable scopes,
      // never personal memories without an incident grant), so the screen is open to them.
      { path: '/search', label: 'Search playground', roles: [...USER, 'admin'] },
      { path: '/hygiene', label: 'Dreaming', roles: USER, labs: true },
      { path: '/projects', label: 'Projects & teams' },
    ],
  },
  {
    group: 'Governance',
    groupFor: { user: 'My governance' },
    items: [
      { path: '/review', label: 'Review queue', badge: 'review', labelFor: { user: 'Review requests' } },
      { path: '/curation', label: 'Curation rules', labelFor: { user: 'My curation rules' } },
      {
        path: '/quality',
        label: 'Retrieval quality',
        labelFor: { user: 'Retrieval checks', admin: 'Retrieval health' },
        labs: true,
        feature: { user: ['checks', 'check_runs'], operator: ['checks', 'check_runs', 'search_runs'], admin: ['search_runs'] },
      },
      { path: '/reads', label: 'Who read my memories', roles: USER },
      { path: '/audit', label: 'Audit & forensics', roles: [...ADMIN, 'user'], labelFor: { user: 'My activity' } },
      { path: '/incident', label: 'Incident access', roles: ['admin'], superuser: true },
    ],
  },
  {
    group: 'Access',
    groupFor: { user: 'Agents' },
    items: [
      { path: '/accounts', label: 'Accounts & sign-up', roles: ADMIN },
      { path: '/connect', label: 'Connect an agent', roles: USER },
      { path: '/verify', label: 'Connection check', roles: USER },
      { path: '/identities', label: 'Users & agents', labelFor: { user: 'My agents' } },
      { path: '/clients', label: 'OAuth clients & keys', labelFor: { user: 'Agent credentials' } },
    ],
  },
  {
    group: 'Platform',
    groupFor: { user: 'Account' },
    items: [
      { path: '/operations', label: 'Operations', labelFor: { user: 'Background jobs' }, feature: { user: ['jobs'], admin: ['jobs'], operator: ['jobs'] } },
      { path: '/settings', label: 'Settings', roles: ADMIN },
      { path: '/preferences', label: 'Preferences & privacy', roles: USER },
    ],
  },
];

/**
 * The user's menu. Screens that used to have their own item live inside a
 * hub now: My activity collects the log, readers, background jobs, retrieval
 * checks and incident notices; My agents & API keys joins agents, keys,
 * connecting an agent and the connection check.
 */
export const USER_NAV: { group?: string; items: NavItem[] }[] = [
  { items: [{ path: '/overview', label: 'Overview' }] },
  {
    group: 'My memory',
    items: [
      { path: '/memories', label: 'Memory browser' },
      { path: '/search', label: 'Search playground' },
      { path: '/knowledge', label: 'Knowledge', labs: true },
      { path: '/hygiene', label: 'Dreaming', labs: true },
      { path: '/entities', label: 'Entities' },
    ],
  },
  {
    group: 'Work',
    items: [
      { path: '/audit', label: 'My activity' },
      { path: '/review', label: 'My requests' },
      { path: '/projects', label: 'Projects & teams' },
    ],
  },
  {
    group: 'Agents',
    items: [
      { path: '/identities', label: 'My agents & API keys' },
      { path: '/curation', label: 'My curation rules' },
    ],
  },
  { group: 'Account', items: [{ path: '/preferences', label: 'Preferences & privacy' }] },
];

/** Old user screens and where they live now (the hub path and its view). */
export const USER_MOVED: Record<string, { path: string; view: string }> = {
  '/reads': { path: '/audit', view: 'reads' },
  '/connect': { path: '/identities', view: 'connect' },
  '/verify': { path: '/identities', view: 'verify' },
  '/operations': { path: '/audit', view: 'jobs' },
  '/quality': { path: '/audit', view: 'checks' },
  '/clients': { path: '/identities', view: 'keys' },
};

/** The platform admin's menu (super-users get Incident access as well). */
export const ADMIN_NAV: { group?: string; items: NavItem[] }[] = [
  { items: [{ path: '/overview', label: 'Tenant overview' }] },
  {
    group: 'People & access',
    items: [
      { path: '/accounts', label: 'Users & access' },
      { path: '/identities', label: 'Agents & identities' },
      { path: '/clients', label: 'OAuth clients & keys' },
    ],
  },
  { group: 'Work', items: [{ path: '/projects', label: 'Projects & teams' }] },
  {
    group: 'Governance',
    items: [
      { path: '/memories', label: 'Content moderation' },
      { path: '/review', label: 'Review queue', badge: 'review' },
      { path: '/curation', label: 'Curation & compaction' },
      { path: '/incident', label: 'Incident access', superuser: true },
    ],
  },
  {
    group: 'Insight',
    items: [
      { path: '/audit', label: 'Audit & forensics' },
      { path: '/quality', label: 'Retrieval health & operations' },
    ],
  },
  { group: 'Tenant', items: [{ path: '/settings', label: 'Tenant settings' }] },
];

/** The Super Admin's Platform Operations menu (outside a tenant context). */
export const SUPER_NAV: { group?: string; items: NavItem[] }[] = [
  { items: [{ path: '/platform', label: 'Global overview' }] },
  {
    group: 'Platform',
    items: [
      { path: '/tenants', label: 'Tenants' },
      { path: '/admins', label: 'Administrators' },
      { path: '/platform-health', label: 'Platform health & deployments' },
    ],
  },
  {
    group: 'Control',
    items: [
      { path: '/policies', label: 'Global policies & models' },
      { path: '/security', label: 'Security center' },
      { path: '/global-audit', label: 'Global audit' },
    ],
  },
  { group: 'Privileged access', items: [{ path: '/incident', label: 'Incident access' }] },
  { group: 'Optional module', items: [{ path: '/runbooks', label: 'Operations knowledge' }] },
];
const SUPER_LINK_ONLY = ['/incident-request', '/grant'];

/** Admin screens without their own menu item: where they live now, or reachable by link only. */
export const ADMIN_MOVED: Record<string, { path: string; view: string }> = {
  '/operations': { path: '/quality', view: 'jobs' },
};
const ADMIN_LINK_ONLY = ['/search', '/graph'];

/** Where a moved screen lives for this role, if it moved. */
export const movedFor = (role: Role, path: string) => (role === 'user' ? USER_MOVED[path] : role === 'admin' ? ADMIN_MOVED[path] : undefined);

export const canSee = (path: string, role: Role, superuser = false, platformMode = false) =>
  platformMode
    ? SUPER_NAV.some((s) => s.items.some((i) => i.path === path)) || SUPER_LINK_ONLY.includes(path)
    : role === 'admin'
    ? ADMIN_NAV.some((s) => s.items.some((i) => i.path === path && (!i.superuser || superuser))) || path in ADMIN_MOVED || ADMIN_LINK_ONLY.includes(path)
    : role === 'user'
    ? USER_NAV.some((s) => s.items.some((i) => i.path === path)) || path in USER_MOVED
    : NAV.some((s) => s.items.some((i) => i.path === path && (!i.roles || i.roles.includes(role)) && (!i.superuser || superuser)));

const hasContent = (item: NavItem, role: Role, features: NavFeatures | null) => {
  const keys = item.feature?.[role];
  if (!keys) return true;
  return !!features && keys.some((k) => (features[k] ?? 0) > 0);
};

export const isLabsPath = (path: string, role?: Role) =>
  (role === 'user' ? USER_NAV : role === 'admin' ? ADMIN_NAV : NAV).some((s) => s.items.some((i) => i.path === path && i.labs));

export const navFor = (role: Role, features: NavFeatures | null = null, labs = false, superuser = false, platformMode = false) =>
  platformMode
    ? SUPER_NAV
    : role === 'user'
    ? USER_NAV.map((s) => ({ group: s.group, items: s.items.filter((i) => labs || !i.labs) })).filter((s) => s.items.length > 0)
    : role === 'admin'
      ? ADMIN_NAV.map((s) => ({ group: s.group, items: s.items.filter((i) => !i.superuser) })).filter((s) => s.items.length > 0)
      : NAV.map((s) => ({
    group: s.groupFor?.[role] ?? s.group,
    items: s.items
      .filter((i) => !i.roles || i.roles.includes(role))
      .filter((i) => !i.superuser || superuser)
      .filter((i) => labs || !i.labs)
      .filter((i) => hasContent(i, role, features))
      .map((i) => ({ ...i, label: i.labelFor?.[role] ?? i.label })),
  })).filter((s) => s.items.length > 0);

export const ROLE_LABEL: Record<Role | 'superuser', string> = { admin: 'Platform admin', superuser: 'Super Admin', user: 'User', operator: 'Open mode' };

const NAV_PREF = 'memoryhub.navOpen';
const readNavPref = () => {
  try {
    return window.localStorage.getItem(NAV_PREF) !== 'false';
  } catch {
    return true;
  }
};

export const Shell: React.FC<{ activePath: string; children: React.ReactNode }> = ({ activePath, children }) => {
  const { me, role, superuser, tenant, reviewCount, features, platformMode, tenantContext, exitTenant } = useApp();
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

  /** Ends the session completely, then lands on the sign-in page (or the OpenShift logout). */
  const onLogout = async () => {
    let res: Awaited<ReturnType<typeof api.logout>> | null = null;
    try {
      res = await api.logout();
    } catch {
      /* still leave the app */
    }
    try {
      window.sessionStorage.clear();
    } catch {
      /* storage unavailable */
    }
    const target = res?.redirect || '/#/login?signed_out=1';
    if (res?.method === 'POST') {
      // The OpenShift OAuth server's /logout only accepts a form POST and
      // responds with an empty 200 page. Submit it into a hidden frame so the
      // user never lands on that blank page, then clear oauth-proxy's cookie
      // and replace the current history entry with our sign-in screen.
      const frame = document.createElement('iframe');
      const frameName = `memoryhub-logout-${Date.now()}`;
      frame.name = frameName;
      frame.title = 'Signing out';
      frame.setAttribute('aria-hidden', 'true');
      frame.style.display = 'none';
      document.body.appendChild(frame);
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = target;
      form.target = frameName;
      form.style.display = 'none';
      Object.entries(res.fields ?? {}).forEach(([name, value]) => {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = name;
        input.value = value;
        form.appendChild(input);
      });
      document.body.appendChild(form);
      form.submit();
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        frame.remove();
        form.remove();
        window.location.replace('/#/login?signed_out=1');
      };
      // Give the cross-origin POST time to clear the OpenShift session before
      // asking the local oauth-proxy to clear its session cookie as well.
      window.setTimeout(() => {
        fetch('/oauth/sign_out', { credentials: 'same-origin', redirect: 'manual' })
          .catch(() => undefined)
          .finally(finish);
      }, 400);
      // Network failures must still leave the app on a usable sign-in route.
      window.setTimeout(finish, 2500);
      return;
    }
    window.location.replace(target);
  };

  const [switchable, setSwitchable] = useState<SwitchTargets | null>(null);
  const loadTargets = () => {
    if (me?.test_mode && !switchable) api.switchTargets().then(setSwitchable).catch(() => undefined);
  };
  const switchTo = async (username: string | null, toRole: string | null) => {
    try {
      await api.switchAccount(username, toRole);
    } finally {
      window.location.hash = '#/overview';
      window.location.reload();
    }
  };

  return (
    <div>
      <header className="mast">
        <button type="button" className="icb" aria-label={open ? 'Hide navigation' : 'Show navigation'} aria-expanded={open} onClick={toggle}>
          <Icon.Menu />
        </button>
        <a className="brand" href={buildHash(platformMode ? '/platform' : '/overview')}>
          <span className="mark">
            <Icon.Mark />
          </span>
          <span className="wm">
            MemoryHub<small>for OpenShift AI</small>
          </span>
        </a>
        {superuser ? (
          <>
            <span className="mast-section">{platformMode ? 'Platform operations' : 'Tenant console'}</span>
            <ScopeSwitcher />
          </>
        ) : (
          <>
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
          </>
        )}
        <div className="mast-r">
          {role !== 'admin' && (
            <a className="icb" aria-label="Search memories" href={buildHash('/search')}>
              <Icon.Search />
            </a>
          )}
          <Notifications fallbackCount={reviewCount} />
          <Dropdown
            align="right"
            toggle={(p) => (
              <button type="button" className="icb" aria-label="Help" {...p}>
                <Icon.Help />
              </button>
            )}
          >
            {() => (
              <>
                <a href={`${REPO_URL}#readme`} target="_blank" rel="noopener noreferrer">
                  Documentation
                </a>
                <a href={`${REPO_URL}/issues/new`} target="_blank" rel="noopener noreferrer">
                  Report an issue
                </a>
              </>
            )}
          </Dropdown>
          <Dropdown
            align="right"
            toggle={(p) => (
              <button
                type="button"
                className="who"
                {...p}
                onClick={() => {
                  loadTargets();
                  p.onClick();
                }}
              >
                <span className="av">{me?.initials ?? '··'}</span>
                {me?.name ?? ''}
                {superuser && <span className="sa-badge">Super Admin</span>}
                <span className="vh"> · {me?.test_mode ? 'account menu and test-mode account switcher' : 'account menu'}</span>
                {me?.test_mode && <Icon.Chevron />}
              </button>
            )}
          >
            {() => (
              <>
                <div className="mh">
                  {me ? `${me.real_username ? 'Viewing as' : 'Signed in as'} ${me.username}` : 'Not signed in'}
                  <br />
                  <span className="muted sm">{ROLE_LABEL[superuser ? 'superuser' : role]}</span>
                  {me?.real_username && (
                    <>
                      <br />
                      <span className="muted sm">Signed in as {me.real_username}</span>
                    </>
                  )}
                </div>
                {me?.test_mode && (
                  <>
                    <hr />
                    <div className="mh">Switch account · test mode</div>
                    {!switchable ? (
                      <div className="mh muted">Loading…</div>
                    ) : (
                      switchable.targets.map((t) => {
                        const on = t.username === me.username && t.role === me.role;
                        return (
                          <button
                            key={`${t.username}-${t.role}`}
                            type="button"
                            role="menuitemradio"
                            aria-checked={on}
                            className={on ? 'on' : ''}
                            onClick={() => !on && switchTo(t.username, t.role)}
                          >
                            <span className="sw-row">
                              <span className={`sw-dot ${t.role}`} aria-hidden="true" />
                              <span>
                                <span style={{ display: 'block', fontWeight: on ? 600 : 400 }}>
                                  {t.label}
                                  {on ? ' ✓' : ''}
                                </span>
                                {t.note && <span className="hint">{t.note}</span>}
                              </span>
                            </span>
                          </button>
                        );
                      })
                    )}
                    {me.real_username && (
                      <button type="button" onClick={() => switchTo(null, null)}>
                        Back to {me.real_username}
                      </button>
                    )}
                    <hr />
                  </>
                )}
                {me && me.source !== 'anonymous' && (
                  <button type="button" onClick={onLogout}>
                    Log out
                  </button>
                )}
              </>
            )}
          </Dropdown>
        </div>
      </header>
      {me?.access?.break_glass && <IncidentBanner grant={me.access.break_glass} />}
      {tenantContext && (
        <div className="ctx-banner" role="status">
          <Icon.Shield size={16} />
          <b>Super Admin in tenant context: {tenantContext.tenant}</b>
          <span>You act as a tenant administrator here, not as any user. Personal content stays closed; every action is logged with your platform identity.</span>
          <button type="button" className="btn ctx-exit" onClick={exitTenant}>
            Exit to All tenants
          </button>
        </div>
      )}
      {me?.real_username && (
        <div className="viewing-as" role="status">
          <b>Test mode:</b> viewing as {me.username} · {ROLE_LABEL[superuser ? 'superuser' : role]} (signed in as {me.real_username}).
          <button type="button" onClick={() => switchTo(null, null)}>
            Back to my account
          </button>
        </div>
      )}
      <div className={`shell ${open ? 'nav-open' : 'nav-closed'}`}>
        <nav className="nav" aria-label="Primary">
          {navFor(role, features, !!me?.labs, superuser, platformMode).map((section, i) => (
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
          {tenantContext && (
            <div className="eff-perm">
              <b>Effective permissions</b>
              <div>
                Super Admin in tenant context tenant.* for {tenantContext.tenant} · same read rules as a PA: no personal content, project content only by membership
              </div>
              <div className="muted">Resolved by the API from /api/me</div>
            </div>
          )}
        </nav>
        <main className="main">{children}</main>
      </div>
    </div>
  );
};

/** Super Admin: All tenants, or one tenant's console (asks for a reason first, on Tenants). */
const ScopeSwitcher: React.FC = () => {
  const { platformMode, tenantContext, exitTenant, tenant } = useApp();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    if (!platformMode) return;
    platform
      .tenants()
      .then((r) => setCount(r.items.length))
      .catch(() => undefined);
  }, [platformMode]);
  return (
    <Dropdown
      toggle={(p) => (
        <button type="button" className="scope-pill" {...p}>
          {platformMode ? `Scope: All tenants${count !== null ? ` (${count})` : ''}` : `Tenant: ${tenantContext?.tenant ?? tenant} · admin context`}
          <Icon.Chevron />
        </button>
      )}
    >
      {(close) => (
        <>
          {platformMode ? (
            <div className="mh muted sm">Open a tenant’s console from Tenants — it asks for a reason and is logged.</div>
          ) : (
            <button
              type="button"
              onClick={() => {
                close();
                exitTenant();
              }}
            >
              Exit to All tenants
            </button>
          )}
          <a href={buildHash('/tenants')} onClick={() => close()}>
            Tenants…
          </a>
        </>
      )}
    </Dropdown>
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

const CrumbRoot: React.FC = () => {
  const { superuser, tenantContext } = useApp();
  if (!superuser) return <a href={buildHash('/overview')}>MemoryHub</a>;
  return (
    <>
      <a href={buildHash('/platform')}>Platform Operations</a>
      {tenantContext && (
        <>
          <span>/</span>
          <a href={buildHash('/overview')}>{tenantContext.tenant}</a>
        </>
      )}
    </>
  );
};

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

const POLL_NOTIFICATIONS_MS = 60000;

const Notifications: React.FC<{ fallbackCount: number }> = ({ fallbackCount }) => {
  const { role } = useApp();
  const [data, setData] = useState<NotificationsResponse | null>(null);
  const load = useCallback(() => {
    api
      .notifications()
      .then(setData)
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    load();
    const id = window.setInterval(load, POLL_NOTIFICATIONS_MS);
    return () => window.clearInterval(id);
  }, [load, role]);
  const unread = data ? data.unread : fallbackCount;
  return (
    <Dropdown
      align="right"
      toggle={(p) => (
        <button
          type="button"
          className="icb"
          aria-label={unread ? `Notifications, ${unread} new` : 'Notifications'}
          {...p}
          onClick={() => {
            p.onClick();
            if (data?.unread) {
              api
                .markNotificationsSeen()
                .then(() => setData((d) => (d ? { ...d, unread: 0 } : d)))
                .catch(() => undefined);
            }
          }}
        >
          <Icon.Bell />
          {unread > 0 && <span className="dot">{unread > 99 ? '99+' : unread}</span>}
        </button>
      )}
    >
      {(close) => (
        <div className="notif">
          <div className="notif-h">
            <b>Notifications</b>
            {role === 'admin' && (
              <a className="sm" href={buildHash('/review')} onClick={close}>
                Review queue
              </a>
            )}
          </div>
          {!data ? (
            <div style={{ padding: 16 }} className="sm muted">
              Loading…
            </div>
          ) : data.items.length === 0 ? (
            <div style={{ padding: 16 }} className="sm muted">
              {role === 'admin' ? 'The review queue is empty.' : 'Nothing new. Break-glass access, contradictions on your memories, other agents using them and Dreaming suggestions show up here.'}
            </div>
          ) : (
            data.items.map((n) => (
              <a key={n.id} href={buildHash(n.href)} className={`notif-i ${n.unread ? 'unread' : ''}`} onClick={close}>
                <span className={`ndot ${n.severity}`} aria-hidden="true" />
                <span style={{ minWidth: 0 }}>
                  <span className="sm b6" style={{ display: 'block' }}>
                    {n.title}
                  </span>
                  {n.body && (
                    <span className="hint ellipsis" style={{ display: 'block' }}>
                      {n.body}
                    </span>
                  )}
                  {n.at && <span className="hint">{fmtRelativeShort(n.at)}</span>}
                </span>
              </a>
            ))
          )}
        </div>
      )}
    </Dropdown>
  );
};

const fmtRelativeShort = (iso: string) => {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
};

/** #667: while a super-user holds an incident grant, every page says so. */
const IncidentBanner: React.FC<{ grant: BreakGlassGrant }> = ({ grant }) => (
  <div className="incident-banner" role="status">
    <b>Incident access {grant.incident_ref}</b>
    <span>
      User memories are open until {new Date(grant.expires_at).toLocaleString()}. Every one you open is logged with HIGH severity and its owner is told.
    </span>
    <a href={buildHash('/incident')}>Manage</a>
  </div>
);
