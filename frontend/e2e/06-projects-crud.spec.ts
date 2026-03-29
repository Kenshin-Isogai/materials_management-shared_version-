import { test, expect } from '@playwright/test';
import { E2E_BEARER_TOKEN, authHeaders, installAccessToken } from './auth';

test.describe('Projects Stateful CRUD', () => {
  const testProjectName = `E2E Test Project ${Date.now()}`;
  const editedProjectName = `${testProjectName} Edited`;
  let currentProjectName = testProjectName;

  test.beforeEach(async ({ page }) => {
    test.skip(!E2E_BEARER_TOKEN, 'Set PLAYWRIGHT_E2E_BEARER_TOKEN before running Playwright E2E tests.');
    await installAccessToken(page);
  });

  test.afterAll(async ({ request }) => {
    if (!E2E_BEARER_TOKEN) {
      return;
    }
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
      headers: authHeaders()
    });
    expect(deleteResponse.ok()).toBeTruthy();
  });

  test('Create, Edit, and Manage Project', async ({ page }) => {
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
