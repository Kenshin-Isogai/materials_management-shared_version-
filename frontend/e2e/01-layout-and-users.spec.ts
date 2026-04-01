import { test, expect } from '@playwright/test';
import { E2E_BEARER_TOKEN, installAccessToken } from './auth';

test.describe('Layout and Users Flow', () => {
  test('App redirects to /login and shows the login page', async ({ page }) => {
    await page.goto('/');

    /* Should redirect to /login */
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByText('Welcome back')).toBeVisible();
    await expect(page.getByPlaceholder('Paste local fixture or OIDC bearer token')).toBeVisible();
  });

  test('Navigate to Users page and view layout', async ({ page }) => {
    test.skip(!E2E_BEARER_TOKEN, 'Set PLAYWRIGHT_E2E_BEARER_TOKEN before running Playwright E2E tests.');
    await installAccessToken(page);
    await page.goto('/users');
    await expect(page.locator('h1', { hasText: 'Users' })).toBeVisible();
    await expect(page.locator('text=Active Users')).toBeVisible();
  });
});
