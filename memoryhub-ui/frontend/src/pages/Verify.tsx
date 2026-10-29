import React, { useState } from 'react';
import { api, ApiError } from '@/api/client';
import { PageHeader } from '@/components/Shell';
import { copyText, Empty, ErrorState, Icon, Modal, SkLines, useToast } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { buildHash } from '@/hooks/useHashRoute';
import type { VerifyCheck, VerifyList, VerifyResult, VerifyStatus } from '@/types';
import { errorMessage, fmtDateTime, fmtRelative } from '@/utils/format';

const STATUS: Record<VerifyStatus, { label: string; cls: string; mark: string }> = {
  pass: { label: 'Passed', cls: 'grn', mark: '✓' },
  warn: { label: 'Needs attention', cls: 'ylw', mark: '!' },
  fail: { label: 'Failed', cls: 'red', mark: '✕' },
  not_run: { label: 'Not run', cls: 'g', mark: '–' },
};

const STATE: Record<VerifyResult['summary']['state'], { title: string; cls: string; body: string }> = {
  pass: { title: 'Everything checked works', cls: 'ok-a', body: 'All checks that ran passed.' },
  warn: { title: 'Works, with things to fix', cls: 'warn-a', body: 'Nothing failed, but some checks need your attention.' },
  fail: { title: 'Something is broken', cls: 'err-a', body: 'At least one check failed. Each failed check says what to do next.' },
  partial: {
    title: 'Partly checked',
    cls: '',
    body: 'The checks that ran passed. Some can only run on the agent host, so this result is incomplete.',
  },
};

const SAMPLE = `{
  "schema": "memoryhub.verify/v1",
  "produced_by": { "tool": "memoryhub", "version": "…", "command": "…", "host": "claude-code", "profile_version": 1 },
  "context": { "endpoint": "https://…/mcp/", "tenant": "default", "identity": "my-agent", "project": "payments" },
  "checks": [
    { "id": "tool_discovery", "status": "pass", "explanation": "memory tools listed" },
    { "id": "cross_session", "status": "fail", "category": "host_integration_failed",
      "code": "cross_session.not_recalled", "explanation": "…", "next_action": "…" }
  ]
}`;

/** Connection check (R1-024): renders verifier results, never reimplements the tests. */
const Verify: React.FC = () => {
  const toast = useToast();
  const { data, error, loading, reload, setData } = useApi<VerifyList>(() => api.verifyResults(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [upload, setUpload] = useState(false);

  const run = async () => {
    setRunning(true);
    try {
      const r = await api.runVerify();
      if (data) setData({ ...data, results: [r, ...data.results].slice(0, 20) });
      setSelected(r.id);
      toast(r.summary.fail ? 'Check finished — something failed.' : 'Check finished.');
    } catch (e) {
      toast(errorMessage(e), 'err');
    } finally {
      setRunning(false);
    }
  };

  const added = (r: VerifyResult) => {
    if (data) setData({ ...data, results: [r, ...data.results].slice(0, 20) });
    setSelected(r.id);
    setUpload(false);
    toast('Host result added.');
  };

  const result = data?.results.find((r) => r.id === selected) ?? data?.results[0];
  const unauthorized = error instanceof ApiError && (error.status === 401 || error.status === 403);

  return (
    <>
      <PageHeader
        title="Connection check"
        description="Is MemoryHub set up correctly for you and your agents? Each check says what it found and, when something is wrong, what to do next. No secrets are shown or stored."
        actions={
          <>
            <button type="button" className="btn bs" onClick={() => setUpload(true)} disabled={!data}>
              Add host result
            </button>
            <button type="button" className="btn bp" onClick={run} disabled={running || !data}>
              <Icon.Refresh size={14} /> {running ? 'Checking…' : data?.results.length ? 'Run again' : 'Run check'}
            </button>
          </>
        }
      />
      <div className="body">
        {error && !data ? (
          <div className="card">
            {unauthorized ? (
              <Empty title="Sign in to check your connection">The connection check runs as you, so it needs a signed-in dashboard session.</Empty>
            ) : (
              <ErrorState error={error} onRetry={reload} title="The connection check is unavailable" />
            )}
          </div>
        ) : loading && !data ? (
          <div className="card">
            <SkLines lines={8} />
          </div>
        ) : (
          data && (
            <div className="row-wrap">
              <div className="col-main">
                <div className="alert">
                  <Icon.Info size={18} />
                  <span className="sm">
                    The dashboard checks the endpoint, your sign-in, identity, tenant and projects, and writes and reads back a test memory in your own scope, then removes it.{' '}
                    <b>Tool discovery</b> and <b>recall in a new session</b> can only be checked on the agent host. A host verifier command is planned (R1-026) and not released yet;
                    when it is, add its JSON result here.
                  </span>
                </div>
                {!result ? (
                  <section className="card">
                    <Empty
                      title="No check has run yet"
                      action={
                        <button type="button" className="btn bp" onClick={run} disabled={running}>
                          {running ? 'Checking…' : 'Run check'}
                        </button>
                      }
                    >
                      Takes a few seconds. It writes one test memory to your user scope and deletes it again.
                    </Empty>
                  </section>
                ) : (
                  <ResultCard result={result} />
                )}
              </div>
              <aside className="col-side">
                <section className="card">
                  <h3>History</h3>
                  {data.results.length === 0 ? (
                    <p className="sm muted">Results you run or add appear here. The last 20 are kept.</p>
                  ) : (
                    <ul className="vlist" style={{ marginTop: 10 }}>
                      {data.results.map((r) => (
                        <li key={r.id}>
                          <button type="button" className={`vhist ${r.id === result?.id ? 'on' : ''}`} onClick={() => setSelected(r.id)}>
                            <span>
                              <b className="sm">{r.source === 'host' ? `Host · ${r.produced_by.host || r.produced_by.tool || 'verifier'}` : 'Dashboard'}</b>
                              <span className="hint" style={{ display: 'block' }}>{fmtRelative(r.created_at)}</span>
                            </span>
                            <span className="sm">
                              {r.summary.fail > 0 && <span className="err">{r.summary.fail} failed </span>}
                              {r.summary.warn > 0 && <span className="warn">{r.summary.warn} to fix </span>}
                              {r.summary.fail === 0 && r.summary.warn === 0 && <span className="ok">{r.summary.pass} passed</span>}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
                <section className="card">
                  <h3>Next steps</h3>
                  <p className="sm" style={{ margin: '8px 0' }}>
                    Not connected yet? <a href={buildHash('/connect')}>Connect an agent</a> shows the supported hosts and the setup command.
                  </p>
                  <p className="sm muted" style={{ margin: 0 }}>
                    Failures use the categories of the shared failure model: {data.categories.map((c) => c.label.toLowerCase()).join(', ')}.
                  </p>
                </section>
              </aside>
            </div>
          )
        )}
      </div>
      {upload && <UploadModal onClose={() => setUpload(false)} onAdded={added} />}
    </>
  );
};

const ResultCard: React.FC<{ result: VerifyResult }> = ({ result }) => {
  const state = STATE[result.summary.state];
  const ctx = result.context as Record<string, unknown>;
  const pb = result.produced_by;
  return (
    <section className="card">
      <div className={`alert ${state.cls}`} style={{ marginBottom: 16 }}>
        <span>
          <b>{state.title}</b>
          <span className="sm" style={{ display: 'block' }}>
            {state.body} {result.summary.pass} passed · {result.summary.warn} to fix · {result.summary.fail} failed · {result.summary.not_run} not run
          </span>
        </span>
      </div>
      <dl className="dl">
        <dt>Produced by</dt>
        <dd>
          {result.source === 'dashboard' ? 'Dashboard checks' : [pb.tool, pb.version, pb.command].filter(Boolean).join(' · ') || 'Host verifier'}
          {pb.profile_version ? ` · profile v${pb.profile_version}` : ''}
        </dd>
        <dt>When</dt>
        <dd>{fmtDateTime(result.finished_at || result.created_at)}</dd>
        {typeof ctx.endpoint === 'string' && (
          <>
            <dt>Endpoint</dt>
            <dd className="mono">{ctx.endpoint}</dd>
          </>
        )}
        {typeof ctx.tenant === 'string' && (
          <>
            <dt>Tenant</dt>
            <dd className="mono">{ctx.tenant}</dd>
          </>
        )}
        {typeof ctx.identity === 'string' && (
          <>
            <dt>Identity</dt>
            <dd className="mono">{ctx.identity}</dd>
          </>
        )}
      </dl>
      <ul className="checks" aria-label="Checks">
        {result.checks.map((c) => (
          <CheckRow key={c.id} c={c} />
        ))}
      </ul>
    </section>
  );
};

const CheckRow: React.FC<{ c: VerifyCheck }> = ({ c }) => {
  const s = STATUS[c.status];
  return (
    <li className={`check ${c.status}`}>
      <span className={`lbl ${s.cls} ck-mark`} aria-label={s.label}>
        {s.mark}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <b>{c.title}</b>
          <span className="hint">{s.label}</span>
          {c.source === 'host' && <span className="tag">agent host</span>}
          {c.duration_ms !== null && <span className="hint">{c.duration_ms} ms</span>}
        </div>
        {c.explanation && <p className="sm" style={{ margin: '4px 0 0' }}>{c.explanation}</p>}
        {(c.status === 'fail' || c.status === 'warn') && (c.category_label || c.next_action) && (
          <div className="ck-next">
            {c.category_label && (
              <span className="sm">
                <b>{c.category_label}</b>
                {c.code && <span className="code" style={{ marginLeft: 6 }}>{c.code}</span>}
              </span>
            )}
            {c.next_action && <span className="sm">Next: {c.next_action}</span>}
          </div>
        )}
        {c.status === 'not_run' && c.next_action && <p className="hint" style={{ margin: '4px 0 0' }}>{c.next_action}</p>}
      </div>
    </li>
  );
};

const UploadModal: React.FC<{ onClose: () => void; onAdded: (r: VerifyResult) => void }> = ({ onClose, onAdded }) => {
  const toast = useToast();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setErr(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      setErr('That is not valid JSON.');
      return;
    }
    setBusy(true);
    try {
      onAdded(await api.uploadVerify(parsed));
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const onFile = async (f: File | undefined) => {
    if (f) setText(await f.text());
  };
  return (
    <Modal
      title="Add a host result"
      onClose={onClose}
      wide
      actions={
        <>
          <button type="button" className="btn bg" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn bp" disabled={!text.trim() || busy} onClick={submit}>
            {busy ? 'Adding…' : 'Add result'}
          </button>
        </>
      }
    >
      <p className="sm" style={{ marginTop: 0 }}>
        Paste the JSON a verifier produced on the agent host, in the <span className="code">memoryhub.verify/v1</span> format. Anything that looks like a token, key or password is
        removed before it is stored.
      </p>
      <div className="f">
        <label htmlFor="vj">Result JSON</label>
        <textarea id="vj" className="in mono" rows={10} value={text} onChange={(e) => setText(e.target.value)} placeholder={SAMPLE} />
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
        <label className="btn bs sm">
          Choose file…
          <input type="file" accept="application/json,.json" hidden onChange={(e) => onFile(e.target.files?.[0])} />
        </label>
        <button
          type="button"
          className="btn bg sm"
          onClick={async () => toast((await copyText(SAMPLE)) ? 'Example copied.' : 'Could not copy.', 'ok')}
        >
          Copy example
        </button>
      </div>
      {err && (
        <p className="sm err" role="alert" style={{ marginBottom: 0 }}>
          {err}
        </p>
      )}
    </Modal>
  );
};

export default Verify;
