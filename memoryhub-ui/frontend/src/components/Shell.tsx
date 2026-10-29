import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api } from '@/api/client';
import type { BreakGlassGrant, Me, NavFeatures, NotificationsResponse, Role, SwitchTargets } from '@/types';
import { buildHash } from '@/hooks/useHashRoute';
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
}

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
});
export const useApp = () => useContext(AppContext);

const POLL_EMPTY_MS = 5000;
const POLL_IDLE_MS = 60000;

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [me, setMe] = useState<Me | null>(null);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [reviewCount, setReviewCount] = useState(0);
  const [token, setToken] = useState(0);
  const [features, setFeatures] = useState<NavFeatures | null>(null);

  useEffect(() => {
    api.me().then(setMe).catch(() => undefined);
  }, []);

  useEffect(() => {
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
  }, [token, me?.role, me?.username]);

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
        role: me?.role === 'superuser' ? 'admin' : (me?.role ?? 'operator'),
        superuser: me?.role === 'superuser',
        tenant: me?.tenant_id ?? '',
        memoryCount,
        standby: memoryCount === 0,
        reviewCount,
        features,
        refreshCounts,
      }}
    >
      {children}
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
      { path: '/search', label: 'Search playground', roles: USER },
      { path: '/hygiene', label: 'Memory hygiene', roles: USER, labs: true },
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

export const canSee = (path: string, role: Role, superuser = false) =>
  NAV.some((s) => s.items.some((i) => i.path === path && (!i.roles || i.roles.includes(role)) && (!i.superuser || superuser)));

const hasContent = (item: NavItem, role: Role, features: NavFeatures | null) => {
  const keys = item.feature?.[role];
  if (!keys) return true;
  return !!features && keys.some((k) => (features[k] ?? 0) > 0);
};

export const isLabsPath = (path: string) => NAV.some((s) => s.items.some((i) => i.path === path && i.labs));

export const navFor = (role: Role, features: NavFeatures | null = null, labs = false, superuser = false) =>
  NAV.map((s) => ({
    group: s.groupFor?.[role] ?? s.group,
    items: s.items
      .filter((i) => !i.roles || i.roles.includes(role))
      .filter((i) => !i.superuser || superuser)
      .filter((i) => labs || !i.labs)
      .filter((i) => hasContent(i, role, features))
      .map((i) => ({ ...i, label: i.labelFor?.[role] ?? i.label })),
  })).filter((s) => s.items.length > 0);

export const ROLE_LABEL: Record<Role | 'superuser', string> = { admin: 'Platform admin', superuser: 'Super-user', user: 'User', operator: 'Open mode' };

const NAV_PREF = 'memoryhub.navOpen';
const readNavPref = () => {
  try {
    return window.localStorage.getItem(NAV_PREF) !== 'false';
  } catch {
    return true;
  }
};

export const Shell: React.FC<{ activePath: string; children: React.ReactNode }> = ({ activePath, children }) => {
  const { me, role, superuser, tenant, reviewCount, features } = useApp();
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
            className={`role-pill ${superuser ? 'superuser' : role}`}
            title={
              superuser
                ? 'Platform admin who can open user memories for an incident, with an incident reference'
                : role === 'admin'
                  ? 'You moderate every scope except user; personal memories show metadata only'
                  : 'You see memories you are allowed to read'
            }
          >
            {ROLE_LABEL[superuser ? 'superuser' : role]}
          </span>
        )}
        {tenant && (
          <span className="ctx" title="Each dashboard deployment serves one tenant (MEMORYHUB_UI_TENANT_ID)">
            Tenant: {tenant}
          </span>
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
                aria-label={me?.test_mode ? 'Account and test-mode account switcher' : 'Account'}
                {...p}
                onClick={() => {
                  loadTargets();
                  p.onClick();
                }}
              >
                <span className="av">{me?.initials ?? '··'}</span>
                {me?.name ?? ''}
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
          {navFor(role, features, !!me?.labs, superuser).map((section, i) => (
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
}> = ({ title, crumbs, description, actions, tabs, long, topAlign, below }) => (
  <div className={`ph ${tabs ? 'has-tabs' : ''}`}>
    <div className="crumbs">
      <a href={buildHash('/overview')}>MemoryHub</a>
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
