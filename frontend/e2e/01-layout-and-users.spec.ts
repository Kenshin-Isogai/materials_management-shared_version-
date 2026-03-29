import { test, expect } from '@playwright/test';

test.describe('Layout and Users Flow', () => {
  test('App loads and user selection is available', async ({ page }) => {
    // Navigate to root
    await page.goto('/');

    // Check app shell loads
    await expect(page.locator('select').first()).toBeVisible();

    // The user dropdown should be visible. We can identify it by its label 'User' or just the select element.
    const userSelect = page.locator('select');
    await expect(userSelect).toBeVisible();

    // Verify nav links
    await expect(page.locator('text=Workspace').first()).toBeVisible();
    await expect(page.locator('text=Projects').first()).toBeVisible();
  });

  test('Navigate to Users page and view layout', async ({ page }) => {
    await page.goto('/users');
    await expect(page.locator('h1', { hasText: 'Users' })).toBeVisible();
    await expect(page.locator('text=Active Users')).toBeVisible();
  });
});
