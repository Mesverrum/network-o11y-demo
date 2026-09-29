import { test, expect } from './fixtures';

// Writes a real Fleet pipeline. Run only against the hub test Grafana (HUB_E2E_FLEET=1).
test.describe('fleet scenario', () => {
  test.skip(!process.env.HUB_E2E_FLEET, 'set HUB_E2E_FLEET=1 to write to Fleet');

  test('apply lands on the collector and data arrives', async ({ gotoPage, page }) => {
    test.setTimeout(10 * 60 * 1000);

    await gotoPage('/apply');
    await page.getByRole('button', { name: 'Apply to Fleet' }).click();
    await expect(page.getByText('Fleet accepted', { exact: false }).first()).toBeVisible({ timeout: 30000 });

    await page.getByRole('button', { name: "See what's arriving" }).click();
    await expect(page.getByText('Live from the stack')).toBeVisible();

    for (const label of ['Collector took the config', 'Pipeline components healthy', 'Discovery found devices']) {
      await expect(page.getByRole('row', { name: new RegExp(label) })).toContainText('Receiving', {
        timeout: 5 * 60 * 1000,
      });
    }
    await expect(page.getByRole('row', { name: /Health and traffic/ })).toContainText('Receiving', {
      timeout: 5 * 60 * 1000,
    });
    await expect(page.getByRole('row', { name: /Alarms/ })).toContainText(/Listening on UDP 11621|Receiving/);
    await expect(page.getByRole('row', { name: /Device logs/ })).toContainText(/Listening on UDP 1516|Receiving/);

    await gotoPage('/found');
    const ignore = page.getByRole('button', { name: 'Ignore' }).first();
    await expect(ignore).toBeVisible({ timeout: 60000 });
    await ignore.click();
    await expect(page.getByRole('heading', { name: 'Ignored' })).toBeVisible();
    await expect(page.getByText('Fleet has the ignore')).toBeVisible({ timeout: 30000 });
    await page.getByRole('button', { name: 'Restore' }).click();
    await expect(page.getByText('is back in the scan')).toBeVisible({ timeout: 30000 });
  });
});
