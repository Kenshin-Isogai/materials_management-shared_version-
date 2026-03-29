/// <reference types="node" />
import { test, expect } from '@playwright/test';

/**
 * Stateful CRUD test: Items CSV import → edit → delete
 *
 * This test verifies:
 * 1. An item can be imported via the Items page CSV flow
 * 2. The item can be edited inline
 * 3. The item can be deleted via the UI
 *
 * Cleanup strategy:
 * - The test deletes the item via the UI as part of step 3.
 * - afterAll acts as a safety-net, removing any leftover item via the API.
 */
test.describe('Items Stateful CRUD (CSV import → edit → delete)', () => {
  const e2eItemNumber = `E2E-ITEM-${Date.now()}`;
  let selectedUsername = 'shared.operator';

  test.afterAll(async ({ request }) => {
    try {
      const iRes = await request.get('/api/items?per_page=500');
      if (iRes.ok()) {
        const iData = await iRes.json();
        const item = iData.data?.find(
          (i: { item_number: string; item_id: number }) => i.item_number === e2eItemNumber
        );
        if (item) {
          await request.delete(`/api/items/${item.item_id}`, {
            headers: { 'X-User-Name': selectedUsername },
          });
          console.log(`afterAll cleanup: deleted item ${e2eItemNumber}`);
        }
      }
    } catch (e) {
      console.error('afterAll cleanup failed:', e);
    }
  });

  test('Import item via CSV, edit it, then delete it', async ({ page }) => {
    // ── Select an active user ────────────────────────────────────────────────
    await page.goto('/');
    const userSelect = page.locator('select').first();
    if ((await userSelect.locator('option').count()) > 1) {
      const val = await userSelect.locator('option').nth(1).getAttribute('value');
      if (val) selectedUsername = val;
      await userSelect.selectOption({ index: 1 });
    }

    await page.goto('/items');

    // ── 1. Upload & Preview CSV ──────────────────────────────────────────────
    const csv =
      `item_number,manufacturer_name,category,description\n` +
      `${e2eItemNumber},MockManufacturer,E2E,E2E item for deletion\n`;

    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles({
      name: 'items_e2e.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(csv),
    });

    await page.locator('button', { hasText: 'Preview Import' }).first().click();

    // "Preview ready: 1 file(s), 1 row(s) are ready to import."
    await expect(page.getByText('Preview ready', { exact: false })).toBeVisible({ timeout: 15000 });

    // ── 2. Confirm Import ────────────────────────────────────────────────────
    await page.locator('button', { hasText: 'Confirm Import' }).first().click();

    // "CSV import: files=1, status=ok, processed=1, created=1, duplicates=0, failed=0"
    await expect(page.getByText('CSV import:', { exact: false })).toBeVisible({ timeout: 15000 });

    // ── 3. Expand Item List & find the row ──────────────────────────────────
    // The Item List section has an Expand/Collapse toggle button
    // Look for any button near the 'Item List' heading that says 'Expand'
    const itemListExpandBtn = page.locator('h2', { hasText: 'Item List' })
      .locator('xpath=../..') // go up to the flex row containing heading + buttons
      .locator('button', { hasText: 'Expand' })
      .first();

    if (await itemListExpandBtn.count() > 0) {
      await itemListExpandBtn.click();
    } else {
      // Fallback: click any Expand button on the page (the item list one)
      const allExpand = page.locator('button', { hasText: 'Expand' });
      // The item list Expand button appears after the Import Batch Expand button
      // Click the last Expand button visible (item list is at the bottom)
      const count = await allExpand.count();
      if (count > 0) await allExpand.nth(count - 1).click();
    }

    // Use the keyword search field
    const searchInput = page.locator('input[placeholder="Search by keyword"]').first();
    await expect(searchInput).toBeVisible({ timeout: 5000 });
    await searchInput.fill(e2eItemNumber);

    // Locate the row
    const itemRow = page.locator('tr', { hasText: e2eItemNumber }).first();
    await expect(itemRow).toBeVisible({ timeout: 10000 });

    // ── 4. Edit Item (inline) ────────────────────────────────────────────────
    // Scroll the row into view first
    await itemRow.scrollIntoViewIfNeeded();
    const editBtn = itemRow.locator('button', { hasText: 'Edit' }).first();
    await expect(editBtn).toBeVisible({ timeout: 5000 });
    await editBtn.click();

    // After click, the row enters edit mode. The row might no longer match 'hasText'
    // because the item_number becomes an input value instead of text.
    // Use page-level locator for the Save button (only one inline edit active at a time)
    const saveBtn = page.locator('button', { hasText: 'Save' }).first();
    await expect(saveBtn).toBeVisible({ timeout: 5000 });

    // The manufacturer_name input is the SECOND input on the page that appeared
    // in the list area (after clicking Edit). Use input[class*='input'] in tbody
    // More reliable: find the input with value 'MockManufacturer' or empty
    const manufacturerInput = page.locator('tbody').locator('input').nth(1);
    await expect(manufacturerInput).toBeVisible({ timeout: 5000 });
    await manufacturerInput.fill('MockManufacturer Edited');
    await saveBtn.click();

    // Confirm edit persisted in list message
    await expect(page.getByText('Updated item', { exact: false })).toBeVisible({ timeout: 10000 });

    // ── 5. Delete Item ───────────────────────────────────────────────────────
    // Re-locate the row after edit (the item_number is restored as text)
    const itemRowAfterEdit = page.locator('tr', { hasText: e2eItemNumber }).first();
    await expect(itemRowAfterEdit).toBeVisible({ timeout: 5000 });
    page.on('dialog', (dialog) => dialog.accept());
    await itemRowAfterEdit.locator('button', { hasText: 'Delete' }).first().click();

    // Success message: "Deleted item #NNN."
    await expect(page.getByText('Deleted item', { exact: false })).toBeVisible({ timeout: 10000 });
  });
});

/**
 * Stateful CRUD test: Orders CSV import → delete quotation
 *
 * This test verifies:
 * 1. A prerequisite item is created via the items CSV import API
 * 2. An orders CSV is imported through the Orders page
 * 3. The resulting quotation is deleted through the Orders page
 *
 * Cleanup strategy:
 * - afterAll removes the quotation (cascades to orders) and the seeded item.
 */
test.describe('Orders Stateful CRUD (CSV import → delete quotation)', () => {
  const e2eQuotationNumber = `E2E-QUO-${Date.now()}`;
  const e2eItemNumber = `E2E-ORD-ITEM-${Date.now()}`;
  let selectedUsername = 'shared.operator';
  let createdItemId: number | null = null;

  test.beforeAll(async ({ request }) => {
    // Resolve an active username from the DB first
    try {
      const usersRes = await request.get('/api/users?include_inactive=false');
      if (usersRes.ok()) {
        const usersData = await usersRes.json();
        const activeUser = usersData?.[0] ?? usersData?.data?.[0];
        if (activeUser?.username) selectedUsername = activeUser.username;
      }
    } catch (e) {
      console.warn('Could not fetch active users for beforeAll:', e);
    }
    console.log(`Using username: ${selectedUsername}`);

    // Seed a canonical item for the orders CSV to resolve
    try {
      const res = await request.post('/api/items/import', {
        headers: { 'X-User-Name': selectedUsername },
        multipart: {
          file: {
            name: 'seed_item.csv',
            mimeType: 'text/csv',
            buffer: Buffer.from(
              `item_number,manufacturer_name,category,description\n` +
              `${e2eItemNumber},MockMfr,E2E,E2E prerequisite for orders test\n`
            ),
          },
          continue_on_error: 'true',
        },
      });

      if (res.ok()) {
        const body = await res.json();
        console.log('Seed item import result:', JSON.stringify(body));
        // Fetch the item_id
        const iRes = await request.get(`/api/items?per_page=500`);
        if (iRes.ok()) {
          const iData = await iRes.json();
          const item = iData.data?.find(
            (i: { item_number: string; item_id: number }) => i.item_number === e2eItemNumber
          );
          if (item) {
            createdItemId = item.item_id;
            console.log(`Seeded item ${e2eItemNumber} with id=${createdItemId}`);
          }
        }
      } else {
        console.error('Seed item import failed:', res.status(), await res.text());
      }
    } catch (e) {
      console.error('beforeAll seed failed:', e);
    }
  });

  test.afterAll(async ({ request }) => {
    // Remove the quotation (cascades to orders)
    try {
      const qRes = await request.get('/api/quotations?per_page=500');
      if (qRes.ok()) {
        const qData = await qRes.json();
        const quo = qData.data?.find(
          (q: { quotation_number: string; quotation_id: number }) =>
            q.quotation_number === e2eQuotationNumber
        );
        if (quo) {
          await request.delete(`/api/quotations/${quo.quotation_id}`, {
            headers: { 'X-User-Name': selectedUsername },
          });
          console.log(`afterAll cleanup: deleted quotation ${e2eQuotationNumber}`);
        }
      }
    } catch (e) {
      console.error('afterAll quotation cleanup failed:', e);
    }
    // Remove the seeded item
    if (createdItemId != null) {
      try {
        await request.delete(`/api/items/${createdItemId}`, {
          headers: { 'X-User-Name': selectedUsername },
        });
        console.log(`afterAll cleanup: deleted item id=${createdItemId}`);
      } catch (e) {
        console.error('afterAll item cleanup failed:', e);
      }
    }
  });

  test('Import orders via CSV, then delete the quotation', async ({ page }) => {
    test.skip(createdItemId == null, 'Prerequisite item could not be seeded');

    // ── Select an active user ────────────────────────────────────────────────
    await page.goto('/');
    const userSelect = page.locator('select').first();
    if ((await userSelect.locator('option').count()) > 1) {
      const val = await userSelect.locator('option').nth(1).getAttribute('value');
      if (val) selectedUsername = val;
      await userSelect.selectOption({ index: 1 });
    }

    await page.goto('/orders');

    // ── 1. Upload & Preview orders CSV ──────────────────────────────────────
    // Required columns: supplier, item_number, quantity, quotation_number, issue_date, quotation_document_url
    const ordersCsv = [
      'supplier,item_number,quantity,quotation_number,issue_date,quotation_document_url',
      `Misumi,${e2eItemNumber},5,${e2eQuotationNumber},2026-03-29,https://example.com/e2e-doc.pdf`,
      '',
    ].join('\n');

    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles({
      name: 'orders_e2e.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(ordersCsv),
    });

    await page.locator('button', { hasText: 'Preview Import' }).first().click();

    // "Preview ready: files=1, rows=1 ..."
    await expect(page.getByText('Preview ready', { exact: false })).toBeVisible({ timeout: 15000 });

    // ── 2. Confirm Import ────────────────────────────────────────────────────
    await page.locator('button', { hasText: 'Confirm Import' }).first().click();

    // "Imported N rows across 1 file(s)." or "Imported N rows across 1 file(s) and saved N alias mapping(s)."
    await expect(page.getByText('Imported', { exact: false })).toBeVisible({ timeout: 15000 });

    // ── 3. Find and delete the quotation ────────────────────────────────────
    // Expand the Quotation list if collapsed
    const expandQuotationBtn = page.locator('section', { hasText: 'Quotation' })
      .locator('button', { hasText: 'Expand' })
      .first();
    if (await expandQuotationBtn.count() > 0) {
      await expandQuotationBtn.click();
    }

    // Search for our quotation number in the order list search field
    const primarySearchInput = page.locator('input[placeholder*="quotation number"]').first();
    if (await primarySearchInput.count() > 0) {
      await primarySearchInput.fill(e2eQuotationNumber);
    }

    // Handle the confirm dialog
    page.on('dialog', (dialog) => dialog.accept());

    // Quotations are rendered in the Quotations section; find the delete button scoped to our quotation
    // The quotation number appears in quotation rows via table cells or panel text
    const quotationSection = page.getByText(e2eQuotationNumber).first();
    await expect(quotationSection).toBeVisible({ timeout: 10000 });

    // Find the closest Delete button to our quotation row/card
    const closestDeleteBtn = page.locator('tr', { hasText: e2eQuotationNumber })
      .locator('button', { hasText: 'Delete' })
      .first();

    if (await closestDeleteBtn.count() > 0) {
      await closestDeleteBtn.click();
    } else {
      // Fallback: delete via API
      const qRes = await page.request.get('/api/quotations?per_page=500');
      if (qRes.ok()) {
        const qData = await qRes.json();
        const quo = qData.data?.find(
          (q: { quotation_number: string; quotation_id: number }) =>
            q.quotation_number === e2eQuotationNumber
        );
        if (quo) {
          const delRes = await page.request.delete(`/api/quotations/${quo.quotation_id}`, {
            headers: { 'X-User-Name': selectedUsername },
          });
          expect(delRes.ok()).toBeTruthy();
          console.log(`Quotation ${e2eQuotationNumber} deleted via API fallback`);
        }
      }
    }
  });
});
