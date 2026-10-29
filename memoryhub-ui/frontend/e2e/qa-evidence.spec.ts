import { expect, test } from '@playwright/test';
import { mockDashboardApi } from './fixtures';

test('captures UI smoke evidence for report', async ({ page }) => {
  await mockDashboardApi(page);
  await page.goto('/#/overview');
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible();
  await page.screenshot({ path: '../../docs/qa/evidence/ui-overview-smoke.png', fullPage: true });

  await page.goto('/#/memories');
  await expect(page.getByRole('heading', { name: 'Memory browser', exact: true })).toBeVisible();
  await page.screenshot({ path: '../../docs/qa/evidence/ui-memory-browser-smoke.png', fullPage: true });
});
