import { expect, test } from '@playwright/test';
import { E2E_BEARER_TOKEN, authHeaders, installAccessToken } from './auth';

test.describe('Auth and Reservation Flows', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!E2E_BEARER_TOKEN, 'Set PLAYWRIGHT_E2E_BEARER_TOKEN before running Playwright E2E tests.');
    await installAccessToken(page);
  });

  test('Users page shows a duplicate email conflict message', async ({ page, request }) => {
    const stamp = Date.now();
    const existingEmail = `playwright-duplicate-${stamp}@example.test`;

    const seedResponse = await request.post('/api/users', {
      headers: authHeaders(),
      data: {
        username: `playwright.seed.${stamp}`,
        display_name: `Playwright Seed ${stamp}`,
        email: existingEmail,
        external_subject: `sub-playwright-seed-${stamp}`,
        identity_provider: 'test-oidc',
        role: 'viewer',
        is_active: true,
      },
    });
    expect(seedResponse.ok()).toBeTruthy();

    await page.goto('/users');
    await page.getByPlaceholder('shared.operator').fill(`playwright.duplicate.${stamp}`);
    await page.getByPlaceholder('Shared Operator').fill(`Playwright Duplicate ${stamp}`);
    await page.getByPlaceholder('operator@example.com').fill(existingEmail);
    await page.getByRole('button', { name: 'Create User' }).click();

    await expect(page.getByText('Email is already mapped to another user')).toBeVisible();
  });

  test('Reservations consume flow can be undone from History', async ({ page, request }) => {
    const stamp = Date.now();
    const manufacturerResponse = await request.post('/api/manufacturers', {
      headers: authHeaders(),
      data: { name: `PW-RES-MFG-${stamp}` },
    });
    expect(manufacturerResponse.ok()).toBeTruthy();
    const manufacturer = await manufacturerResponse.json();

    const itemResponse = await request.post('/api/items', {
      headers: authHeaders(),
      data: {
        item_number: `PW-RES-ITEM-${stamp}`,
        manufacturer_id: manufacturer.data.manufacturer_id,
        category: 'Playwright',
      },
    });
    expect(itemResponse.ok()).toBeTruthy();
    const itemPayload = await itemResponse.json();
    const item = itemPayload.data;

    const adjustResponse = await request.post('/api/inventory/adjust', {
      headers: authHeaders(),
      data: {
        item_id: item.item_id,
        quantity_delta: 5,
        location: 'BENCH_A',
        note: 'playwright seed inventory',
      },
    });
    expect(adjustResponse.ok()).toBeTruthy();

    const reservationResponse = await request.post('/api/reservations', {
      headers: authHeaders(),
      data: {
        item_id: item.item_id,
        quantity: 4,
        purpose: 'playwright reservation',
      },
    });
    expect(reservationResponse.ok()).toBeTruthy();
    const reservationPayload = await reservationResponse.json();
    const reservationId = reservationPayload.data.reservation_id;

    await page.goto('/reserve');
    const reservationRow = page.locator('tr', { hasText: `PW-RES-ITEM-${stamp}` }).first();
    await expect(reservationRow).toBeVisible();
    page.once('dialog', (dialog) => dialog.accept('3'));
    await reservationRow.getByRole('button', { name: 'Consume' }).click();
    await expect(reservationRow).toContainText('ACTIVE');
    await expect(reservationRow).toContainText('1');

    await page.goto('/history');
    const consumeHistoryRow = page
      .locator('tr', { hasText: `PW-RES-ITEM-${stamp}` })
      .filter({ hasText: 'CONSUME' })
      .first();
    await expect(consumeHistoryRow).toBeVisible();
    await consumeHistoryRow.getByRole('button', { name: 'Undo' }).click();
    await expect
      .poll(async () => {
        const transactionsResponse = await request.get(`/api/transactions?item_id=${item.item_id}&page=1&per_page=20`, {
          headers: authHeaders(),
        });
        const transactionsPayload = await transactionsResponse.json();
        const consumeRow = transactionsPayload.data.find(
          (row: { batch_id: string | null }) =>
            String(row.batch_id).startsWith(`reservation-consume-${reservationId}-log-`),
        );
        return consumeRow?.is_undone ?? 0;
      })
      .toBe(1);

    const reservationsResponse = await request.get(`/api/reservations?item_id=${item.item_id}&per_page=50`, {
      headers: authHeaders(),
    });
    expect(reservationsResponse.ok()).toBeTruthy();
    const reservationsPayload = await reservationsResponse.json();
    const restoredReservation = reservationsPayload.data.find(
      (row: { reservation_id: number }) => row.reservation_id === reservationId,
    );
    expect(restoredReservation.status).toBe('ACTIVE');
    expect(restoredReservation.quantity).toBe(4);

    const inventoryResponse = await request.get(`/api/inventory?item_id=${item.item_id}&per_page=50`, {
      headers: authHeaders(),
    });
    expect(inventoryResponse.ok()).toBeTruthy();
    const inventoryPayload = await inventoryResponse.json();
    const benchRow = inventoryPayload.data.find((row: { location: string }) => row.location === 'BENCH_A');
    expect(benchRow.quantity).toBe(5);
    expect(inventoryPayload.data.some((row: { location: string }) => row.location === 'STOCK')).toBeFalsy();
  });
});
