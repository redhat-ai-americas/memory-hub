import { expect, test, type Page } from '@playwright/test';
import { entityId, memoryId, mockBff, type MockedBff, type Role } from './fixtures';

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
      await expect(page.getByRole('button', { name: 'Timeline' })).toHaveCount(0);
      await expect(page.getByRole('link', { name: /Export/ })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Timeline' })).toHaveCount(0);
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

    test('curation rule shows its version history', async ({ page }) => {
      const bff = await mockBff(page, role);
      const errors = watch(page);
      await page.goto('/#/curation?rule=rule-org');
      await expect(page.getByText('Version history')).toBeVisible();
      await expect(page.getByText('Test on sample')).toHaveCount(0);
      expect(bff.calls).toContain('GET /api/rules/rule-org/history');
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

test('admin: resolves a contradiction and adds a project member', async ({ page }) => {
  const bff = await mockBff(page, 'admin');
  const errors = watch(page);
  await page.goto('/#/review');
  await page.getByRole('button', { name: 'Mark resolved', exact: true }).first().click();
  expect(bff.calls).toContain(`PATCH /api/contradictions/55555555-5555-4555-8555-555555555555`);
  await page.goto('/#/projects');
  await page.getByRole('button', { name: '+ Add member' }).click();
  await expect(page.getByRole('dialog')).toContainText('Add members to atlas-planner');
  await expect(page.getByText('Teams')).toHaveCount(0);
  expectClean(bff, errors);
});
