import { test, expect } from '@playwright/test';

test.describe('Users Stateful CRUD', () => {
  const testUsername = `e2e.user.${Date.now()}`;
  const testDisplayName = `E2E User ${Date.now()}`;
  let createdUserId: string | null = null;

  test.afterAll(async ({ request }) => {
    // Attempt API cleanup if we got an ID, using a dummy X-User-Name that has access
    // The frontend users endpoint allows DELETE. If it succeeds, great. 
    // If not, we rely on the UI deactivation below.
    if (createdUserId) {
      await request.delete(`/api/users/${createdUserId}`, {
        headers: {
          'X-User-Name': testUsername // As the user itself or admin
        }
      }).catch(() => {});
    }
  });

  test('Create, Edit, and Deactivate User', async ({ page, request }) => {
    await page.goto('/');
    
    // Pick an existing user if available to enable mutations
    const userSelect = page.locator('select').first();
    const optionsCount = await userSelect.locator('option').count();
    let bootstrapMode = false;
    if (optionsCount > 1) {
      await userSelect.selectOption({ index: 1 });
    } else {
      bootstrapMode = true;
    }

    await page.goto('/users');

    // 1. Create User
    await page.fill('input[placeholder="shared.operator"]', testUsername);
    await page.fill('input[placeholder="Shared Operator"]', testDisplayName);
    await page.click('button:has-text("Create User")');

    // The user should appear in the list
    const userRow = page.locator('tr', { hasText: testUsername }).first();
    await expect(userRow).toBeVisible({ timeout: 10000 });

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
