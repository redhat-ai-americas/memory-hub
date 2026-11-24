import { expect, test, type Page, type Route } from '@playwright/test';
import type { BrowseResponse, EntitiesResponse, EntityMergePreview } from '../src/types';
import { entityId, mockBff, type Role } from './fixtures';

const filters = {
  scope: 'project', actor: 'mchen', project: 'atlas-planner', domain: 'robotics',
  minw: '0.2', maxw: '0.5', from: '2026-01-01', to: '2026-11-01',
  branch: 'evidence', flag: 'has_branches', entity: entityId, entityName: 'Atlas gripper',
};
const apiFilters = [
  'scope', 'actor', 'project', 'domain', 'min_weight', 'max_weight',
  'created_from', 'created_to', 'branch_type', 'flag', 'entity',
];

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
