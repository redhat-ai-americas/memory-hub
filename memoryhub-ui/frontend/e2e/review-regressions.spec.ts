import { expect, test } from '@playwright/test';
import { memoryId, mockDashboardApi } from './fixtures';

const filterQuery = 'tab=deleted&q=needle&mode=text&scope=project&actor=alice&project=p1&domain=security&minw=0.75&flag=contradicted&entity=33333333-3333-4333-8333-333333333333';
function expectFilters(url: string) {
  const params = new URL(url, 'http://test').searchParams;
  for (const [key, value] of new URLSearchParams(filterQuery)) {
    expect(params.get(key === 'minw' ? 'min_weight' : key)).toBe(value);
  }
}

test('switching browser views and exporting preserves every filter', async ({ page }) => {
  await mockDashboardApi(page);
  await page.goto(`/#/memories?${filterQuery}`);
  await expect(page.getByRole('heading', { name: 'Memory browser', exact: true })).toBeVisible();
  expectFilters((await page.getByRole('link', { name: 'Export JSONL' }).getAttribute('href'))!);
  const graphRequest = page.waitForRequest((r) => new URL(r.url()).pathname === '/api/graph/all');
  await page.getByRole('button', { name: 'Graph', exact: true }).click();
  expectFilters((await graphRequest).url());
  const timelineRequest = page.waitForRequest((r) => new URL(r.url()).pathname === '/api/memories/timeline');
  await page.getByRole('button', { name: 'Timeline', exact: true }).click();
  const timelineUrl = (await timelineRequest).url();
  expectFilters(timelineUrl);
  expect(new URL(timelineUrl).searchParams.get('days')).toBe('0');
});

test('write form uses server capabilities and the actual owner', async ({ page }) => {
  await mockDashboardApi(page, { role: 'user' });
  // A previously saved admin-only default must not reappear in the form.
  await page.route('**/api/me/prefs', (route) => route.fulfill({ json: { prefs: { write: { default_scope: 'enterprise', default_weight: 0.7 } } } }));
  await page.goto('/#/memories');
  await page.getByRole('button', { name: 'Write memory', exact: true }).click();
  await expect(page.locator('#wm-scope option')).toHaveText(['User', 'Project', 'Campaign']);
  await expect(page.getByLabel('Scope', { exact: true })).toHaveValue('user');
  await expect(page.getByLabel('Owner', { exact: true })).toHaveValue('admin');
  await expect(page.getByLabel('Owner', { exact: true })).toHaveAttribute('readonly', '');
  await page.getByLabel('Scope', { exact: true }).selectOption('project');
  await expect(page.locator('#wm-sid option')).toHaveText(['Select a project', 'memoryhub-ui']);
  await page.getByLabel('Project ID', { exact: true }).selectOption('memoryhub-ui');
  await page.getByLabel('Content', { exact: true }).fill('A project memory');
  const write = page.waitForRequest((r) => r.method() === 'POST' && new URL(r.url()).pathname === '/api/memories');
  await page.getByRole('dialog').getByRole('button', { name: 'Write memory', exact: true }).click();
  expect((await write).postDataJSON()).toMatchObject({ scope: 'project', scope_id: 'memoryhub-ui', owner_id: 'memoryhub-ui' });
});

for (const trigger of ['expiry', 'focus', 'storage', 'poll'] as const) {
  test(`incident access clears cached content on ${trigger}`, async ({ page }) => {
    const start = new Date('2026-11-02T12:00:00Z');
    await page.clock.install({ time: start });
    await mockDashboardApi(page, { role: 'superuser', grant: true });
    let revoked = false;
    let offline = false;
    const grant = { id: 'g1', incident_ref: 'INC-1234', justification: 'Investigate customer data exposure', expires_at: new Date(start.getTime() + 3600_000).toISOString() };
    await page.route('**/api/me', (route) => offline ? route.abort() : route.fulfill({ json: {
      username: 'admin', name: 'Admin', initials: 'AD', role: 'superuser', tenant_id: 'demo-tenant', source: 'api-key',
      access: { hidden_scopes: revoked ? ['user'] : [], break_glass: revoked ? null : grant },
    } }));
    await page.route('**/api/memories/browse?**', (route) => route.fulfill({ json: {
      items: [{ id: memoryId, stub: revoked ? 'Content hidden' : 'Private incident evidence', content_preview: revoked ? 'Content hidden' : 'Private incident evidence', scope: 'user', owner_id: 'alice', score: null, near_duplicate: null, weight: 0.8, version: 1, is_current: true, status: 'active', domains: [], entities: [], branch_summary: [], branch_count: 0, open_contradictions: 0, created_at: start.toISOString(), updated_at: start.toISOString(), redacted: revoked }],
      total: 1, page: 1, per_page: 20, tab_counts: { current: 1, all: 1, quarantined: 0, deleted: 0 }, facets: { scopes: [], writers: [], projects: [], domains: [], flags: {} },
    } }));
    await page.goto('/#/memories');
    await expect(page.locator('.incident-banner')).toBeVisible();
    await expect(page.getByText('Private incident evidence').first()).toBeVisible();
    revoked = true;
    if (trigger === 'expiry') {
      offline = true;
      await page.clock.fastForward(3600_001);
    } else if (trigger === 'poll') {
      await page.clock.fastForward(15_001);
    } else if (trigger === 'focus') {
      await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    } else {
      await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', { key: 'memoryhub:authorization-changed', newValue: 'revoked' })));
    }
    await expect(page.locator('.incident-banner')).toHaveCount(0);
    await expect(page.getByText('Private incident evidence')).toHaveCount(0);
    if (!offline) await expect(page.getByText('Content hidden').first()).toBeVisible();
  });
}
