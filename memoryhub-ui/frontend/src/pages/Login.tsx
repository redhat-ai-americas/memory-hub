import React, { useEffect, useMemo, useState } from 'react';
import { api } from '@/api/client';
import { Icon, Switch } from '@/components/ui';
import { navigate } from '@/hooks/useHashRoute';
import type { AuthStatus, SetupPayload, SignupMode } from '@/types';
import { errorMessage } from '@/utils/format';

/**
 * Screen 13 — sign-in, sign-up and the first-run admin setup.
 *
 * - Behind the OpenShift OAuth proxy, "Log in with OpenShift" (re)starts that
 *   flow and roles come from the admin OpenShift group.
 * - With local accounts (MEMORYHUB_UI_LOCAL_ACCOUNTS=true) people sign in with
 *   email or username + password, and can create an account when the tenant's
 *   sign-up policy allows it. The very first visit creates the platform admin.
 * - The API-key form stays available for development clusters.
 */
type AuthView = 'login' | 'register' | 'setup';

const DOCS = 'https://github.com/redhat-ai-americas/memory-hub#readme';

const Login: React.FC<{ onLoggedIn: () => void; view?: AuthView; invite?: string; signedOut?: boolean }> = ({ onLoggedIn, view = 'login', invite, signedOut }) => {
  const [status, setStatus] = useState<AuthStatus | null>(null);

  useEffect(() => {
    api.authStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  const current: AuthView = status?.setup_required ? 'setup' : view;
  const proceed = () => {
    onLoggedIn();
    navigate('/overview');
  };

  return (
    <AuthLayout status={status} wide={current === 'setup'}>
      {current === 'setup' ? (
        <SetupWizard status={status} onDone={proceed} />
      ) : current === 'register' ? (
        <RegisterForm status={status} invite={invite} onDone={proceed} />
      ) : (
        <LoginForm status={status} onDone={proceed} signedOut={signedOut} />
      )}
    </AuthLayout>
  );
};

/* ------------------------------------------------------------------ */
/* Layout                                                              */
/* ------------------------------------------------------------------ */

const AuthLayout: React.FC<{ status: AuthStatus | null; wide?: boolean; children: React.ReactNode }> = ({ status, wide, children }) => (
  <div className="auth">
    <svg aria-hidden="true" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" className="auth-bg">
      <g fill="none" stroke="#2a2a2a" strokeWidth="1.5">
        {[120, 240, 360, 480].map((r) => (
          <circle key={r} cx="1180" cy="300" r={r} />
        ))}
      </g>
      <g stroke="#3a3a3a" strokeWidth="1.5">
        <line x1="1040" y1="180" x2="1300" y2="420" />
        <line x1="1300" y1="180" x2="980" y2="520" />
        <line x1="900" y1="300" x2="1440" y2="300" />
      </g>
      <g fill="#ee0000">
        <circle cx="1040" cy="180" r="6" />
        <circle cx="1300" cy="420" r="6" />
      </g>
      <g fill="#4d4d4d">
        <circle cx="1300" cy="180" r="5" />
        <circle cx="980" cy="520" r="5" />
        <circle cx="1180" cy="300" r="7" />
      </g>
    </svg>
    <header className="auth-head">
      <span className="mark" style={{ width: 34, height: 34, borderRadius: 9 }}>
        <Icon.Mark size={20} />
      </span>
      <span style={{ fontFamily: 'var(--mh-font-display)', fontWeight: 600, fontSize: 20 }}>MemoryHub</span>
      <span style={{ color: '#c7c7c7', fontSize: 14 }}>for OpenShift AI</span>
      {status?.organization && <span className="auth-org">{status.organization}</span>}
    </header>
    <div className="auth-body">
      <div className={`auth-card ${wide ? 'wide' : ''}`}>{children}</div>
      {!wide && (
        <div className="auth-pitch">
          <h2>Governed memory for every agent in your cluster.</h2>
          <p>Shared, versioned and audited memory over MCP — with six-tier scopes, contradiction handling and a forensic trail that answers what an agent knew and why.</p>
          <ul>
            <li>Your memories stay yours: platform admins see counts and activity, never content</li>
            <li>Scope isolation enforced in SQL, not in prompts</li>
            <li>Human approval for enterprise policy memories</li>
          </ul>
        </div>
      )}
    </div>
    <footer className="auth-foot">
      <span>MemoryHub{status?.cluster_domain ? ` · cluster ${status.cluster_domain}` : ''}</span>
      <a href={DOCS} target="_blank" rel="noopener noreferrer">
        Help
      </a>
    </footer>
  </div>
);

/* ------------------------------------------------------------------ */
/* Sign in                                                             */
/* ------------------------------------------------------------------ */

const LoginForm: React.FC<{ status: AuthStatus | null; onDone: () => void; signedOut?: boolean }> = ({ status, onDone, signedOut }) => {
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [key, setKey] = useState('');
  const [user, setUser] = useState('');
  const [devRole, setDevRole] = useState<'admin' | 'user'>('admin');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const accounts = Boolean(status?.local_accounts);
  const signupOpen = accounts && status?.signup && status.signup.mode !== 'closed';

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const openshift = () => {
    if (status?.mode === 'open' || (!signedOut && status?.mode === 'oauth-proxy')) onDone();
    else window.location.href = '/oauth/start?rd=/';
  };

  return (
    <div className="auth-form">
      {signedOut && (
        <div className="alert ok-a" role="status">
          You are signed out. Sign in again or create an account.
        </div>
      )}
      <div>
        <h1>Log in to your account</h1>
        <p className="muted">
          {accounts
            ? 'Sign in with your MemoryHub account. What you can see follows your role and memberships.'
            : 'Use your OpenShift identity. Your access to memories follows your cluster roles.'}
        </p>
      </div>
      {accounts && (
        <form
          className="auth-form"
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => api.passwordLogin(login.trim(), password));
          }}
        >
          <div className="f">
            <label htmlFor="login">Email or username</label>
            <input id="login" className="in lg" value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username" required />
          </div>
          <div className="f">
            <label htmlFor="pw">Password</label>
            <input id="pw" className="in lg" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            <span className="hint">Forgot it? A platform admin can reset your account.</span>
          </div>
          {error && <div className="alert err-a">{error}</div>}
          <button type="submit" className="btn bp block lg" disabled={busy || !login || !password}>
            {busy ? 'Signing in…' : 'Log in'}
          </button>
          {signupOpen && (
            <p className="sm" style={{ margin: 0, textAlign: 'center' }}>
              New here? <a href="#/register">Create an account</a>
            </p>
          )}
        </form>
      )}
      {(!accounts || status?.mode === 'oauth-proxy') && (
        <button type="button" className="btn bp block lg" onClick={openshift}>
          Log in with OpenShift
        </button>
      )}
      {!accounts && (
        <p className="sm" style={{ margin: 0, textAlign: 'center' }}>
          Need a local account? <a href="#/register">Open registration options</a>
        </p>
      )}
      {status?.api_key_login && (
        <details className="auth-dev" open={!accounts}>
          <summary>Development cluster: sign in with an API key</summary>
          <form
            className="auth-form"
            style={{ marginTop: 14 }}
            onSubmit={(e) => {
              e.preventDefault();
              void run(() => api.login(key, user.trim() || undefined, devRole));
            }}
          >
            <div className="f">
              <label htmlFor="k">API key</label>
              <input id="k" className="in lg" type="password" placeholder="mh-dev-…" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" />
            </div>
            <div className="f">
              <label htmlFor="u">Your name (shown in the audit log)</label>
              <input id="u" className="in lg" value={user} onChange={(e) => setUser(e.target.value)} placeholder="dev-operator" />
            </div>
            <div className="f">
              <span className="lbl-t">Sign in as</span>
              <div className="seg full" role="group" aria-label="Sign in as">
                {(['admin', 'user'] as const).map((r) => (
                  <button key={r} type="button" className={devRole === r ? 'on' : ''} aria-pressed={devRole === r} onClick={() => setDevRole(r)}>
                    {r === 'admin' ? 'Platform admin' : 'User'}
                  </button>
                ))}
              </div>
            </div>
            {!accounts && error && <div className="alert err-a">{error}</div>}
            <button type="submit" className="btn bg block lg" disabled={busy || !key}>
              {busy ? 'Checking…' : 'Continue with API key'}
            </button>
          </form>
        </details>
      )}
      {status && !accounts && !status.api_key_login && status.mode !== 'oauth-proxy' && (
        <p className="sm muted" style={{ margin: 0 }}>
          No sign-in is configured on this deployment (open development mode).{' '}
          <a href={DOCS} target="_blank" rel="noopener noreferrer">
            Learn about authentication
          </a>
        </p>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Sign up (user)                                                      */
/* ------------------------------------------------------------------ */

const usernameFrom = (email: string) =>
  email
    .split('@')[0]
    .toLowerCase()
    .replace(/[^a-z0-9._-]/g, '')
    .slice(0, 40);

const PasswordField: React.FC<{ id: string; value: string; onChange: (v: string) => void; min: number; label?: string }> = ({ id, value, onChange, min, label = 'Password' }) => {
  const checks = [
    { ok: value.length >= min, text: `${min}+ characters` },
    { ok: /[A-Za-z]/.test(value) && /[0-9\W_]/.test(value), text: 'letters and a digit or symbol' },
  ];
  return (
    <div className="f">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="in lg" type="password" value={value} onChange={(e) => onChange(e.target.value)} autoComplete="new-password" required />
      <span className="hint" aria-live="polite">
        {checks.map((c) => (
          <span key={c.text} className={c.ok ? 'ok' : ''} style={{ marginRight: 12 }}>
            {c.ok ? '✓' : '·'} {c.text}
          </span>
        ))}
      </span>
    </div>
  );
};

const passwordOk = (pw: string, min: number) => pw.length >= min && /[A-Za-z]/.test(pw) && /[0-9\W_]/.test(pw);

const RegisterForm: React.FC<{ status: AuthStatus | null; invite?: string; onDone: () => void }> = ({ status, invite, onDone }) => {
  const min = status?.password_min_length ?? 12;
  const signup = status?.signup;
  const [form, setForm] = useState({ display_name: '', email: '', username: '', password: '', confirm: '', job_title: '', projects: '', invite_code: invite ?? '' });
  const [userTouched, setUserTouched] = useState(false);
  const [accept, setAccept] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(false);
  const set = (k: keyof typeof form) => (v: string) =>
    setForm((f) => ({ ...f, [k]: v, ...(k === 'email' && !userTouched ? { username: usernameFrom(v) } : {}) }));

  if (status && !status.local_accounts) {
    return (
      <div className="auth-form">
        <h1>Registration options</h1>
        <p className="muted">
          Local accounts are not enabled on this deployment yet. You can sign in with OpenShift, or ask a platform admin to enable local accounts if you need email and password login.
        </p>
        <a className="btn bp block lg" href="#/login">
          Back to log in
        </a>
      </div>
    );
  }
  if (pending) {
    return (
      <div className="auth-form">
        <h1>Request sent</h1>
        <p className="muted">
          Your account <b>{form.username}</b> is waiting for a platform admin to approve it. You can log in as soon as it is approved.
        </p>
        <a className="btn bp block lg" href="#/login">
          Back to log in
        </a>
      </div>
    );
  }

  const mode: SignupMode = signup?.mode ?? 'invite';
  const needsInvite = mode === 'invite' || mode === 'closed';
  const policy =
    mode === 'open'
      ? 'Anyone can create an account.'
      : mode === 'domain'
        ? `Accounts are limited to ${signup?.allowed_domains.join(', ')} email addresses.`
        : mode === 'invite'
          ? 'You need an invite code from a platform admin.'
          : 'Sign-up is closed; you can still join with an invite code.';
  const valid =
    form.display_name.trim() &&
    /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email) &&
    /^[a-z0-9][a-z0-9._-]{1,62}$/.test(form.username) &&
    passwordOk(form.password, min) &&
    form.password === form.confirm &&
    accept &&
    (!needsInvite || form.invite_code.trim());

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.register({
        display_name: form.display_name.trim(),
        email: form.email.trim(),
        username: form.username.trim(),
        password: form.password,
        job_title: form.job_title.trim() || undefined,
        requested_projects: form.projects.split(',').map((p) => p.trim()).filter(Boolean),
        invite_code: form.invite_code.trim() || undefined,
        accept_privacy: accept,
      });
      if (res.status === 'pending') setPending(true);
      else onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="auth-form" onSubmit={submit}>
      <div>
        <h1>Create your account</h1>
        <p className="muted">
          {policy}
          {signup?.require_approval && !form.invite_code ? ' A platform admin approves new accounts.' : ''}
        </p>
      </div>
      <div className="grid2">
        <div className="f">
          <label htmlFor="rn">Full name</label>
          <input id="rn" className="in lg" value={form.display_name} onChange={(e) => set('display_name')(e.target.value)} autoComplete="name" required />
        </div>
        <div className="f">
          <label htmlFor="rj">Job title (optional)</label>
          <input id="rj" className="in lg" value={form.job_title} onChange={(e) => set('job_title')(e.target.value)} placeholder="Platform engineer" />
        </div>
      </div>
      <div className="f">
        <label htmlFor="re">Work email</label>
        <input id="re" className="in lg" type="email" value={form.email} onChange={(e) => set('email')(e.target.value)} autoComplete="email" required />
      </div>
      <div className="f">
        <label htmlFor="ru">Username</label>
        <input
          id="ru"
          className="in lg mono"
          value={form.username}
          onChange={(e) => {
            setUserTouched(true);
            set('username')(e.target.value.toLowerCase());
          }}
          autoComplete="username"
          required
        />
        <span className="hint">Your user-scope memories are owned by this ID. Lowercase letters, digits, dot, dash or underscore.</span>
      </div>
      <div className="grid2">
        <PasswordField id="rp" value={form.password} onChange={set('password')} min={min} />
        <div className="f">
          <label htmlFor="rc">Confirm password</label>
          <input id="rc" className="in lg" type="password" value={form.confirm} onChange={(e) => set('confirm')(e.target.value)} autoComplete="new-password" required />
          {form.confirm && form.confirm !== form.password && <span className="field-err">Passwords do not match</span>}
        </div>
      </div>
      <div className="f">
        <label htmlFor="rpr">Projects you work on (optional)</label>
        <input id="rpr" className="in lg" value={form.projects} onChange={(e) => set('projects')(e.target.value)} placeholder="memoryhub-ui, payments-api" />
        <span className="hint">Comma-separated. Shown to the admin who approves you; project owners grant access.</span>
      </div>
      {(needsInvite || form.invite_code) && (
        <div className="f">
          <label htmlFor="ri">Invite code</label>
          <input id="ri" className="in lg mono" value={form.invite_code} onChange={(e) => set('invite_code')(e.target.value)} required={needsInvite} />
        </div>
      )}
      <label className="consent">
        <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
        <span>
          I understand how my memories are handled: their content is visible to me and to the projects, roles and campaigns I share it with. Platform admins see only
          metadata — counts, scopes, activity and health — never what a memory says. Every access is audited.
        </span>
      </label>
      {error && <div className="alert err-a">{error}</div>}
      <button type="submit" className="btn bp block lg" disabled={busy || !valid}>
        {busy ? 'Creating account…' : 'Create account'}
      </button>
      <p className="sm" style={{ margin: 0, textAlign: 'center' }}>
        Already have an account? <a href="#/login">Log in</a>
      </p>
    </form>
  );
};

/* ------------------------------------------------------------------ */
/* First-run setup (platform admin)                                     */
/* ------------------------------------------------------------------ */

const STEPS = ['Organization', 'Admin account', 'Sign-up policy', 'Privacy', 'Review'] as const;

const SIGNUP_OPTIONS: { value: SignupMode; title: string; text: string }[] = [
  { value: 'invite', title: 'Invite only', text: 'Admins hand out single-use invite codes. Recommended.' },
  { value: 'domain', title: 'Company email domains', text: 'Anyone with an allowed email domain can sign up.' },
  { value: 'open', title: 'Open', text: 'Anyone who can reach the dashboard can sign up.' },
  { value: 'closed', title: 'Closed', text: 'Only admins create accounts (via invites).' },
];

const SetupWizard: React.FC<{ status: AuthStatus | null; onDone: () => void }> = ({ status, onDone }) => {
  const [step, setStep] = useState(0);
  const [token, setToken] = useState('');
  const [org, setOrg] = useState({ name: '', contact_email: '' });
  const [admin, setAdmin] = useState({ display_name: '', email: '', username: '', password: '', confirm: '' });
  const [userTouched, setUserTouched] = useState(false);
  const [signup, setSignup] = useState<SetupPayload['signup']>({ mode: 'invite', allowed_domains: [], require_approval: true });
  const [domains, setDomains] = useState('');
  const [privacy, setPrivacy] = useState<SetupPayload['privacy']>({
    admin_readable_scopes: ['project', 'campaign', 'role', 'organizational', 'enterprise'],
    break_glass: true,
    break_glass_hours: 24,
    break_glass_approvers: 2,
    notify_owner: true,
  });
  const [security, setSecurity] = useState<SetupPayload['security']>({ session_hours: 12, password_min_length: 12 });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const domainList = useMemo(
    () =>
      domains
        .split(/[\s,]+/)
        .map((d) => d.trim().toLowerCase().replace(/^@/, ''))
        .filter(Boolean),
    [domains],
  );
  const emailOk = (e: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e);
  const stepValid = [
    Boolean(org.name.trim()) && (!org.contact_email || emailOk(org.contact_email)) && (!status?.setup_token_required || token.trim()),
    Boolean(admin.display_name.trim()) &&
      emailOk(admin.email) &&
      /^[a-z0-9][a-z0-9._-]{1,62}$/.test(admin.username) &&
      passwordOk(admin.password, security.password_min_length) &&
      admin.password === admin.confirm,
    signup.mode !== 'domain' || domainList.length > 0,
    true,
    true,
  ];

  const toggleScope = (s: string) =>
    setPrivacy((p) => ({
      ...p,
      admin_readable_scopes: p.admin_readable_scopes.includes(s) ? p.admin_readable_scopes.filter((x) => x !== s) : [...p.admin_readable_scopes, s],
    }));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.setup({
        setup_token: token.trim() || undefined,
        organization: { name: org.name.trim(), contact_email: org.contact_email.trim() },
        admin: { display_name: admin.display_name.trim(), email: admin.email.trim(), username: admin.username.trim(), password: admin.password },
        signup: { ...signup, allowed_domains: signup.mode === 'domain' ? domainList : [] },
        privacy,
        security,
      });
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-form">
      <div>
        <span className="lbl blue">First-run setup</span>
        <h1 style={{ marginTop: 10 }}>Set up MemoryHub for your organization</h1>
        <p className="muted">
          Create the first platform admin and decide who can join and what admins may see. You can change everything later under Accounts &amp; sign-up and
          Settings.
        </p>
      </div>
      <ol className="steps" aria-label="Setup steps">
        {STEPS.map((label, i) => (
          <li key={label} className={i === step ? 'on' : i < step ? 'done' : ''} aria-current={i === step ? 'step' : undefined}>
            <span>{i < step ? '✓' : i + 1}</span>
            {label}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <section className="auth-form">
          <div className="f">
            <label htmlFor="on">Organization name</label>
            <input id="on" className="in lg" value={org.name} onChange={(e) => setOrg({ ...org, name: e.target.value })} placeholder="Acme Healthcare" required />
            <span className="hint">Shown on the sign-in page and in invite emails.</span>
          </div>
          <div className="f">
            <label htmlFor="oc">Security contact email (optional)</label>
            <input id="oc" className="in lg" type="email" value={org.contact_email} onChange={(e) => setOrg({ ...org, contact_email: e.target.value })} placeholder="security@acme.com" />
            <span className="hint">Receives break-glass requests and privacy questions.</span>
          </div>
          {status?.setup_token_required && (
            <div className="f">
              <label htmlFor="st">Setup token</label>
              <input id="st" className="in lg mono" type="password" value={token} onChange={(e) => setToken(e.target.value)} required />
              <span className="hint">From the MEMORYHUB_UI_SETUP_TOKEN secret of this deployment.</span>
            </div>
          )}
        </section>
      )}

      {step === 1 && (
        <section className="auth-form">
          <div className="alert">
            <Icon.Info />
            <span>
              The platform admin manages users, agents, keys, rules and settings and sees memory <b>metadata</b> — never the content of personal, project, campaign
              or role memories.
            </span>
          </div>
          <div className="f">
            <label htmlFor="an">Full name</label>
            <input id="an" className="in lg" value={admin.display_name} onChange={(e) => setAdmin({ ...admin, display_name: e.target.value })} autoComplete="name" />
          </div>
          <div className="f">
            <label htmlFor="ae">Work email</label>
            <input
              id="ae"
              className="in lg"
              type="email"
              value={admin.email}
              onChange={(e) => setAdmin({ ...admin, email: e.target.value, username: userTouched ? admin.username : usernameFrom(e.target.value) })}
              autoComplete="email"
            />
          </div>
          <div className="f">
            <label htmlFor="au">Username</label>
            <input
              id="au"
              className="in lg mono"
              value={admin.username}
              onChange={(e) => {
                setUserTouched(true);
                setAdmin({ ...admin, username: e.target.value.toLowerCase() });
              }}
            />
          </div>
          <div className="grid2">
            <PasswordField id="ap" value={admin.password} onChange={(v) => setAdmin({ ...admin, password: v })} min={security.password_min_length} />
            <div className="f">
              <label htmlFor="ac">Confirm password</label>
              <input id="ac" className="in lg" type="password" value={admin.confirm} onChange={(e) => setAdmin({ ...admin, confirm: e.target.value })} autoComplete="new-password" />
              {admin.confirm && admin.confirm !== admin.password && <span className="field-err">Passwords do not match</span>}
            </div>
          </div>
        </section>
      )}

      {step === 2 && (
        <section className="auth-form">
          <fieldset className="choice">
            <legend className="lbl-t">Who can create an account?</legend>
            {SIGNUP_OPTIONS.map((o) => (
              <label key={o.value} className={`radio ${signup.mode === o.value ? 'on' : ''}`}>
                <input type="radio" name="mode" checked={signup.mode === o.value} onChange={() => setSignup({ ...signup, mode: o.value })} />
                <span>
                  <b className="sm">{o.title}</b>
                  <span className="hint" style={{ display: 'block' }}>
                    {o.text}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>
          {signup.mode === 'domain' && (
            <div className="f">
              <label htmlFor="dm">Allowed email domains</label>
              <input id="dm" className="in lg mono" value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="acme.com, acme-health.org" />
            </div>
          )}
          <div className="swrow">
            <span>
              Admin approves new accounts
              <span className="hint" style={{ display: 'block' }}>
                Self-registered people wait in the Accounts queue. Invited people are approved by their invite.
              </span>
            </span>
            <Switch on={signup.require_approval} onChange={(v) => setSignup({ ...signup, require_approval: v })} label="Admin approves new accounts" />
          </div>
          <div className="grid2">
            <div className="f">
              <label htmlFor="sh">Session length (hours)</label>
              <input id="sh" className="in lg" type="number" min={1} max={24} value={security.session_hours} onChange={(e) => setSecurity({ ...security, session_hours: Number(e.target.value) })} />
            </div>
            <div className="f">
              <label htmlFor="pl">Minimum password length</label>
              <input id="pl" className="in lg" type="number" min={10} max={64} value={security.password_min_length} onChange={(e) => setSecurity({ ...security, password_min_length: Number(e.target.value) })} />
            </div>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="auth-form">
          <div>
            <p className="lbl-t" style={{ margin: '0 0 8px' }}>
              What may platform admins read?
            </p>
            <div className="fx">
              <label>
                <span>
                  <input type="checkbox" checked={false} disabled aria-describedby="always-private" /> User memories
                </span>
                <span className="sm muted">metadata only</span>
              </label>
              {[
                ['project', 'Project'],
                ['campaign', 'Campaign'],
                ['role', 'Role'],
                ['organizational', 'Organizational'],
                ['enterprise', 'Enterprise'],
              ].map(([s, label]) => (
                <label key={s}>
                  <span>
                    <input type="checkbox" checked={privacy.admin_readable_scopes.includes(s)} onChange={() => toggleScope(s)} /> {label} memories
                  </span>
                  <span className="sm muted">{privacy.admin_readable_scopes.includes(s) ? 'readable · moderated' : 'metadata only'}</span>
                </label>
              ))}
            </div>
            <p id="always-private" className="hint" style={{ marginTop: 8 }}>
              Personal (user) memories are never readable to admins. A super-user can open them only for an incident, with a reference, for a limited time.
            </p>
          </div>
          <div className="swrow">
            <span>
              Super-user incident access
              <span className="hint" style={{ display: 'block' }}>
                Super-users (set by the deployment) open user memories with an incident reference; access expires and every memory opened is audited.
              </span>
            </span>
            <Switch on={privacy.break_glass} onChange={(v) => setPrivacy({ ...privacy, break_glass: v })} label="Super-user incident access" />
          </div>
          {privacy.break_glass && (
            <div className="grid2">
              <div className="f">
                <label htmlFor="bh">A grant lasts at most (hours)</label>
                <input id="bh" className="in lg" type="number" min={1} max={72} value={privacy.break_glass_hours} onChange={(e) => setPrivacy({ ...privacy, break_glass_hours: Number(e.target.value) })} />
              </div>
            </div>
          )}
          <div className="swrow">
            <span>Tell the owner when a super-user opens their memory</span>
            <Switch on={privacy.notify_owner} onChange={(v) => setPrivacy({ ...privacy, notify_owner: v })} label="Notify the owner" />
          </div>
        </section>
      )}

      {step === 4 && (
        <section className="auth-form">
          <dl className="dl wide">
            <dt>Organization</dt>
            <dd>{org.name}</dd>
            <dt>Platform admin</dt>
            <dd>
              {admin.display_name} · <span className="mono">{admin.username}</span> · {admin.email}
            </dd>
            <dt>Sign-up</dt>
            <dd>
              {SIGNUP_OPTIONS.find((o) => o.value === signup.mode)?.title}
              {signup.mode === 'domain' ? ` (${domainList.join(', ')})` : ''}
              {signup.require_approval ? ' · admin approval' : ''}
            </dd>
            <dt>Admins may read</dt>
            <dd>{privacy.admin_readable_scopes.length ? privacy.admin_readable_scopes.join(', ') + ' memories (never user)' : 'no memory content'}</dd>
            <dt>Break-glass</dt>
            <dd>{privacy.break_glass ? `${privacy.break_glass_approvers} approval(s), expires after ${privacy.break_glass_hours} h` : 'off'}</dd>
            <dt>Sessions</dt>
            <dd>
              {security.session_hours} h · passwords {security.password_min_length}+ characters
            </dd>
          </dl>
          {error && <div className="alert err-a">{error}</div>}
        </section>
      )}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between', flexWrap: 'wrap' }}>
        <button type="button" className="btn bg" disabled={step === 0 || busy} onClick={() => setStep((s) => s - 1)}>
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button type="button" className="btn bp" disabled={!stepValid[step]} onClick={() => setStep((s) => s + 1)}>
            Continue
          </button>
        ) : (
          <button type="button" className="btn bp" disabled={busy || !stepValid.every(Boolean)} onClick={submit}>
            {busy ? 'Creating…' : 'Create admin and finish setup'}
          </button>
        )}
      </div>
    </div>
  );
};

export default Login;
