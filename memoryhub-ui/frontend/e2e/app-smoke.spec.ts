import { expect, test } from '@playwright/test';
import { memoryId, mockDashboardApi } from './fixtures';

test.beforeEach(async ({ page }) => {
  await mockDashboardApi(page);
});

test.describe('primary navigation', () => {
  test('opens every primary destination', async ({ page }) => {
    const pageErrors: Error[] = [];
    page.on('pageerror', (error) => pageErrors.push(error));

    await page.goto('/#/overview');
    await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible();

    const destinations = [
      ['Memory browser', 'memories', 'Memory browser'],
      ['Entities', 'entities', 'Entities'],
      ['Search playground', 'search', 'Search playground'],
      ['Projects & teams', 'projects', 'Projects & teams'],
      ['Review queue', 'review', 'Review queue'],
      ['Curation rules', 'curation', 'Curation & compaction'],
      ['Audit & forensics', 'audit', 'Audit & forensics'],
      ['Users & agents', 'identities', 'Agents & identities'],
      ['OAuth clients & keys', 'clients', 'OAuth clients & keys'],
      ['Settings', 'settings', 'Tenant settings'],
    ] as const;

    for (const [linkName, path, heading] of destinations) {
      await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: linkName, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`#/${path}$`));
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
    }

    expect(pageErrors, pageErrors.map((error) => error.stack || error.message).join('\n')).toEqual([]);
  });
});

test.describe('shell controls', () => {
  test('toggles navigation and opens utility menus', async ({ page }) => {
    await page.goto('/#/overview');

    const navToggle = page.getByRole('button', { name: 'Hide navigation' });
    await navToggle.click();
    await expect(page.getByRole('button', { name: 'Show navigation' })).toBeVisible();
    await page.getByRole('button', { name: 'Show navigation' }).click();
    await expect(page.getByRole('button', { name: 'Hide navigation' })).toBeVisible();

    await page.getByRole('button', { name: 'Help' }).click();
    await expect(page.getByRole('menu')).toContainText('Documentation');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('menu')).toBeHidden();

    await page.getByRole('button', { name: 'Account' }).click();
    await expect(page.getByRole('menu')).toContainText('Signed in as admin');
  });

  test('global search and review shortcuts navigate to the expected screens', async ({ page }) => {
    await page.goto('/#/overview');
    await page.getByRole('link', { name: 'Search memories' }).click();
    await expect(page).toHaveURL(/#\/search$/);
    await expect(page.getByRole('heading', { name: 'Search playground', exact: true })).toBeVisible();

    await page.getByRole('link', { name: 'Review queue', exact: true }).click();
    await expect(page).toHaveURL(/#\/review$/);
    await expect(page.getByRole('heading', { name: 'Review queue', exact: true })).toBeVisible();
  });
});

test.describe('overview activity', () => {
  test('charts memory operations and loads each activity range', async ({ page }) => {
    await page.goto('/#/overview');
    await expect(page.getByRole('heading', { name: 'Memory operations', exact: true })).toBeVisible();
    await expect(page.getByRole('img', { name: /Memory operations in 7 daily buckets/ })).toBeVisible();

    const rangeGroup = page.getByRole('group', { name: 'Memory operation range' });
    await expect(rangeGroup.getByRole('button')).toHaveCount(6);
    for (const label of ['All time', '1h', '12h', '1d', '7d', '30d']) {
      await expect(rangeGroup.getByRole('button', { name: label, exact: true })).toBeVisible();
    }

    const overviewRequest = page.waitForRequest((request) => request.url().includes('/api/overview?range=1d'));
    await rangeGroup.getByRole('button', { name: '1d', exact: true }).click();
    await overviewRequest;
    await expect(page.getByText('Last 24 hours', { exact: true })).toBeVisible();
    await expect(page.getByRole('img', { name: /24 hourly buckets/ })).toBeVisible();

    const refreshRequest = page.waitForRequest((request) => request.url().includes('/api/overview?range=1d'));
    await page.getByRole('button', { name: 'Refresh memory operations' }).click();
    await refreshRequest;
  });

  test('KPI tiles link to their screens', async ({ page }) => {
    await page.goto('/#/overview');
    await page.getByRole('link', { name: /Agents connected/ }).click();
    await expect(page).toHaveURL(/#\/identities$/);
  });

  test('renders the category mix as a pie with a legend', async ({ page }) => {
    await page.goto('/#/overview');
    await expect(page.getByRole('heading', { name: 'Memory categories', exact: true })).toBeVisible();
    await expect(page.getByRole('img', { name: /^Memory categories:/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /tooling/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /containers/ })).toBeVisible();
  });
});

test.describe('entities', () => {
  test('browses extracted entities and links them to their memories', async ({ page }) => {
    await page.goto('/#/entities');
    await expect(page.getByRole('heading', { name: 'Entities', exact: true })).toBeVisible();
    await expect(page.getByRole('tab', { name: /All/ })).toBeVisible();
    await expect(page.getByRole('link', { name: 'MemoryHub UI' })).toHaveAttribute('href', /#\/entity\//);
    await expect(page.getByText('memoryhub-ui', { exact: true })).toBeVisible();
    await page.getByLabel('Search entities').fill('MemoryHub');
    await page.getByRole('button', { name: 'Apply filters' }).click();
    await expect(page).toHaveURL(/#\/entities\?q=MemoryHub/);
  });
});

test.describe('memory graph', () => {
  test('table/graph toggle, focus, layouts, depth and relationship filters', async ({ page }) => {
    await page.goto('/#/memories');
    await page.getByRole('group', { name: 'View as' }).getByRole('button', { name: 'Graph' }).click();
    await expect(page).toHaveURL(/view=graph/);
    // Graph view swaps the table filters for graph settings and hides the state tabs.
    await expect(page.getByRole('heading', { name: 'Graph settings' })).toBeVisible();
    await expect(page.getByRole('tab', { name: /All versions/ })).toHaveCount(0);
    await expect(page.getByRole('img', { name: /2 memories and 1 relationships/ })).toBeVisible();

    await page.locator('svg g.node').first().click();
    await expect(page.getByRole('link', { name: 'Open memory' })).toHaveAttribute('href', new RegExp(memoryId));
    await page.getByRole('button', { name: 'Show only its connections' }).click();
    await expect(page).toHaveURL(/gfocus=memory/);

    await page.getByRole('group', { name: 'Depth' }).getByRole('button', { name: '3 hops' }).click();
    await expect(page).toHaveURL(/depth=3/);

    // Time is its own view now, not a graph layout.
    await expect(page.getByRole('group', { name: 'Layout' }).getByRole('button', { name: 'Timeline' })).toHaveCount(0);

    const related = page.getByRole('checkbox', { name: 'related_to' });
    await expect(related).toBeChecked();
    await related.uncheck();
    await expect(related).not.toBeChecked();
  });

  test('graph says when it is truncated and offers a bigger limit', async ({ page }) => {
    await page.route('**/api/graph/all**', (route) =>
      route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ nodes: [], edges: [], total: 900, truncated: true, left_out: 600, max_nodes: 300, limit_ceiling: 1500, prefer: 'connected', orphan_count: 0, hidden_links: 12, metadata_only: false }),
      }),
    );
    await page.goto('/#/memories?view=graph');
    await expect(page.getByText(/Showing 0 of 900 memories/)).toBeVisible();
    await page.getByRole('button', { name: 'Draw up to 600' }).click();
    await expect(page).toHaveURL(/glimit=600/);
  });

  test('old graph links land in the browser graph view', async ({ page }) => {
    await page.goto(`/#/graph?focus=${memoryId}`);
    await expect(page).toHaveURL(/#\/memories\?view=graph&gfocus=memory&focus=/);
  });
});

test.describe('write and credentials actions', () => {
  test('writes a memory through the modal', async ({ page }) => {
    await page.goto('/#/memories');
    await expect(page.getByRole('heading', { name: 'Memory browser', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Write memory' }).click();
    const dialog = page.getByRole('dialog', { name: 'Write memory' });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('Content').fill('A test memory created by the browser smoke suite.');
    await dialog.getByRole('button', { name: 'Write memory', exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText('Memory written.')).toBeVisible();
  });

  test('opens the OAuth client form and submits it', async ({ page }) => {
    await page.goto('/#/clients');
    await expect(page.getByRole('heading', { name: 'OAuth clients & keys', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'New OAuth client' }).first().click();
    await expect(page.getByRole('dialog', { name: 'Create OAuth client' })).toBeVisible();
    await page.getByLabel('client_id').fill('browser-test-agent');
    await page.getByLabel('Display name').fill('Browser test agent');
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    const credentials = page.getByRole('dialog', { name: 'Copy these credentials now' });
    await expect(credentials).toBeVisible();
    await expect(credentials.getByText('browser-test-agent', { exact: true })).toBeVisible();
  });
});

test.describe('memory workspace', () => {
  test('timeline view keeps filters and selection across views', async ({ page }) => {
    await page.goto('/#/memories?scope=project');
    await page.getByRole('group', { name: 'View as' }).getByRole('button', { name: 'Timeline' }).click();
    await expect(page).toHaveURL(/view=timeline/);
    await expect(page).toHaveURL(/scope=project/);
    await expect(page.getByRole('heading', { name: 'Timeline settings' })).toBeVisible();
    await expect(page.getByText('Filters from the table:')).toBeVisible();
    await page.locator('svg g.node').first().click();
    await expect(page).toHaveURL(/sel=/);
    await page.getByRole('group', { name: 'View as' }).getByRole('button', { name: 'Graph' }).click();
    await expect(page).toHaveURL(/sel=/);
  });

  test('old timeline layout links open the timeline view', async ({ page }) => {
    await page.goto('/#/memories?view=graph&layout=timeline');
    await expect(page).toHaveURL(/view=timeline/);
  });

  test('knowledge page cites its memories', async ({ page }) => {
    await page.goto('/#/knowledge');
    await page.getByRole('link', { name: /What memory knows about Admin User/ }).click();
    await expect(page).toHaveURL(/#\/knowledge\/me/);
    await expect(page.getByRole('heading', { name: 'In short' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Tooling' })).toBeVisible();
    await expect(page.getByText('+1 similar folded')).toBeVisible();
    await expect(page.locator('a.cite').first()).toHaveAttribute('href', new RegExp(memoryId));
  });

  test('entity page shows memories and offers rename and merge', async ({ page }) => {
    await page.goto('/#/entities');
    await page.getByRole('link', { name: 'MemoryHub UI' }).click();
    await expect(page.getByRole('heading', { name: /MemoryHub UI/ })).toBeVisible();
    await expect(page.getByText('Also known as ui.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Merge into…' })).toBeVisible();
    await page.getByRole('button', { name: 'Rename · aliases' }).click();
    await expect(page.getByRole('textbox', { name: 'Aliases' })).toHaveValue('ui');
  });

  test('deleted memories can be restored from the table', async ({ page }) => {
    let restored = false;
    await page.route('**/api/memories/bulk', async (route) => {
      restored = JSON.parse(route.request().postData() || '{}').action === 'restore';
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ done: [memoryId], errors: [] }) });
    });
    await page.goto('/#/memories?tab=deleted');
    await page.getByRole('checkbox', { name: 'Select memory' }).first().check();
    await page.getByRole('button', { name: 'Restore', exact: true }).click();
    await expect.poll(() => restored).toBe(true);
  });

  test('notifications open from the bell', async ({ page }) => {
    await page.goto('/#/overview');
    await page.getByRole('button', { name: /Notifications, 1 new/ }).click();
    await expect(page.getByText('Other agents used your memories 2 times today')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Getting started' })).toBeVisible();
  });
});

test.describe('quality, packs, documents, operations', () => {
  test('content tabs appear in the menu once they have content', async ({ page }) => {
    await page.goto('/#/overview');
    const nav = page.getByRole('navigation');
    await expect(nav.getByRole('link', { name: 'Knowledge', exact: true })).toBeVisible();
    // Documents and context packs live inside Knowledge, not in the menu.
    await expect(nav.getByRole('link', { name: 'Documents', exact: true })).toHaveCount(0);
    await expect(nav.getByRole('link', { name: 'Context packs', exact: true })).toHaveCount(0);
    await expect(nav.getByRole('link', { name: 'Operations', exact: true })).toBeVisible();
  });

  test('content tabs stay hidden while empty', async ({ page }) => {
    await page.route('**/api/nav-features', (route) => route.fulfill({ contentType: 'application/json', body: '{}' }));
    await page.goto('/#/overview');
    const nav = page.getByRole('navigation');
    await expect(nav.getByRole('link', { name: 'Memory browser', exact: true })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Knowledge', exact: true })).toHaveCount(0);
    await expect(nav.getByRole('link', { name: 'Operations', exact: true })).toHaveCount(0);
  });

  test('retrieval checks show recall and why a memory is missing', async ({ page }) => {
    await page.goto('/#/quality');
    await expect(page.getByText('50% · 1/2')).toBeVisible();
    await expect(page.getByText('below weight threshold')).toBeVisible();
    await page.getByRole('tab', { name: 'My search health' }).click();
    await expect(page.getByRole('heading', { name: 'Where matches are cut' })).toBeVisible();
  });

  test('context pack renders a preview within its budget', async ({ page }) => {
    await page.goto('/#/knowledge');
    await page.getByRole('tab', { name: 'Context packs' }).click();
    await expect(page).toHaveURL(/#\/knowledge\/packs$/);
    await page.getByRole('link', { name: /Local dev pack/ }).click();
    await expect(page).toHaveURL(/#\/knowledge\/packs\/p1/);
    await expect(page.getByRole('link', { name: 'Context packs' }).first()).toHaveAttribute('href', '#/knowledge/packs');
    await expect(page.getByText('≈12 of 2,000 tokens')).toBeVisible();
    await expect(page.getByText(/get_context_pack/)).toBeVisible();
  });

  test('documents are a tab of Knowledge', async ({ page }) => {
    await page.goto('/#/knowledge');
    await page.getByRole('tab', { name: 'Documents' }).click();
    await expect(page).toHaveURL(/#\/knowledge\/documents$/);
    await page.getByRole('link', { name: 'Dev handbook' }).click();
    await expect(page).toHaveURL(/#\/knowledge\/documents\/d1$/);
    await expect(page.getByRole('link', { name: 'Documents' }).first()).toHaveAttribute('href', '#/knowledge/documents');
  });

  test('old document and pack links redirect into Knowledge', async ({ page }) => {
    await page.goto('/#/documents/d1');
    await expect(page).toHaveURL(/#\/knowledge\/documents\/d1$/);
    await page.goto('/#/packs/p1');
    await expect(page).toHaveURL(/#\/knowledge\/packs\/p1$/);
  });

  test('document passages show their memories and can be selected', async ({ page }) => {
    await page.goto('/#/knowledge/documents/d1');
    await expect(page.getByRole('heading', { name: 'Dev handbook' })).toBeVisible();
    await page.getByRole('checkbox', { name: 'Passage 2' }).check();
    await expect(page.getByRole('button', { name: 'Write 1 memory' })).toBeEnabled();
  });

  test('operations lists jobs and offers a retry', async ({ page }) => {
    await page.goto('/#/operations');
    await expect(page.getByText('database timeout')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
  });
});

test.describe('Release 1 surface', () => {
  test('Labs features are hidden when Labs is off', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { labs: false });
    await page.goto('/#/overview');
    const nav = page.getByRole('navigation');
    await expect(nav.getByRole('link', { name: 'Memory browser', exact: true })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Knowledge', exact: true })).toHaveCount(0);
    await expect(nav.getByRole('link', { name: 'Memory hygiene', exact: true })).toHaveCount(0);
    await page.goto('/#/knowledge');
    await expect(page.getByText('A MemoryHub Labs feature')).toBeVisible();
  });

  test('old dreaming links open Dreaming', async ({ page }) => {
    await page.goto('/#/dreaming');
    await expect(page).toHaveURL(/#\/hygiene$/);
    await expect(page.getByRole('heading', { name: 'Dreaming', exact: true })).toBeVisible();
  });

  test('users get the connection check, not the admin rule list', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'user' });
    await page.goto('/#/overview');
    const nav = page.getByRole('navigation');
    // The connection check lives inside My agents & API keys now.
    await expect(nav.getByRole('link', { name: 'My agents & API keys', exact: true })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Curation rules', exact: true })).toHaveCount(0);
    await page.goto('/#/verify');
    await expect(page).toHaveURL(/#\/identities\?.*view=verify/);
    await expect(page.getByRole('tab', { name: 'Connection check' })).toBeVisible();
  });

  test('connection check runs and explains each failure', async ({ page }) => {
    await page.goto('/#/verify');
    await expect(page.getByText('No check has run yet')).toBeVisible();
    await page.getByRole('button', { name: 'Run check' }).first().click();
    await expect(page.getByText('Something is broken')).toBeVisible();
    const checks = page.getByRole('list', { name: 'Checks' });
    await expect(checks.getByText('Service unavailable')).toBeVisible();
    await expect(checks.getByText('round_trip.embeddings_unavailable')).toBeVisible();
    await expect(checks.getByText('Next: Join a project in Projects & teams.')).toBeVisible();
    await expect(checks.getByText('agent host').first()).toBeVisible();
  });

  test('host results can be pasted in', async ({ page }) => {
    await page.goto('/#/verify');
    await page.getByRole('button', { name: 'Add host result' }).click();
    await page.getByLabel('Result JSON').fill('not json');
    await page.getByRole('button', { name: 'Add result' }).click();
    await expect(page.getByText('That is not valid JSON.')).toBeVisible();
    await page.getByLabel('Result JSON').fill('{"schema":"memoryhub.verify/v1","checks":[{"id":"endpoint","status":"pass"}]}');
    await page.getByRole('button', { name: 'Add result' }).click();
    await expect(page.getByText('Host · claude-code')).toBeVisible();
  });

  test('connect page shows host support and the setup commands', async ({ page }) => {
    await page.goto('/#/connect');
    await expect(page.getByRole('cell', { name: /OpenCode/ })).toBeVisible();
    await page.getByLabel('Project').selectOption('memoryhub-ui');
    await expect(page.getByText('memoryhub config init --project memoryhub-ui --format claude-code')).toBeVisible();
    await page.getByLabel('Host').selectOption('goose');
    await expect(page.getByText('There is no Goose integration yet.', { exact: false })).toBeVisible();
  });

  test('memory-behavior profile is saved with a new revision', async ({ page }) => {
    await page.goto('/#/preferences');
    await expect(page.getByText('Agent hosts do not read it yet', { exact: false })).toBeVisible();
    await page.getByRole('radio', { name: /Conservative/ }).check();
    await expect(page.getByLabel('When to look for memories')).toHaveValue('explicit');
    const put = page.waitForRequest((r) => r.url().endsWith('/api/me/prefs') && r.method() === 'PUT');
    await page.getByRole('button', { name: 'Save changes' }).click();
    const body = (await put).postDataJSON();
    expect(body.behavior.template).toBe('conservative');
    await expect(page.getByText('Profile revision 2', { exact: false })).toBeVisible();
  });

  test('token counts are labelled as estimates', async ({ page }) => {
    await page.goto('/#/knowledge/packs/p1');
    await expect(page.getByText('≈12 of 2,000 tokens')).toHaveAttribute('title', /Estimated/);
  });
});

test.describe('#667 role tiers', () => {
  test('admins moderate every scope except user memories', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'admin' });
    await page.goto('/#/memories');
    await expect(page.getByRole('heading', { name: /Content moderation/ })).toBeVisible();
    await expect(page.getByText('Personal memories: metadata only')).toBeVisible();
    await expect(page.getByText('Personal memories are private.')).toBeVisible();
    await expect(page.getByRole('navigation').getByRole('link', { name: 'Incident access' })).toHaveCount(0);
  });

  test('super-users start incident access with a reference', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'superuser' });
    // A single-tenant server: no platform API, so the grant starts through /api/break-glass.
    await page.route('**/api/platform/**', (route) => route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Not Found' }) }));
    await page.goto('/#/incident');
    await expect(page.locator('.sa-badge')).toHaveText('Super Admin');
    await page.getByRole('link', { name: 'Request incident access…' }).click();
    const next = page.getByRole('button', { name: /^Next/ });
    await page.getByRole('textbox', { name: /Incident/ }).fill('1234');
    await expect(next).toBeDisabled();
    await page.getByRole('textbox', { name: /Incident/ }).fill('INC-1234');
    await next.click();
    await page.getByRole('textbox', { name: /Owner/ }).fill('alice');
    await page.getByRole('textbox', { name: /Target records/ }).fill('11111111-1111-4111-8111-111111111111');
    await next.click();
    await page.getByRole('textbox', { name: /Reason/ }).fill('Spill of a customer contract into a user memory');
    await next.click();
    await next.click();
    const req = page.waitForRequest((r) => r.url().endsWith('/api/break-glass') && r.method() === 'POST');
    await page.getByRole('button', { name: 'Activate grant', exact: true }).click();
    expect((await req).postDataJSON().incident_ref).toBe('INC-1234');
  });

  test('an active grant is shown on every page', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'superuser', grant: true });
    // Tenant screens open inside the tenant console; the server confirms the tenant (/api/me).
    await page.addInitScript(() => sessionStorage.setItem('memoryhub.tenantContext', JSON.stringify({ tenant: 'demo-tenant', reason: 'test', since: new Date().toISOString() })));
    await page.goto('/#/memories');
    await expect(page.locator('.incident-banner')).toContainText('INC-1234');
    await page.goto('/#/incident');
    await expect(page.getByRole('heading', { name: 'Incident access', exact: true })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'INC-1234' }).first()).toBeVisible();
  });

  test('users keep their own curation rules', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'user' });
    await page.goto('/#/overview');
    await expect(page.getByRole('navigation').getByRole('link', { name: 'My curation rules' })).toBeVisible();
    await page.goto('/#/incident');
    await expect(page.getByText('Only super-users can open this')).toBeVisible();
  });
});

test.describe('#676 central project provisioning', () => {
  test('users cannot create projects or manage members', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'user' });
    await page.goto('/#/projects');
    await expect(page.getByRole('heading', { name: 'memoryhub-ui' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create project' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Add member' })).toBeDisabled();
    await expect(page.getByText('Needs project.manage', { exact: false })).toBeVisible();
  });

  test('admins create a project with its members', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'admin' });
    await page.goto('/#/projects');
    await page.getByRole('button', { name: 'Create project' }).first().click();
    await page.getByLabel('Name').fill('team-x');
    await page.getByLabel('Project admins').click();
    await page.getByRole('option', { name: /Carol Diaz/ }).click();
    await page.getByRole('button', { name: 'Done' }).click();
    await page.getByLabel('Members').click();
    const list = page.getByRole('listbox', { name: 'People and agents' });
    await expect(list.getByRole('option', { name: /Carol Diaz/ })).toHaveAttribute('aria-disabled', 'true');
    await expect(list.getByText("alice's agent")).toBeVisible();
    await page.getByLabel('Search people and agents').fill('ali');
    await list.getByRole('option', { name: /Alice Ng/ }).click();
    await list.getByRole('option', { name: /claude-code-alice/ }).click();
    await page.getByLabel('Search people and agents').fill('dave');
    await list.getByRole('option', { name: /Add “dave”/ }).click();
    await page.getByRole('button', { name: 'Done' }).click();
    const req = page.waitForRequest((r) => r.url().endsWith('/api/projects') && r.method() === 'POST');
    await page.getByRole('button', { name: 'Create with 4 people' }).click();
    expect((await req).postDataJSON().members).toEqual([
      { user_id: 'carol', role: 'admin' },
      { user_id: 'alice', role: 'member' },
      { user_id: 'claude-code-alice', role: 'member' },
      { user_id: 'dave', role: 'member' },
    ]);
  });

  test('adding members picks from the list and skips current members', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'admin' });
    await page.goto('/#/projects');
    await page.getByRole('button', { name: 'Add member', exact: true }).click();
    await page.getByLabel('People and agents').click();
    const list = page.getByRole('listbox', { name: 'People and agents' });
    await expect(list.getByRole('option', { name: /Admin User/ })).toHaveAttribute('aria-disabled', 'true');
    await list.getByRole('option', { name: /bob/ }).click();
    await list.getByRole('option', { name: /Carol Diaz/ }).click();
    await page.getByRole('button', { name: 'Done' }).click();
    const reqs: string[] = [];
    page.on('request', (r) => r.method() === 'POST' && r.url().includes('/members') && reqs.push(r.postDataJSON().user_id));
    await page.getByRole('button', { name: 'Add 2 members' }).click();
    await expect.poll(() => reqs).toEqual(['bob', 'carol']);
  });

  test('project admins change member roles', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'admin' });
    const now = '2026-10-19T12:00:00.000Z';
    await page.route('**/api/projects/memoryhub-ui', (route) =>
      route.request().method() !== 'GET'
        ? route.fallback()
        : route.fulfill({ json: {
            name: 'memoryhub-ui', description: 'UI project', invite_only: false, created_at: now, created_by: 'admin', memories: 1, last_write: now, members: 2, campaigns: [], agents_today: 1,
            members_list: [{ user_id: 'admin', role: 'admin', joined_at: now, joined_by: 'admin' }, { user_id: 'bob', role: 'member', joined_at: now, joined_by: 'admin' }],
            focus_history: [], focus_available: true, loading_policy: 'default', provisioning: 'central', my_role: 'admin', can_manage: true, can_delete: true, archived: false, policies: {},
          } }),
    );
    await page.goto('/#/projects');
    // The owner's role is fixed; other members get a role picker.
    await expect(page.getByLabel('Project role of admin')).toHaveCount(0);
    const bob = page.getByLabel('Project role of bob');
    await expect(bob).toHaveValue('member');
    const req = page.waitForRequest((r) => r.url().endsWith('/api/projects/memoryhub-ui/members/bob') && r.method() === 'PATCH');
    await bob.selectOption('admin');
    expect((await req).postDataJSON().role).toBe('admin');
  });

  test('archived projects are hidden until asked for, and can be restored', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'admin' });
    await page.goto('/#/projects');
    const table = page.locator('table.proj-tbl');
    await expect(table.getByText('memoryhub-ui', { exact: true })).toBeVisible();
    await expect(table.getByText('old-pilot')).toHaveCount(0);
    await page.getByRole('tab', { name: /^Archived/ }).click();
    await expect(table.getByText('old-pilot')).toBeVisible();
    await expect(table.getByText('memoryhub-ui', { exact: true })).toHaveCount(0);
    await table.getByText('old-pilot').click();
    await expect(page.getByRole('button', { name: 'Edit policies' })).toBeDisabled();
    const req = page.waitForRequest((r) => r.url().endsWith('/api/projects/old-pilot/unarchive'));
    await page.getByRole('button', { name: 'Restore', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Unarchive' }).click();
    await req;
  });

  test('project admins archive; deleting needs the name typed', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'admin' });
    await page.goto('/#/projects');
    await page.getByRole('button', { name: 'Archive', exact: true }).click();
    const archived = page.waitForRequest((r) => r.url().endsWith('/api/projects/memoryhub-ui/archive'));
    await page.getByRole('dialog').getByRole('button', { name: 'Archive' }).click();
    await archived;

    await page.goto('/#/projects?project=memoryhub-ui');
    await page.getByRole('button', { name: 'Delete project…' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('a new project can never be called memoryhub-ui');
    await expect(dialog).toContainText('archive the project instead');
    const confirm = dialog.getByRole('button', { name: 'Delete project and memories' });
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel('Type memoryhub-ui to confirm').fill('memoryhub');
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel('Type memoryhub-ui to confirm').fill('memoryhub-ui');
    const del = page.waitForRequest((r) => r.url().endsWith('/api/projects/memoryhub-ui') && r.method() === 'DELETE');
    await confirm.click();
    expect((await del).postDataJSON()).toEqual({ confirm: 'memoryhub-ui' });
  });

  test('users neither archive nor delete projects', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'user' });
    await page.goto('/#/projects');
    await expect(page.getByRole('link', { name: 'Browse memories' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Archive', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Delete project', exact: true })).toBeDisabled();
  });

  test('project policies are saved from the edit form', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'admin' });
    await page.goto('/#/projects');
    await page.getByRole('button', { name: 'Edit policies' }).click();
    await page.getByLabel('Keep relevant for (days)').fill('30');
    await page.getByLabel('Memory limit').fill('0');
    await expect(page.getByText('new memories are refused until fewer than 0 remain', { exact: false })).toBeVisible();
    await page.getByLabel('Memory limit').fill('1000');
    await expect(page.getByText('they are not deleted', { exact: false })).toBeVisible();
    const req = page.waitForRequest((r) => r.url().endsWith('/api/projects/memoryhub-ui') && r.method() === 'PATCH');
    await page.getByRole('button', { name: 'Save' }).click();
    expect((await req).postDataJSON().policies).toEqual({ ttl_days: 30, max_memories: 1000, default_weight: null });
  });

  test('users only get Delete on memories they wrote', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'user', canDelete: false });
    await page.goto('/#/memories');
    await page.getByRole('button', { name: 'Actions', exact: true }).first().click();
    await expect(page.getByRole('menu')).toBeVisible();
    await expect(page.getByRole('menu').getByRole('button', { name: 'Delete' })).toHaveCount(0);
  });

  test('users write only where they may, to a project picked from a list', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'user' });
    await page.goto('/#/memories');
    await page.getByRole('button', { name: 'Write memory' }).first().click();
    const dialog = page.getByRole('dialog');
    const scope = dialog.getByLabel('Scope');
    await expect(scope.locator('option')).toHaveText(['User', 'Project', 'Campaign']);
    await expect(page.getByText('Only you and your agents see it.')).toBeVisible();
    await scope.selectOption('project');
    const project = dialog.getByLabel('Project ID', { exact: true });
    await expect(project.locator('option')).toHaveText(['Select a project', 'memoryhub-ui']);
    await project.selectOption('memoryhub-ui');
    await expect(page.getByText('Every member of memoryhub-ui and their agents see it.')).toBeVisible();
    await dialog.getByLabel('Content').fill('Deploy with the golden test first');
    const req = page.waitForRequest((r) => r.url().endsWith('/api/memories') && r.method() === 'POST');
    await dialog.getByRole('button', { name: 'Write memory' }).click();
    const body = (await req).postDataJSON();
    expect(body).toMatchObject({ scope: 'project', scope_id: 'memoryhub-ui' });
    expect(body.weight).toBeUndefined();
  });

  test('a refused request says so instead of offering a retry', async ({ page }) => {
    await page.unrouteAll();
    await mockDashboardApi(page, { role: 'user' });
    await page.route('**/api/projects?**', (route) => route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: 'Not for you' }) }));
    await page.goto('/#/projects');
    await expect(page.getByText('You don’t have access to this')).toBeVisible();
    await expect(page.getByText('Not for you')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Try again' })).toHaveCount(0);
  });
});
