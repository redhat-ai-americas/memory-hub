import { expect, test, type Page } from '@playwright/test';

// These checks need the standalone demo build (DEMO.md, "Turn the demo on") and were written for the first demo UI;
// update the role-switch steps to the current account menu before running them with MEMORYHUB_DEMO=1.
test.skip(!process.env.MEMORYHUB_DEMO, 'Standalone demo is off in this build');

const chooseRole = async (page: Page, name: 'Super Admin' | 'Platform Admin' | 'User') => {
  await page.getByRole('button', { name: 'Choose demo role' }).click();
  await page.getByRole('menuitemradio', { name: new RegExp(`^${name}`) }).click();
  await expect(page.locator('.role-pill')).toHaveText(name);
};

const openRoute = async (page: Page, route: string) => {
  await page.evaluate((next) => { window.location.hash = `#${next}`; }, route);
  await expect(page.locator('main h1')).toBeVisible();
  await expect(page.locator('main')).not.toContainText('Demo fixture missing');
};

test('all three demo roles can navigate their main pages without API traffic', async ({ page }) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => { if (request.url().includes('/api/') || request.url().includes('/mcp/')) apiRequests.push(request.url()); });
  await page.goto('/#/overview');
  await expect(page.getByText('Interactive demo')).toBeVisible();
  await expect(page.locator('.role-pill')).toHaveText('Super Admin');
  for (const route of ['/overview', '/memories', '/projects', '/review', '/curation', '/audit', '/identities', '/clients', '/accounts', '/settings', '/incident', '/search']) await openRoute(page, route);
  await chooseRole(page, 'Platform Admin');
  for (const route of ['/overview', '/memories', '/projects', '/review', '/curation', '/audit', '/accounts', '/settings', '/search']) await openRoute(page, route);
  await chooseRole(page, 'User');
  for (const route of ['/overview', '/memories', '/memory/demo-memory-3', '/projects', '/review', '/curation', '/audit', '/connect', '/verify', '/preferences', '/reads', '/knowledge', '/entities', '/quality', '/search']) await openRoute(page, route);
  expect(apiRequests).toEqual([]);
});

test('memory, project, audit and role controls are available in the demo', async ({ page }) => {
  await page.goto('/#/memories');
  await expect(page.getByRole('columnheader', { name: 'Relevant until' })).toBeVisible();
  await expect(page.getByRole('link', { name: /Atlas release notes belong/ }).first()).toHaveAttribute('href', /#\/memory\//);
  await openRoute(page, '/projects');
  await expect(page.getByText('atlas-demo').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Archived (1)' })).toBeVisible();
  await page.getByRole('button', { name: 'Archived (1)' }).click();
  await expect(page.getByText('old-pilot').first()).toBeVisible();
  await openRoute(page, '/audit');
  await expect(page.getByRole('heading', { name: 'Audit & forensics' })).toBeVisible();
  await chooseRole(page, 'User');
  await openRoute(page, '/memories');
  await expect(page.getByRole('columnheader', { name: 'Relevant until' })).toBeVisible();
});

test('navigation, tabs and project lifecycle work with in-memory state', async ({ page }) => {
  await page.goto('/#/overview');
  const links = await page.locator('nav[aria-label="Primary"] a').evaluateAll((items) => items.map((item) => item.getAttribute('href')).filter(Boolean) as string[]);
  for (const href of links) {
    await page.locator(`nav[aria-label="Primary"] a[href="${href}"]`).click();
    await expect(page.locator('main h1')).toBeVisible();
  }
  await openRoute(page, '/projects');
  await page.getByRole('tab', { name: /^Teams/ }).click();
  await expect(page).toHaveURL(/kind=teams/);
  await page.getByRole('tab', { name: /^Campaigns/ }).click();
  await expect(page).toHaveURL(/kind=campaigns/);
  await page.getByRole('tab', { name: /^Projects/ }).click();
  await page.getByRole('button', { name: 'More actions for atlas-demo' }).click();
  await page.getByRole('menu').getByRole('button', { name: 'Archive' }).click();
  await page.getByRole('dialog', { name: 'Archive atlas-demo?' }).getByRole('button', { name: 'Archive' }).click();
  await expect(page.getByRole('button', { name: 'Archived (2)' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Archived (1)' })).toBeVisible();
});

test('a user can write a synthetic memory and refresh resets it', async ({ page }) => {
  await page.goto('/#/overview');
  await chooseRole(page, 'User');
  await openRoute(page, '/memories');
  await page.getByRole('button', { name: 'Write memory' }).click();
  const dialog = page.getByRole('dialog', { name: 'Write memory' });
  await expect(dialog).toContainText('Demo only');
  await dialog.getByRole('textbox', { name: 'Content' }).fill('Synthetic note for browser state');
  await dialog.getByRole('button', { name: 'Write memory' }).click();
  await expect(page.locator('main')).toContainText('Synthetic note for browser state');
  await page.reload();
  await expect(page.locator('main')).not.toContainText('Synthetic note for browser state');
});
