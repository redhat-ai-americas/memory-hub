import { expect, test, type Page } from '@playwright/test';
import { entityId, memoryId, mockBff, reportId, type MockedBff, type Role } from './fixtures';

/** Every screen a role can open, its menu label and the page heading. */
const SCREENS: Record<Role, [string, string, string][]> = {
  user: [
    ['Overview', 'overview', 'Overview'],
    ['Memory browser', 'memories', 'Memory browser'],
    ['Search playground', 'search', 'Search playground'],
    ['Entities', 'entities', 'Entities'],
    ['Projects', 'projects', 'Projects'],
    ['My agents & API keys', 'identities', 'My agents & API keys'],
    ['My curation rules', 'curation', 'My curation rules'],
  ],
  admin: [
    ['Tenant overview', 'overview', 'Tenant overview'],
    ['Agents & identities', 'identities', 'Agents & identities'],
    ['OAuth clients & keys', 'clients', 'OAuth clients & keys'],
    ['Projects', 'projects', 'Projects'],
    ['Content moderation', 'memories', 'Content moderation'],
    ['Contradictions', 'review', 'Contradictions'],
    ['Curation rules', 'curation', 'Curation rules'],
  ],
};

const watch = (page: Page) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.stack || e.message));
  return errors;
};

const expectClean = (bff: MockedBff, errors: string[]) => {
  expect(bff.unknown, `calls to endpoints the BFF does not serve:\n${bff.unknown.join('\n')}`).toEqual([]);
  expect(errors, errors.join('\n')).toEqual([]);
};

for (const role of ['user', 'admin'] as const) {
  test.describe(`${role}`, () => {
    test('opens every menu item and only calls BFF routes', async ({ page }) => {
      const bff = await mockBff(page, role);
      const errors = watch(page);
      await page.goto('/#/overview');
      const nav = page.getByRole('navigation', { name: 'Primary' });
      await expect(nav.getByRole('link')).toHaveCount(SCREENS[role].length);
      for (const [label, path, heading] of SCREENS[role]) {
        await nav.getByRole('link', { name: new RegExp(`^${label}`) }).click();
        await expect(page).toHaveURL(new RegExp(`#/${path}`));
        await expect(page.getByRole('heading', { level: 1 })).toContainText(heading);
      }
      expectClean(bff, errors);
    });

    test('memory browser: table, graph and memory page', async ({ page }) => {
      const bff = await mockBff(page, role);
      const errors = watch(page);
      await page.goto('/#/memories');
      await expect(page.getByRole('link', { name: /Gripper torque limit/ })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Timeline' })).toBeVisible();
      await expect(page.getByRole('link', { name: /Export/ })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Timeline' })).toBeVisible();
      await page.getByRole('button', { name: 'Graph', exact: true }).click();
      await expect(page).toHaveURL(/view=graph/);
      await expect(page.locator('svg circle').first()).toBeVisible();
      expect(bff.calls).toContain('GET /api/graph/all');
      await page.goto(`/#/memory/${memoryId}`);
      await expect(page.getByRole('heading', { level: 1 })).toContainText('Gripper torque limit');
      expect(bff.calls).toContain(`GET /api/memory/${memoryId}/context`);
      await expect(page.getByText('Access log')).toHaveCount(0);
      await expect(page.getByText('Similar memories')).toBeVisible();
      expectClean(bff, errors);
    });

    test('search playground ranks memories', async ({ page }) => {
      test.skip(role === 'admin', 'Search is not in the admin menu');
      const bff = await mockBff(page, role);
      const errors = watch(page);
      await page.goto('/#/search');
      await page.getByLabel('Query', { exact: true }).fill('torque');
      await page.getByRole('button', { name: 'Run search' }).click();
      await expect(page.locator('.res')).toHaveCount(2);
      expect(bff.calls).toContain('POST /api/search');
      await expect(page.getByText('Saved queries')).toHaveCount(0);
      expectClean(bff, errors);
    });

    test('curation rule shows its version without the technical history route', async ({ page }) => {
      const bff = await mockBff(page, role);
      const errors = watch(page);
      await page.goto('/#/curation?rule=rule-org');
      await expect(page.getByText(/earlier version kept for audit/)).toBeVisible();
      await expect(page.getByText('Version history')).toHaveCount(0);
      await expect(page.getByText('Test on sample')).toHaveCount(0);
      expect(bff.calls.some((c) => c.endsWith('/history'))).toBe(false);
      expectClean(bff, errors);
    });

    test('OAuth clients: create and rotate', async ({ page }) => {
      const bff = await mockBff(page, role);
      const errors = watch(page);
      await page.goto(role === 'user' ? '/#/identities?view=keys' : '/#/clients');
      await page.getByRole('button', { name: role === 'user' ? 'New OAuth client' : 'New service client' }).first().click();
      await page.getByLabel('client_id').fill('test-bot');
      await page.getByRole('button', { name: 'Create', exact: true }).click();
      await expect(page.getByText('Copy these credentials now')).toBeVisible();
      await page.keyboard.press('Escape');
      // Rotation needs ownership: a user owns their one agent; the admin only curator-agent of the three active clients.
      await expect(page.getByRole('button', { name: 'Rotate API key' })).toHaveCount(1);
      await expect(page.getByRole('button', { name: 'Revoke' })).toHaveCount(role === 'user' ? 1 : 3);
      await page.getByRole('button', { name: 'Rotate API key' }).first().click();
      await page.getByRole('button', { name: 'Rotate', exact: true }).click();
      expect(bff.calls).toContain('POST /api/clients');
      expect(bff.calls.some((c) => c.endsWith('/rotate-api-key'))).toBe(true);
      expectClean(bff, errors);
    });
  });
}

test('user: entity page renames only', async ({ page }) => {
  const bff = await mockBff(page, 'user');
  const errors = watch(page);
  await page.goto(`/#/entity/${entityId}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Atlas gripper');
  await page.getByRole('button', { name: 'Rename', exact: true }).click();
  await expect(page.getByLabel('Aliases')).toHaveCount(0);
  expectClean(bff, errors);
});

test('user: an entity the BFF would not let them change is read only', async ({ page }) => {
  const bff = await mockBff(page, 'user', (key, payload) =>
    key === `GET /api/entities/${entityId}` ? { ...(payload as object), can_edit: false } : payload,
  );
  const errors = watch(page);
  await page.goto(`/#/entity/${entityId}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Atlas gripper');
  await expect(page.getByText('Read only', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Rename', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Merge into…' })).toHaveCount(0);
  expectClean(bff, errors);
});

test('admin: no resolve button on a report about their own memory', async ({ page }) => {
  const bff = await mockBff(page, 'admin', (key, payload) => {
    if (!key.endsWith('/context')) return payload;
    const ctx = payload as { memory: Record<string, unknown> };
    return { ...ctx, memory: { ...ctx.memory, actor_id: 'dosei' } };
  });
  const errors = watch(page);
  await page.goto('/#/review');
  await expect(page.getByText('You wrote this memory, so another project admin has to resolve its reports.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Mark resolved' })).toHaveCount(0);
  expect(bff.calls.some((c) => c.startsWith('PATCH /api/contradictions/'))).toBe(false);
  expectClean(bff, errors);
});

test('admin: memory page quarantines, and hides what a personal memory says', async ({ page }) => {
  let personal = false;
  const bff = await mockBff(page, 'admin', (key, payload) => {
    if (!personal || !key.endsWith('/context')) return payload;
    const ctx = payload as { memory: Record<string, unknown>; versions: Record<string, unknown>[]; branches: Record<string, unknown>[] };
    return {
      ...ctx,
      memory: { ...ctx.memory, scope: 'user', scope_id: null, owner_id: 'mchen', redacted: true, content: '', stub: 'Content hidden', capabilities: { write: false, moderate: false }, can_delete: false },
      versions: ctx.versions.map((v) => ({ ...v, content: '' })),
      branches: ctx.branches.map((b) => ({ ...b, content: '' })),
      contradictions: [],
      similar: [],
    };
  });
  const errors = watch(page);
  await page.goto(`/#/memory/${memoryId}`);
  await page.getByRole('button', { name: 'Quarantine', exact: true }).click();
  await page.getByLabel('Reason').fill('Wrong torque value');
  await page.getByRole('dialog').getByRole('button', { name: 'Quarantine', exact: true }).click();
  expect(bff.calls).toContain('POST /api/memories/bulk');

  personal = true;
  await page.reload();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Personal memory · content hidden');
  await expect(page.getByText(/What it says is private to its owner/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Quarantine', exact: true })).toHaveCount(0);
  expectClean(bff, errors);
});

test('admin: cannot remove themselves from a project', async ({ page }) => {
  const bff = await mockBff(page, 'admin');
  const errors = watch(page);
  await page.goto('/#/project/atlas-planner');
  await expect(page.getByRole('button', { name: 'Remove mchen' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Remove dosei' })).toHaveCount(0);
  expectClean(bff, errors);
});

test('admin: resolves a contradiction and adds a project member', async ({ page }) => {
  const bff = await mockBff(page, 'admin');
  const errors = watch(page);
  await page.goto('/#/review');
  await page.getByRole('button', { name: 'Mark resolved', exact: true }).first().click();
  expect(bff.calls).toContain(`PATCH /api/contradictions/${reportId}`);
  expect(bff.calls).toContain(`GET /api/memory/${memoryId}/context`);
  await page.goto('/#/projects');
  await page.getByRole('button', { name: '+ Add member' }).click();
  await expect(page.getByRole('dialog')).toContainText('Add members to atlas-planner');
  await expect(page.getByText('Teams')).toHaveCount(0);
  expectClean(bff, errors);
});

/* ---------------- Memory browser (user) ---------------- */

const bodyOf = (bff: MockedBff, key: string) => bff.bodies.filter((b) => b.key === key).map((b) => b.body);

test('user: semantic search ranks, shows similarity and near-duplicates, and says when it fell back to text', async ({ page }) => {
  const bff = await mockBff(page, 'user');
  const errors = watch(page);
  await page.goto('/#/memories');
  await expect(page.getByText('near-duplicate 0.94')).toBeVisible();
  await expect(page.getByText('Near-duplicate (≥0.90)')).toBeVisible();
  await expect(page.getByText(/agent\s+claude-code-mchen/)).toBeVisible();

  await page.getByRole('textbox', { name: 'Search memories' }).fill('gripper torque');
  await page.getByRole('textbox', { name: 'Search memories' }).press('Enter');
  await expect(page.getByText('score 0.71')).toBeVisible();
  const searched = bff.calls.length;
  expect(bff.calls.filter((c) => c === 'GET /api/memories/browse').length).toBeGreaterThan(1);
  await expect(page.getByText('Embedding service unavailable — showing text matches.')).toHaveCount(0);
  // The URL carries semantic mode by default and relevance as the sort.
  await expect(page.getByRole('button', { name: 'Sort', exact: true })).toHaveText('Sort: Relevance');

  await page.getByRole('textbox', { name: 'Search memories' }).fill('torque?');
  await page.getByRole('textbox', { name: 'Search memories' }).press('Enter');
  await expect(page.getByText('Embedding service unavailable — showing text matches.')).toBeVisible();
  expect(bff.calls.length).toBeGreaterThan(searched);
  expectClean(bff, errors);
});

test('user: timeline view draws the same filters over time', async ({ page }) => {
  const bff = await mockBff(page, 'user');
  const errors = watch(page);
  await page.goto('/#/memories?scope=project');
  await page.getByRole('button', { name: 'Timeline' }).click();
  await expect(page.getByRole('img', { name: 'Timeline of 2 memories' })).toBeVisible();
  expect(bff.calls).toContain('GET /api/memories/timeline');
  await page.getByRole('button', { name: '30 days' }).click();
  await expect(page).toHaveURL(/tdays=30/);
  await page.getByRole('button', { name: /Project memory: Gripper torque limit/ }).click();
  await expect(page.getByRole('complementary', { name: 'Selected memory' }).getByRole('link', { name: 'Open' })).toBeVisible();
  expectClean(bff, errors);
});

test('user: bulk weight and promotion send what the BFF expects', async ({ page }) => {
  const bff = await mockBff(page, 'user', (key, payload) => {
    if (key !== 'GET /api/memories/browse') return payload;
    const b = payload as { items: Record<string, unknown>[] };
    // Personal memories: the ones a user may promote into a project.
    return { ...b, items: b.items.map((item) => ({ ...item, scope: 'user', scope_id: null, owner_id: 'mchen' })) };
  });
  const errors = watch(page);
  await page.goto('/#/memories');
  await page.getByRole('checkbox', { name: 'Select memory' }).first().check();
  await page.getByRole('button', { name: 'Change weight' }).click();
  await page.getByLabel(/Weight · /).fill('90');
  await page.getByRole('button', { name: 'Create new versions' }).click();
  await expect(page.getByText('Weight set to 0.90 — new versions created.')).toBeVisible();
  expect(bodyOf(bff, 'POST /api/memories/bulk')).toContainEqual({ action: 'weight', ids: [memoryId], weight: 0.9 });

  await page.getByRole('checkbox', { name: 'Select memory' }).first().check();
  await page.getByRole('button', { name: 'Promote to project' }).click();
  await expect(page.getByRole('dialog').getByLabel('Project')).toHaveValue('atlas-planner');
  await page.getByRole('button', { name: 'Copy it' }).click();
  await expect(page.getByText('1 copied to project atlas-planner.')).toBeVisible();
  expect(bodyOf(bff, 'POST /api/memories/bulk')).toContainEqual({
    action: 'promote', ids: [memoryId], target_scope: 'project', target_scope_id: 'atlas-planner',
  });
  expectClean(bff, errors);
});

test('user: delete reports what it forgot, and the Deleted tab restores it', async ({ page }) => {
  const bff = await mockBff(page, 'user');
  const errors = watch(page);
  await page.goto('/#/memories');
  await page.getByRole('checkbox', { name: 'Select memory' }).first().check();
  await page.getByRole('button', { name: 'Delete', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(page.getByText(/Forgot 1 memory — 2 versions and 1 branch in project · atlas-planner/)).toBeVisible();

  await page.getByRole('tab', { name: /Deleted/ }).click();
  await expect(page).toHaveURL(/tab=deleted/);
  // A deleted memory has no memory page to open.
  await expect(page.getByRole('link', { name: /Gripper torque limit/ })).toHaveCount(0);
  await page.getByRole('checkbox', { name: 'Select memory' }).first().check();
  await page.getByRole('button', { name: 'Restore', exact: true }).click();
  await expect(page.getByText(/Restored 1 memory — 2 versions and 1 branch/)).toBeVisible();
  expect(bodyOf(bff, 'POST /api/memories/bulk')).toContainEqual({ action: 'restore', ids: [memoryId] });
  expectClean(bff, errors);
});
