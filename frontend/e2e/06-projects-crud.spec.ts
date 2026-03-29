import { test, expect } from '@playwright/test';

test.describe('Projects Stateful CRUD', () => {
  const testProjectName = `E2E Test Project ${Date.now()}`;
  let selectedUsername = 'test_runner';

  test.afterAll(async ({ request }) => {
    try {
      const res = await request.get('/api/projects');
      if (res.ok()) {
        const data = await res.json();
        const projects = data.data || [];
        const testProject = projects.find((p: any) => p.name && p.name.includes(testProjectName));
        if (testProject) {
          await request.delete(`/api/projects/${testProject.project_id}`, {
            headers: { 'X-User-Name': selectedUsername }
          });
        }
      }
    } catch (e) {}
  });

  test('Create, Edit, and Manage Project', async ({ page }) => {
    await page.goto('/');
    const userSelect = page.locator('select').first();
    const optionsCount = await userSelect.locator('option').count();
    if (optionsCount > 1) {
      const userValue = await userSelect.locator('option').nth(1).getAttribute('value');
      if (userValue) selectedUsername = userValue;
      await userSelect.selectOption({ index: 1 });
    }

    await page.goto('/projects');

    // 1. Create Project
    const nameInput = page.locator('input').first();
    await expect(nameInput).toBeVisible({ timeout: 10000 });
    await nameInput.fill(testProjectName);
    
    // Submit creation
    await page.locator('button', { hasText: 'Create Project' }).first().click();

    // Verify creation
    const projectRow = page.locator('tr', { hasText: testProjectName }).first();
    await expect(projectRow).toBeVisible({ timeout: 10000 });
    
    // 2. Edit Project Details
    await projectRow.locator('button', { hasText: 'Edit' }).first().click();

    // Verify edit form loaded
    const saveBtn = page.locator('button', { hasText: 'Save Project' }).first();
    await expect(saveBtn).toBeVisible({ timeout: 5000 });

    // Update name
    await nameInput.fill(testProjectName + " Edited");
    await saveBtn.click();

    // Verify updated name
    await expect(page.locator('tr', { hasText: testProjectName + " Edited" }).first()).toBeVisible({ timeout: 10000 });
  });
});
