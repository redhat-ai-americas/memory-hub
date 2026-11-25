import { expect, test, type Page, type Route } from '@playwright/test';
import type { BrowseResponse, EntitiesResponse, EntityMergePreview, GraphAll, GraphNeighbourhood } from '../src/types';
import { entityId, memoryId, mockBff, type Role } from './fixtures';

const filters = {
  scope: 'project', actor: 'mchen', project: 'atlas-planner', domain: 'robotics',
  minw: '0.2', maxw: '0.5', from: '2026-01-01', to: '2026-11-01',
  branch: 'evidence', flag: 'has_branches', entity: entityId, entityName: 'Atlas gripper',
};
const apiFilters = [
  'scope', 'actor', 'project', 'domain', 'min_weight', 'max_weight',
  'created_from', 'created_to', 'branch_type', 'flag', 'entity',
];

test('a failed new filter cannot display or select the previous query results', async ({ page }) => {
  await mockBff(page, 'user');
  const pending: Route[] = [];
  await page.route('**/api/memories/browse?**', async (route) => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get('min_weight') === '0.5' && params.get('max_weight') === '0.1') pending.push(route);
    else await route.fallback();
  });
  await page.goto('/#/memories');
  await expect(page.getByRole('table')).toBeVisible();
  await page.evaluate(() => { window.location.hash = '/memories?minw=0.5&maxw=0.1'; });
  await expect.poll(() => pending.length).toBe(1);
  await expect(page.getByRole('table')).toHaveCount(0);
  await pending[0].fulfill({ status: 422, json: { detail: 'Invalid weight range' } });
  await expect(page.getByText('Invalid weight range', { exact: true })).toBeVisible();
  await expect(page.getByRole('table')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add relationship', exact: true })).toHaveCount(0);

  await page.evaluate(() => { window.location.hash = '/memories'; });
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByText('Invalid weight range', { exact: true })).toHaveCount(0);
});

test('graph Reset restores current versions and keeps browse filters', async ({ page }) => {
  await mockBff(page, 'user');
  await page.goto('/#/memories?view=graph&tab=all&depth=3&scope=project&minw=0.2');
  const settings = page.getByRole('complementary', { name: 'Graph settings' });
  const request = page.waitForRequest((r) => {
    const url = new URL(r.url());
    return url.pathname === '/api/graph/all' && url.searchParams.get('tab') === 'current';
  });
  await settings.getByRole('button', { name: 'Reset', exact: true }).click();
  const reset = new URL((await request).url()).searchParams;
  expect(reset.get('tab')).toBe('current');
  expect(reset.get('scope')).toBe('project');
  expect(reset.get('min_weight')).toBe('0.2');
  const params = new URLSearchParams(new URL(page.url()).hash.split('?')[1]);
  expect(params.get('tab')).toBe('current');
  expect(params.has('depth')).toBe(false);
});

for (const role of ['user', 'admin'] satisfies Role[]) {
  for (const writable of [false, true]) {
    for (const focused of [false, true]) {
      test(`${role}: ${focused ? 'focused' : 'all'} graph relationship action follows write=${writable}`, async ({ page }) => {
        await mockBff(page, role, (key, payload) => {
          const capabilities = { write: writable, moderate: false };
          if (key === 'GET /api/graph/all') {
            const graph = payload as GraphAll;
            return { ...graph, nodes: graph.nodes.map((node) => ({ ...node, capabilities })) };
          }
          if (key === 'GET /api/graph/neighbourhood') {
            const graph = payload as GraphNeighbourhood;
            return { ...graph, focus: { ...graph.focus, capabilities },
              nodes: graph.nodes.map((node) => ({ ...node, capabilities })) };
          }
          return payload;
        });
        const focus = focused ? `&gfocus=memory&focus=${memoryId}` : '';
        await page.goto(`/#/memories?view=graph&sel=${memoryId}${focus}`);
        const panel = page.getByRole('complementary', { name: 'Selected memory' });
        await expect(panel.getByRole('link', { name: 'Open memory', exact: true })).toBeVisible();
        const action = panel.getByRole('button', { name: 'Relationship', exact: true });
        if (writable) {
          await action.click();
          await expect(page.getByRole('dialog', { name: 'Add relationship' })).toBeVisible();
        } else {
          await expect(action).toHaveCount(0);
        }
      });
    }
  }
}

for (const role of ['user', 'admin'] satisfies Role[]) {
  for (const empty of [false, true]) {
    test(`${role}: ${empty ? 'empty results reset clears search and filters' : 'Clear all removes every filter and keeps search'}`, async ({ page }) => {
      await mockBff(page, role, (key, payload) => {
        if (key !== 'GET /api/memories/browse' || !empty) return payload;
        return { ...(payload as BrowseResponse), items: [], total: 0 };
      });
      const params = new URLSearchParams({ ...filters, q: 'torque', tab: 'all', sort: 'weight', per: '50', page: '3' });
      await page.goto(`/#/memories?${params}`);
      await expect(page.getByLabel('Created from (UTC)')).toHaveValue(filters.from);
      const request = page.waitForRequest((r) => {
        const url = new URL(r.url());
        return url.pathname === '/api/memories/browse';
      });
      await page.getByRole('button', { name: empty ? 'Clear search and filters' : 'Clear all', exact: true }).click();
      const cleared = new URL((await request).url()).searchParams;
      for (const key of apiFilters) expect(cleared.has(key), key).toBe(false);
      expect(cleared.get('q')).toBe(empty ? null : 'torque');
      expect(cleared.get('page')).toBe('1');
      expect(cleared.get('tab')).toBe('all');
      expect(cleared.get('sort')).toBe('weight');
      expect(cleared.get('per_page')).toBe('50');
      const remaining = new URLSearchParams(new URL(page.url()).hash.split('?')[1]);
      for (const key of Object.keys(filters)) expect(remaining.has(key), key).toBe(false);
      await expect(page.getByLabel('Maximum weight')).toHaveValue('');
      await expect(page.getByLabel('Created from (UTC)')).toHaveValue('');
      await expect(page.getByLabel('Created through (UTC)')).toHaveValue('');
      await expect(page.getByLabel('Has branch type')).toHaveValue('');
      await expect(page.getByRole('textbox', { name: 'Search memories', exact: true })).toHaveValue(empty ? '' : 'torque');
    });
  }
}

async function mergeDialog(page: Page) {
  await mockBff(page, 'user', (key, payload) => {
    if (key !== 'GET /api/entities') return payload;
    const entities = payload as EntitiesResponse;
    return { ...entities, items: [
      { ...entities.items[0], id: 'target-a', name: 'Target A' },
      { ...entities.items[0], id: 'target-b', name: 'Target B' },
    ] };
  });
  const previews: Route[] = [];
  const merges: string[] = [];
  await page.route(`**/api/entities/${entityId}/merge`, async (route) => {
    const body = route.request().postDataJSON() as { into: string; dry_run: boolean };
    if (body.dry_run) previews.push(route);
    else {
      merges.push(body.into);
      await route.fulfill({ json: preview(body.into, false) });
    }
  });
  await page.goto(`/#/entity/${entityId}`);
  await page.getByRole('button', { name: 'Merge into…' }).click();
  const dialog = page.getByRole('dialog');
  const select = async (name: string) => {
    const count = previews.length;
    await dialog.getByRole('radio', { name: new RegExp(name) }).check();
    await expect.poll(() => previews.length).toBe(count + 1);
    return previews[count];
  };
  return { dialog, select, merges, confirm: dialog.getByRole('button', { name: 'Merge', exact: true }) };
}

function preview(id: string, dryRun = true): EntityMergePreview {
  return {
    source: { id: entityId, name: 'Atlas gripper', entity_type: 'object', aliases: [] },
    target: { id, name: id === 'target-a' ? 'Target A' : 'Target B', entity_type: 'object', aliases: [] },
    moving: 1, both: 0, staying: 0, aliases_after: [], source_removed: !dryRun, memories: [], dry_run: dryRun,
  };
}

for (const fails of [false, true]) {
  test(`entity merge requires the selected target's preview${fails ? ' even after an error' : ''}`, async ({ page }) => {
    const { dialog, select, merges, confirm } = await mergeDialog(page);
    await expect(confirm).toBeDisabled();
    const first = await select('Target A');
    await first.fulfill({ json: preview('target-a') });
    await expect(dialog.getByRole('status')).toContainText('Target A');
    await expect(confirm).toBeEnabled();
    const second = await select('Target B');
    await expect(confirm).toBeDisabled();
    await expect(dialog.getByRole('status')).toHaveCount(0);
    expect(merges).toEqual([]);
    if (fails) {
      await second.fulfill({ status: 409, json: { detail: 'Selected target cannot be merged' } });
      await expect(page.getByText('Selected target cannot be merged', { exact: true })).toBeVisible();
      await expect(confirm).toBeDisabled();
      expect(merges).toEqual([]);
    } else {
      await second.fulfill({ json: preview('target-b') });
      await expect(dialog.getByRole('status')).toContainText('Target B');
      await expect(confirm).toBeEnabled();
      await confirm.click();
      await expect.poll(() => merges).toEqual(['target-b']);
    }
  });
}

for (const fails of [false, true]) {
  test(`a late merge preview ${fails ? 'error' : 'response'} cannot affect the current selection`, async ({ page }) => {
    const { dialog, select, merges, confirm } = await mergeDialog(page);
    const first = await select('Target A');
    const second = await select('Target B');
    await second.fulfill({ json: preview('target-b') });
    await expect(dialog.getByRole('status')).toContainText('Target B');
    await expect(confirm).toBeEnabled();
    const finished = page.waitForEvent('requestfinished', (request) => request === first.request());
    await first.fulfill(fails
      ? { status: 409, json: { detail: 'Outdated preview failed' } }
      : { json: preview('target-a') });
    await finished;
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
    await expect(dialog.getByRole('status')).toContainText('Target B');
    await expect(page.getByText('Outdated preview failed', { exact: true })).toHaveCount(0);
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect.poll(() => merges).toEqual(['target-b']);
  });
}
