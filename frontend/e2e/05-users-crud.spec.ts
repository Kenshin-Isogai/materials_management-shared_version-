import { test, expect } from '@playwright/test';
import { E2E_BEARER_TOKEN, authHeaders, installAccessToken } from './auth';

test.describe('Users Stateful CRUD', () => {
  const testUsername = `e2e.user.${Date.now()}`;
  const testDisplayName = `E2E User ${Date.now()}`;
  let createdUserId: string | null = null;

  test.beforeEach(async ({ page }) => {
    test.skip(!E2E_BEARER_TOKEN, 'Set PLAYWRIGHT_E2E_BEARER_TOKEN before running Playwright E2E tests.');
    await installAccessToken(page);
  });

  test.afterAll(async ({ request }) => {
    if (!E2E_BEARER_TOKEN) {
      return;
    }
    if (createdUserId) {
      await request.delete(`/api/users/${createdUserId}`, {
        headers: authHeaders(),
      }).catch(() => {});
    }
  });

  test('Create, Edit, and Deactivate User', async ({ page, request }) => {
    await page.goto('/');

    await page.goto('/users');

    // 1. Create User
    await page.fill('input[placeholder="shared.operator"]', testUsername);
    await page.fill('input[placeholder="Shared Operator"]', testDisplayName);
    await page.click('button:has-text("Create User")');

    // The user should appear in the list
    const userRow = page.locator('tr', { hasText: testUsername }).first();
    await expect(userRow).toBeVisible({ timeout: 10000 });
    const usersResponse = await request.get('/api/users?include_inactive=true', { headers: authHeaders() });
    const usersPayload = await usersResponse.json();
    const createdUser = usersPayload.data?.find(
      (user: { user_id: number; username: string }) => user.username === testUsername
    );
    if (createdUser) {
      createdUserId = String(createdUser.user_id);
    }

    // Look for ID in DOM or just proceed
    // We can extract user ID if needed, but let's just use the UI to Edit
    
    // 2. Edit User
    await userRow.locator('button:has-text("Edit")').click();
    
    // Changing display name
    const editNameInput = userRow.locator('input').first(); // The first input in the row is display name
    await expect(editNameInput).toBeVisible();
    await editNameInput.fill(`${testDisplayName} Edited`);
    
    await userRow.locator('button:has-text("Save")').click();
    await expect(userRow.locator(`text=${testDisplayName} Edited`)).toBeVisible();

    // 3. Deactivate User (Cleanup via UI)
    await userRow.locator('button:has-text("Deactivate")').click();
    
    // Wait for the status indicator to change to Inactive
    await expect(userRow.locator('span', { hasText: 'Inactive' }).first()).toBeVisible();
  });
});
