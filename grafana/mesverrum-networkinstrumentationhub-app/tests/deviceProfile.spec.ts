import { test, expect } from '@playwright/test';

// Writes the hub-canary pipeline. Do not run this in parallel with tests/fleetScenario.spec.ts.
test.skip(!process.env.HUB_E2E_FLEET, 'set HUB_E2E_FLEET=1 to write to Fleet');

test('profile picker fills modules and a name override round-trips', async ({ page }) => {
  test.setTimeout(120000);
  await page.goto('/a/mesverrum-networkdevices-app');
  const row = page.getByRole('row', { name: /hub-canary/ }).first();
  await expect(row).toBeVisible({ timeout: 60000 });
  await row.getByRole('button', { name: 'Edit' }).click();
  await expect(page.getByRole('heading', { name: 'Device', exact: true })).toBeVisible();
  await expect(page.getByText(/Profile list from this collector/)).toBeVisible({
    timeout: 30000,
  });

  await page.locator('#device-profile').fill('barracuda_email_gateway');
  await page.getByRole('option', { name: 'barracuda_email_gateway', exact: true }).click();
  // Module lists come from the collector image; do not assert a fixed lab snapshot.
  await expect(page.locator('#module-hot')).toHaveValue(/if_mib/);
  await expect(page.locator('#module-hot')).not.toHaveValue('');

  await page.getByRole('button', { name: 'Use the fingerprint' }).click();
  await expect(page.locator('#module-hot')).toHaveValue('');

  await page.locator('#device-name').fill('e2e-pin');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Fleet has the override')).toBeVisible({ timeout: 30000 });

  await page.getByRole('button', { name: 'Clear override' }).click();
  await expect(page.getByText('using the fingerprint')).toBeVisible({ timeout: 30000 });
  await expect(page.locator('#device-name')).toHaveValue('');
});
