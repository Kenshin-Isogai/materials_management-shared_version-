import { test, expect } from '@playwright/test';
import { E2E_BEARER_TOKEN, installAccessToken } from './auth';

test.describe('Layout and Users Flow', () => {
  test('App loads and bearer token input is available', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByText('Login')).toBeVisible();
    await expect(page.getByPlaceholder('Paste local fixture or OIDC bearer token')).toBeVisible();

    await expect(page.locator('text=Workspace').first()).toBeVisible();
    await expect(page.locator('text=Projects').first()).toBeVisible();
  });

  test('Navigate to Users page and view layout', async ({ page }) => {
    test.skip(!E2E_BEARER_TOKEN, 'Set PLAYWRIGHT_E2E_BEARER_TOKEN before running Playwright E2E tests.');
    await installAccessToken(page);
    await page.goto('/users');
    await expect(page.locator('h1', { hasText: 'Users' })).toBeVisible();
    await expect(page.locator('text=Active Users')).toBeVisible();
  });
});
