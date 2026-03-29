import { test, expect } from '@playwright/test';
import { E2E_BEARER_TOKEN, installAccessToken } from './auth';

test.describe('Projects Flow', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!E2E_BEARER_TOKEN, 'Set PLAYWRIGHT_E2E_BEARER_TOKEN before running Playwright E2E tests.');
    await installAccessToken(page);
  });

  test('Project List loads and can open Project Creation Form', async ({ page }) => {
    await page.goto('/projects');

    // Should be on Projects tab
    await expect(page.locator('h1', { hasText: 'Projects' })).toBeVisible();

    // Click Create button 
    const createButton = page.locator('button', { hasText: 'Create Project' });
    if (await createButton.count() > 0) {
      await createButton.click();
      // Wait for side panel or modal
      const anyInput = page.locator('input').first(); // wait for any input
      await expect(anyInput).toBeVisible();

      // Enter a casual Title
      const nameInput = page.getByLabel('Project Name').or(page.locator('input[name="projectName"]')).or(page.locator('input[placeholder*="Name"]')).first();
      if (await nameInput.count() > 0) {
        await nameInput.fill('Playwright Test Project');
      }

      // We won't submit to keep the DB clean, just verifying the UI form reacts
      const cancelButton = page.locator('button', { hasText: 'Cancel' }).or(page.locator('button', { hasText: 'Close' }));
      if (await cancelButton.count() > 0) {
        await cancelButton.click();
      }
    }
  });

  test('Workspace view loads pipeline and summary panels', async ({ page }) => {
    await page.goto('/workspace');

    // Looking for the workspace summary board
    await expect(page.locator('h1', { hasText: 'Workspace' })).toBeVisible();
    await expect(page.locator('text=Summary').first()).toBeVisible();

    // We can click elements like pipeline commits if they exist
    await expect(page.locator('table').or(page.locator('.panel'))).toBeVisible();
  });
});
