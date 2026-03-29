import { test, expect } from '@playwright/test';

test.describe('Orders Flow', () => {
  test('Orders Page loads and lists are functional', async ({ page }) => {
    await page.goto('/orders');

    // Orders title
    await expect(page.locator('h1', { hasText: 'Orders' })).toBeVisible();

    // Check expand buttons
    const expandButtons = page.locator('button', { hasText: 'Expand' });
    if (await expandButtons.count() > 0) {
      await expandButtons.first().click();
      await expect(page.locator('button', { hasText: 'Collapse' }).first()).toBeVisible();
    }
  });

  test('Shows validation error on invalid CSV upload', async ({ page }) => {
    await page.goto('/orders');

    const fileInput = page.locator('input[type="file"]').first();
    // Provide a dummy file without required headers
    await fileInput.setInputFiles({
      name: 'dummy.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('invalid,header\ndata,row\n'),
    });

    const submit = page.locator('button', { hasText: 'Preview Import' }).first();
    await submit.click();

    // The validation error should appear (e.g. missing 'supplier' column or 400 error)
    await expect(page.locator('text=failed').or(page.locator('text=error')).or(page.locator('text=required')).first()).toBeVisible();
  });
});
