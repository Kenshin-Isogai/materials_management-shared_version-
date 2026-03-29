import { test, expect } from '@playwright/test';

test.describe('Projects Stateful CRUD', () => {
  const testProjectName = `E2E Test Project ${Date.now()}`;
  const editedProjectName = `${testProjectName} Edited`;
  let currentProjectName = testProjectName;
  let selectedUsername = 'e2e.admin';

  test.afterAll(async ({ request }) => {
    const res = await request.get('/api/projects');
    expect(res.ok()).toBeTruthy();

    const data = await res.json();
    const projects = Array.isArray(data?.data)
      ? (data.data as Array<{ project_id: number; name?: string | null }>)
      : [];
    const candidateNames = new Set([testProjectName, editedProjectName, currentProjectName]);
    const testProject = projects.find(
      (project) => typeof project.name === 'string' && candidateNames.has(project.name)
    );
    if (!testProject) {
      return;
    }

    const deleteResponse = await request.delete(`/api/projects/${testProject.project_id}`, {
      headers: { 'X-User-Name': selectedUsername }
    });
    expect(deleteResponse.ok()).toBeTruthy();
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
    await nameInput.fill(editedProjectName);
    await saveBtn.click();
    currentProjectName = editedProjectName;

    // Verify updated name
    await expect(page.locator('tr', { hasText: editedProjectName }).first()).toBeVisible({ timeout: 10000 });
  });
});
