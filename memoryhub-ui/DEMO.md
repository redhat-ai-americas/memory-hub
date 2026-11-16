# MemoryHub standalone UI demo

This branch renders the three MemoryHub interface roles with synthetic examples. The role selector in the account menu is a presentation control; it is not authentication or authorization. Every action changes in-memory frontend data only and resets on refresh. The app never contacts a MemoryHub backend, database, auth service, agent, API, or MCP endpoint.

## Local build and preview

```bash
cd memoryhub-ui/frontend
npm ci --no-audit --no-fund
npm run build
npm run preview -- --host 127.0.0.1
# Open http://127.0.0.1:4173/#/overview
```

Run the browser checks from the same directory:

```bash
npx playwright test e2e/demo.spec.ts --reporter=line --workers=1
```

The frontend needs no environment variables. The included `server.mjs` serves the production build on port 8080 with `/healthz` for OpenShift probes and a Content Security Policy that blocks network connections from the app.

## QA cluster preview

Authenticate to the target OpenShift cluster first, using your own credentials. From the repository root on branch `memoryhub-ui`:

```bash
MEMORYHUB_UI_NAMESPACE=memoryhub-ui memoryhub-ui/deploy/build.sh
MEMORYHUB_UI_NAMESPACE=memoryhub-ui memoryhub-ui/deploy/deploy.sh
oc get route memoryhub-ui -n memoryhub-ui -o jsonpath='https://{.spec.host}/'
```

The expected route is `https://memoryhub-ui-memoryhub-ui.apps.ocp.crz5h.sandbox1099.opentlc.com/`. The build context contains only the frontend source, `server.mjs`, and the Containerfile. The Deployment has one static Node container and no backend service, OAuth proxy, secrets, or database settings.

The scripts make cluster changes, so run them only when you are ready to deploy. This branch does not deploy itself.

## Turn the demo on

The synthetic data lives in `frontend/src/api/demo.ts`, but the build does **not** use it by default: `npm run build` produces the normal dashboard that calls the backend under `/api`. To build the standalone demo:

1. In `frontend/src/api/client.ts`, import the demo module and short-circuit `request()` when a build flag is set:

   ```ts
   import { demoRequest } from './demo';

   const DEMO = import.meta.env.VITE_DEMO === '1';

   async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
     if (DEMO) return (await demoRequest(method, path, body)) as T;
     // … the existing fetch() code stays as it is
   }
   ```

   Platform Operations (`api/platform.ts`) goes through the same `request()`, so it is covered too.

2. Build with the flag: `VITE_DEMO=1 npm run build`. For the container image, set it before the build step in the `Containerfile`, e.g. `ENV VITE_DEMO=1` above `RUN npm run build`.

3. Open the app. It starts as **Super Admin**; switch to Platform admin or User from the account menu (top right). Every change lives in browser memory and resets on reload. A Super Admin can enter any demo tenant from Tenants → Enter tenant console.

4. `server.mjs` already blocks all network calls (`connect-src 'none'`), which is what the demo needs. Do not serve the normal (non-demo) build with `server.mjs` — it would block the API.

`e2e/demo.spec.ts` was written for the first version of the demo (it looks for "Interactive demo" and a "Choose demo role" button). It is skipped unless `MEMORYHUB_DEMO=1` is set and needs updating to the current account menu before it can run.
