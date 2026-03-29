import type { Page } from '@playwright/test';

export const E2E_BEARER_TOKEN = process.env.PLAYWRIGHT_E2E_BEARER_TOKEN?.trim() ?? '';

export function authHeaders(): Record<string, string> {
  if (!E2E_BEARER_TOKEN) {
    throw new Error('Set PLAYWRIGHT_E2E_BEARER_TOKEN before running Playwright E2E tests.');
  }
  return { Authorization: `Bearer ${E2E_BEARER_TOKEN}` };
}

export async function installAccessToken(page: Page): Promise<void> {
  if (!E2E_BEARER_TOKEN) {
    throw new Error('Set PLAYWRIGHT_E2E_BEARER_TOKEN before running Playwright E2E tests.');
  }
  await page.addInitScript((token: string) => {
    window.localStorage.setItem('materials.access-token', token);
  }, E2E_BEARER_TOKEN);
}
