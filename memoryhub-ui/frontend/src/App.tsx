import React, { useEffect, useState } from 'react';
import { api, AUTH_REQUIRED_EVENT } from '@/api/client';
import { AppProvider, canSee, isLabsPath, movedFor, NAV, Shell, useApp } from '@/components/Shell';
import { Empty } from '@/components/ui';
import { ToastProvider } from '@/components/ui';
import { navigate, useHashRoute, type HashRoute } from '@/hooks/useHashRoute';
import Accounts from '@/pages/Accounts';
import Audit from '@/pages/Audit';
import AdminAudit from '@/pages/AdminAudit';
import Preferences from '@/pages/Preferences';
import WhoRead from '@/pages/WhoRead';
import Dreaming from '@/pages/Dreaming';
import Clients from '@/pages/Clients';
import Curation from '@/pages/Curation';
import Entities from '@/pages/Entities';
import EntityDetail from '@/pages/EntityDetail';
import Knowledge from '@/pages/Knowledge';
import Operations from '@/pages/Operations';
import Quality from '@/pages/Quality';
import Graph from '@/pages/Graph';
import Identities from '@/pages/Identities';
import Login from '@/pages/Login';
import Memories from '@/pages/Memories';
import MemoryDetail from '@/pages/MemoryDetail';
import Overview from '@/pages/Overview';
import Projects from '@/pages/Projects';
import Review from '@/pages/Review';
import Search from '@/pages/Search';
import Settings from '@/pages/Settings';
import Connect from '@/pages/Connect';
import Verify from '@/pages/Verify';
import Incident from '@/pages/Incident';
import MyActivity from '@/pages/MyActivity';
import MyAgents from '@/pages/MyAgents';
import MyProjects from '@/pages/MyProjects';
import MyRequests from '@/pages/MyRequests';
import RetrievalOps from '@/pages/RetrievalOps';
import AdminProjects, { ProjectSettings, TeamSettings } from '@/pages/AdminProjects';

/** Users get their own version of a few screens; everyone else the shared one. */
const ByRole: React.FC<{ user: React.ReactNode; other: React.ReactNode }> = ({ user, other }) => {
  const { role } = useApp();
  return <>{role === 'user' ? user : other}</>;
};

/** Settings pages are for admins; users land on the read-only view of the same record. */
const Redirect: React.FC<{ to: string; params?: Record<string, string> }> = ({ to, params }) => {
  useEffect(() => navigate(to, params, { replace: true }), [to, params]);
  return null;
};

/** Platform admins (and super-users, who work as admins) get their own version of a few screens. */
const AdminOr: React.FC<{ admin: React.ReactNode; other: React.ReactNode }> = ({ admin, other }) => {
  const { role } = useApp();
  return <>{role === 'admin' ? admin : other}</>;
};

interface Screen {
  nav: string;
  title: string;
  render: (route: HashRoute) => React.ReactNode;
}

const SCREENS: Record<string, Screen> = {
  '/overview': { nav: '/overview', title: 'Overview', render: () => <Overview /> },
  '/memories': { nav: '/memories', title: 'Memory browser', render: (r) => <Memories route={r} /> },
  '/memory': { nav: '/memories', title: 'Memory detail', render: (r) => <MemoryDetail route={r} /> },
  '/graph': { nav: '/memories', title: 'Memory graph', render: (r) => <Graph route={r} /> },
  '/accounts': { nav: '/accounts', title: 'Accounts & sign-up', render: () => <Accounts /> },
  '/entities': { nav: '/entities', title: 'Entities', render: (r) => <Entities route={r} /> },
  '/entity': { nav: '/entities', title: 'Entity', render: (r) => <EntityDetail route={r} /> },
  '/knowledge': { nav: '/knowledge', title: 'Knowledge', render: (r) => <Knowledge route={r} /> },
  '/quality': { nav: '/quality', title: 'Retrieval quality', render: (r) => <ByRole user={<Quality route={r} />} other={<AdminOr admin={<RetrievalOps route={r} />} other={<Quality route={r} />} />} /> },
  '/operations': { nav: '/operations', title: 'Operations', render: () => <Operations /> },
  '/search': { nav: '/search', title: 'Search playground', render: (r) => <Search route={r} /> },
  '/projects': { nav: '/projects', title: 'Projects & teams', render: (r) => <ByRole user={<MyProjects route={r} />} other={<AdminOr admin={<AdminProjects route={r} />} other={<Projects route={r} />} />} /> },
  '/project': { nav: '/projects', title: 'Project settings', render: (r) => <ByRole user={<Redirect to="/projects" params={{ project: decodeURIComponent(r.path.slice(9)) }} />} other={<ProjectSettings route={r} />} /> },
  '/team': { nav: '/projects', title: 'Team settings', render: (r) => <ByRole user={<Redirect to="/projects" params={{ kind: 'teams', team: decodeURIComponent(r.path.slice(6)) }} />} other={<TeamSettings route={r} />} /> },
  '/hygiene': { nav: '/hygiene', title: 'Dreaming', render: () => <Dreaming /> },
  '/reads': { nav: '/reads', title: 'Who read my memories', render: (r) => <WhoRead route={r} /> },
  '/preferences': { nav: '/preferences', title: 'Preferences & privacy', render: () => <Preferences /> },
  '/review': { nav: '/review', title: 'Review queue', render: (r) => <ByRole user={<MyRequests route={r} />} other={<Review route={r} />} /> },
  '/curation': { nav: '/curation', title: 'Curation rules', render: (r) => <Curation route={r} /> },
  '/audit': { nav: '/audit', title: 'Audit & forensics', render: (r) => <ByRole user={<MyActivity route={r} />} other={<AdminOr admin={<AdminAudit route={r} />} other={<Audit route={r} />} />} /> },
  '/identities': { nav: '/identities', title: 'Users & agents', render: (r) => <ByRole user={<MyAgents route={r} />} other={<Identities route={r} />} /> },
  '/clients': { nav: '/clients', title: 'OAuth clients & keys', render: (r) => <Clients route={r} /> },
  '/connect': { nav: '/connect', title: 'Connect an agent', render: () => <Connect /> },
  '/verify': { nav: '/verify', title: 'Connection check', render: () => <Verify /> },
  '/incident': { nav: '/incident', title: 'Incident access', render: () => <Incident /> },
  '/settings': { nav: '/settings', title: 'Settings', render: () => <Settings /> },
};

// Old bookmarks from the previous dashboard keep working.
const LEGACY: Record<string, { path: string; params?: Record<string, string> }> = {
  '/status': { path: '/overview' },
  '/contradictions': { path: '/review', params: { tab: 'contradictions' } },
  '/curation-rules': { path: '/curation' },
  '/rules': { path: '/curation' },
  '/documents': { path: '/knowledge/documents' },
  '/packs': { path: '/knowledge/packs' },
  '/dreaming': { path: '/hygiene' },
  '/users': { path: '/identities' },
};

const AUTH_PATHS = ['/login', '/register', '/setup'];

/** Screens a role may not open show a short explanation instead. */
const Guarded: React.FC<{ nav: string; children: React.ReactNode }> = ({ nav, children }) => {
  const { me, role, superuser } = useApp();
  const route = useHashRoute();
  const moved = movedFor(role, nav);
  useEffect(() => {
    if (!moved) return;
    // A user screen that now lives inside a hub: keep its parameters, add the view.
    const next = new URLSearchParams(route.params);
    next.set('view', moved.view);
    navigate(moved.path, next, { replace: true });
  }, [moved, route.params]);
  if (moved) return null;
  const listed = NAV.some((s) => s.items.some((i) => i.path === nav));
  if (me && isLabsPath(nav, role) && !me.labs) {
    return (
      <div className="body">
        <div className="card">
          <Empty title="A MemoryHub Labs feature">
            This screen goes beyond the Release 1 scope and is switched off on this deployment. An operator can turn Labs on with MEMORYHUB_UI_LABS=true.
          </Empty>
        </div>
      </div>
    );
  }
  if (!me || !listed || canSee(nav, role, superuser)) return <>{children}</>;
  return (
    <div className="body">
      <div className="card">
        <Empty
          title={
            nav === '/incident' ? 'Only super-users can open this' : role === 'admin' ? 'Not available to platform admins' : 'Only platform admins can open this'
          }
        >
          {nav === '/incident'
            ? 'Incident access to user memories is for super-users, who are set by the deployment (MEMORYHUB_UI_SUPERUSER_GROUP), never in the dashboard.'
            : role === 'admin'
              ? 'This screen works with personal memories. Platform admins moderate every other scope in Content moderation; user memories need a super-user with an incident reference.'
              : 'Platform settings, identities, keys and the audit log are managed by platform admins.'}
        </Empty>
      </div>
    </div>
  );
};

const screenKey = (path: string) => {
  if (path.startsWith('/memory/')) return '/memory';
  if (path.startsWith('/project/')) return '/project';
  if (path.startsWith('/team/')) return '/team';
  if (path.startsWith('/entity/')) return '/entity';
  if (path.startsWith('/knowledge/')) return '/knowledge';
  return path;
};

const Routed: React.FC = () => {
  const route = useHashRoute();
  const [authRequired, setAuthRequired] = useState(false);

  useEffect(() => {
    api
      .authStatus()
      .then((s) => setAuthRequired(!s.authenticated || s.setup_required))
      .catch(() => undefined);
    const onAuth = () => setAuthRequired(true);
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuth);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onAuth);
  }, []);

  useEffect(() => {
    const legacy = LEGACY[route.path];
    if (legacy) navigate(legacy.path, legacy.params, { replace: true });
    else if (route.path.startsWith('/documents/') || route.path.startsWith('/packs/')) navigate(`/knowledge${route.path}`, undefined, { replace: true });
    else if (route.path === '/' || (!SCREENS[screenKey(route.path)] && !AUTH_PATHS.includes(route.path))) {
      navigate('/overview', undefined, { replace: true });
    }
  }, [route.path]);

  const key = screenKey(route.path);
  const screen = SCREENS[key];

  useEffect(() => {
    const title =
      route.path === '/login' ? 'Log in' : route.path === '/register' ? 'Create account' : route.path === '/setup' ? 'Set up' : screen?.title;
    document.title = title ? `MemoryHub · ${title}` : 'MemoryHub';
  }, [screen, route.path]);

  if (AUTH_PATHS.includes(route.path) || authRequired) {
    const view = route.path === '/register' ? 'register' : route.path === '/setup' ? 'setup' : 'login';
    return (
      <Login
        view={view}
        invite={route.params.get('invite') ?? undefined}
        signedOut={route.params.get('signed_out') === '1'}
        onLoggedIn={() => setAuthRequired(false)}
      />
    );
  }
  if (!screen) return null;
  const known = NAV.some((s) => s.items.some((i) => i.path === screen.nav));
  return (
    <AppProvider>
      <Shell activePath={known ? screen.nav : ''}>
        {/* key resets page state when moving between screens */}
        <React.Fragment key={key}>
          <Guarded nav={screen.nav}>{screen.render(route)}</Guarded>
        </React.Fragment>
      </Shell>
    </AppProvider>
  );
};

const App: React.FC = () => (
  <ToastProvider>
    <Routed />
  </ToastProvider>
);

export default App;
