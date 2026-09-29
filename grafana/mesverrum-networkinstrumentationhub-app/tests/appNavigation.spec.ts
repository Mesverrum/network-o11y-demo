import { test, expect } from './fixtures';

test.describe('navigating app', () => {
  test('collector step should render', async ({ gotoPage, page }) => {
    await gotoPage('/collector');
    await expect(page.getByText('Pick the Network Alloy that can reach this segment.')).toBeVisible();
  });

  test('apply step should say it is a dry run', async ({ gotoPage, page }) => {
    await gotoPage('/apply');
    await expect(page.getByText('Nothing is written yet.')).toBeVisible();
  });
});
