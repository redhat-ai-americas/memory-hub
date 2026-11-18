import React, { useEffect, useState } from 'react';
import { api, AUTH_REQUIRED_EVENT } from '@/api/client';
import { AppProvider, canSee, movedFor, NAV, navFor, Shell, useApp } from '@/components/Shell';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { Empty } from '@/components/ui';
import { ToastProvider } from '@/components/ui';
import { navigate, useHashRoute, type HashRoute } from '@/hooks/useHashRoute';
import Clients from '@/pages/Clients';
import Curation from '@/pages/Curation';
import Entities from '@/pages/Entities';
import EntityDetail from '@/pages/EntityDetail';
import Identities from '@/pages/Identities';
import Memories from '@/pages/Memories';
import MemoryDetail from '@/pages/MemoryDetail';
import Overview from '@/pages/Overview';
import Review from '@/pages/Review';
import Search from '@/pages/Search';
import MyAgents from '@/pages/MyAgents';
import MyProjects from '@/pages/MyProjects';
import AdminProjects, { ProjectSettings } from '@/pages/Projects';

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

interface Screen {
  nav: string;
  title: string;
  render: (route: HashRoute) => React.ReactNode;
}

// Only screens backed by the dashboard BFF (memoryhub-ui/backend). Users and
// admins see different versions of a few of them; the BFF enforces the same split.
const SCREENS: Record<string, Screen> = {
  '/overview': { nav: '/overview', title: 'Overview', render: () => <Overview /> },
  '/memories': { nav: '/memories', title: 'Memory browser', render: (r) => <Memories route={r} /> },
  '/memory': { nav: '/memories', title: 'Memory detail', render: (r) => <MemoryDetail route={r} /> },
  '/entities': { nav: '/entities', title: 'Entities', render: (r) => <Entities route={r} /> },
  '/entity': { nav: '/entities', title: 'Entity', render: (r) => <EntityDetail route={r} /> },
  '/search': { nav: '/search', title: 'Search playground', render: (r) => <Search route={r} /> },
  '/projects': { nav: '/projects', title: 'Projects', render: (r) => <ByRole user={<MyProjects route={r} />} other={<AdminProjects route={r} />} /> },
  '/project': { nav: '/projects', title: 'Project', render: (r) => <ByRole user={<Redirect to="/projects" params={{ project: decodeURIComponent(r.path.slice(9)) }} />} other={<ProjectSettings route={r} />} /> },
  '/review': { nav: '/review', title: 'Contradictions', render: (r) => <Review route={r} /> },
  '/curation': { nav: '/curation', title: 'Curation rules', render: (r) => <Curation route={r} /> },
  '/identities': { nav: '/identities', title: 'Agents & identities', render: (r) => <ByRole user={<MyAgents route={r} />} other={<Identities route={r} />} /> },
  '/clients': { nav: '/clients', title: 'OAuth clients & keys', render: (r) => <Clients route={r} /> },
};

// Old bookmarks from the previous dashboard keep working.
const LEGACY: Record<string, { path: string; params?: Record<string, string> }> = {
  '/status': { path: '/overview' },
  '/contradictions': { path: '/review' },
  '/curation-rules': { path: '/curation' },
  '/rules': { path: '/curation' },
  '/users': { path: '/identities' },
  '/graph': { path: '/memories', params: { view: 'graph' } },
};


/** Screens a role may not open show a short explanation instead. */
const Guarded: React.FC<{ nav: string; children: React.ReactNode }> = ({ nav, children }) => {
  const { me, role } = useApp();
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
  if (!me || canSee(nav, role)) return <>{children}</>;
  return (
    <div className="body">
      <div className="card">
        <Empty title={role === 'admin' ? 'Not available to platform admins' : 'Only platform admins can open this'}>
          {role === 'admin'
            ? 'This screen works with personal memories, which stay private to their owner.'
            : 'Identities, OAuth clients and contradiction review are managed by platform admins.'}
        </Empty>
      </div>
    </div>
  );
};

const screenKey = (path: string) => {
  if (path.startsWith('/memory/')) return '/memory';
  if (path.startsWith('/project/')) return '/project';
  if (path.startsWith('/entity/')) return '/entity';
  return path;
};

/** Browser tab title: the menu label this role sees for a top-level screen, the screen title for detail pages. */
const DocTitle: React.FC<{ path: string; screen: Screen }> = ({ path, screen }) => {
  const { role } = useApp();
  const label =
    path === screen.nav
      ? navFor(role)
          .flatMap((s) => s.items)
          .find((i) => i.path === screen.nav)?.label
      : undefined;
  const title = label ?? screen.title;
  useEffect(() => {
    document.title = `MemoryHub · ${title}`;
  }, [title]);
  return null;
};

const Routed: React.FC = () => {
  const route = useHashRoute();
  const [authRequired, setAuthRequired] = useState(false);

  useEffect(() => {
    api
      .authStatus()
      .then((s) => setAuthRequired(!s.authenticated))
      .catch(() => undefined);
    const onAuth = () => setAuthRequired(true);
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuth);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onAuth);
  }, []);

  useEffect(() => {
    const legacy = LEGACY[route.path];
    if (legacy) navigate(legacy.path, legacy.params, { replace: true });
    else if (route.path === '/' || (!SCREENS[screenKey(route.path)])) {
      navigate('/overview', undefined, { replace: true });
    }
  }, [route.path]);

  const key = screenKey(route.path);
  const screen = SCREENS[key];

  if (authRequired) {
    // The dashboard sits behind the OpenShift oauth-proxy: signing in again is a fresh page load.
    return (
      <div className="body">
        <div className="card">
          <Empty
            title="Your session has ended"
            action={
              <button type="button" className="btn bp" onClick={() => window.location.replace('/')}>
                Sign in again
              </button>
            }
          >
            Sign in through OpenShift to keep working with MemoryHub.
          </Empty>
        </div>
      </div>
    );
  }
  if (!screen) return null;
  const known = NAV.some((s) => s.items.some((i) => i.path === screen.nav));
  return (
    <AppProvider>
      <Shell activePath={known ? screen.nav : ''}>
        {/* key resets page state when moving between screens */}
        <React.Fragment key={key}>
          <DocTitle path={key} screen={screen} />
          <ErrorBoundary key={route.path}>
            <Guarded nav={screen.nav}>{screen.render(route)}</Guarded>
          </ErrorBoundary>
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
