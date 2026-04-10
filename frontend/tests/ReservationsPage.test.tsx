import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiDownloadMock = vi.fn();
const apiGetAllPagesMock = vi.fn();
const apiGetWithPaginationMock = vi.fn();
const apiSendMock = vi.fn();
const apiSendFormMock = vi.fn();

vi.mock("../src/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/lib/api")>();
  return {
    ...actual,
    apiDownload: (...args: unknown[]) => apiDownloadMock(...args),
    apiGetAllPages: (...args: unknown[]) => apiGetAllPagesMock(...args),
    apiGetWithPagination: (...args: unknown[]) => apiGetWithPaginationMock(...args),
    apiSend: (...args: unknown[]) => apiSendMock(...args),
    apiSendForm: (...args: unknown[]) => apiSendFormMock(...args),
  };
});

vi.mock("../src/components/CatalogPicker", () => ({
  CatalogPicker: ({ placeholder }: { placeholder?: string }) => (
    <input aria-label={placeholder ?? "Catalog Picker"} className="input" />
  ),
}));

import { ReservationsPage } from "../src/features/inventory/ReservationsPage";
import { ApiClientError } from "../src/lib/types";

function renderPage(initialEntries: string[] = ["/reservations"]) {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MemoryRouter initialEntries={initialEntries}>
        <ReservationsPage />
      </MemoryRouter>
    </SWRConfig>,
  );
}

describe("ReservationsPage", () => {
  beforeEach(() => {
    apiDownloadMock.mockReset();
    apiGetAllPagesMock.mockReset();
    apiGetWithPaginationMock.mockReset();
    apiSendMock.mockReset();
    apiSendFormMock.mockReset();

    apiGetWithPaginationMock.mockImplementation(async (path: string) => {
      if (path === "/reservations?per_page=200") {
        return { data: [], pagination: undefined };
      }
      if (path === "/items?per_page=1000") {
        return {
          data: [
            {
              item_id: 1,
              item_number: "ITEM-001",
              manufacturer_id: 10,
              manufacturer_name: "Maker",
              category: "Optics",
              description: "Test item",
            },
          ],
          pagination: undefined,
        };
      }
      throw new Error(`Unexpected apiGetWithPagination path: ${path}`);
    });

    apiGetAllPagesMock.mockImplementation(async (path: string) => {
      if (path === "/projects?per_page=200") {
        return [
          {
            project_id: 3,
            name: "Project Alpha",
            status: "ACTIVE",
            planned_start: "2026-04-10",
            requirement_count: 0,
          },
        ];
      }
      if (
        path === "/purchase-order-lines?include_arrived=false&per_page=200" ||
        path === "/reservations?per_page=200"
      ) {
        if (path === "/purchase-order-lines?include_arrived=false&per_page=200") {
          return [
            {
              order_id: 11,
              purchase_order_id: 101,
              purchase_order_number: "PO-GENERIC",
              item_id: 1,
              quotation_id: 201,
              project_id: null,
              canonical_item_number: "ITEM-001",
              order_amount: 4,
              ordered_quantity: 4,
              ordered_item_number: "ITEM-001",
              order_date: "2026-04-01",
              expected_arrival: "2026-04-15",
              arrival_date: null,
              status: "Ordered",
              supplier_name: "Supplier Generic",
              quotation_number: "Q-GENERIC",
            },
            {
              order_id: 12,
              purchase_order_id: 102,
              purchase_order_number: "PO-ALPHA",
              item_id: 1,
              quotation_id: 202,
              project_id: 3,
              project_name: "Project Alpha",
              canonical_item_number: "ITEM-001",
              order_amount: 5,
              ordered_quantity: 5,
              ordered_item_number: "ITEM-001",
              order_date: "2026-04-02",
              expected_arrival: "2026-04-16",
              arrival_date: null,
              status: "Ordered",
              supplier_name: "Supplier Alpha",
              quotation_number: "Q-ALPHA",
            },
            {
              order_id: 13,
              purchase_order_id: 103,
              purchase_order_number: "PO-BETA",
              item_id: 1,
              quotation_id: 203,
              project_id: 9,
              project_name: "Project Beta",
              canonical_item_number: "ITEM-001",
              order_amount: 6,
              ordered_quantity: 6,
              ordered_item_number: "ITEM-001",
              order_date: "2026-04-03",
              expected_arrival: "2026-04-17",
              arrival_date: null,
              status: "Ordered",
              supplier_name: "Supplier Beta",
              quotation_number: "Q-BETA",
            },
          ];
        }
        return [];
      }
      throw new Error(`Unexpected apiGetAllPages path: ${path}`);
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("shows a success message after batch creation", async () => {
    const user = userEvent.setup();
    apiSendMock.mockResolvedValue([]);

    renderPage(["/reservations?item_id=1&quantity=2&project_id=3"]);

    await user.click(await screen.findByRole("button", { name: "Submit Batch" }));

    await waitFor(() => {
      expect(apiSendMock).toHaveBeenCalledWith("/reservations/batch", {
        method: "POST",
        body: JSON.stringify({
          reservations: [
            {
              item_id: 1,
              quantity: 2,
              purpose: null,
              deadline: null,
              note: null,
              project_id: 3,
              preferred_order_id: null,
            },
          ],
        }),
      });
    });

    expect(await screen.findByText("Created 1 reservation row(s).")).toBeTruthy();
  });

  it("shows the backend error when batch creation fails", async () => {
    const user = userEvent.setup();
    apiSendMock.mockRejectedValue(
      new ApiClientError({
        message: "Not enough available inventory for reservation",
        statusCode: 409,
        code: "INSUFFICIENT_STOCK",
      }),
    );

    renderPage(["/reservations?item_id=1&quantity=2&project_id=3"]);

    await user.click(await screen.findByRole("button", { name: "Submit Batch" }));

    expect(
      await screen.findByText("Submit batch failed: Not enough available inventory for reservation"),
    ).toBeTruthy();
  });

  it("hides preferred incoming orders that do not match the reservation project scope", async () => {
    const user = userEvent.setup();

    renderPage(["/reservations?item_id=1&quantity=2"]);

    const preferredOrderSelect = (await screen.findAllByRole("combobox"))[1];
    await user.selectOptions(preferredOrderSelect, "11");

    expect(screen.getByRole("option", { name: /PO-GENERIC/i })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /PO-ALPHA/i })).toBeNull();
    expect(screen.queryByRole("option", { name: /PO-BETA/i })).toBeNull();

    const projectSelect = (await screen.findAllByRole("combobox"))[0];
    await user.selectOptions(projectSelect, "3");

    expect(screen.getByRole("option", { name: /PO-GENERIC/i })).toBeTruthy();
    expect(screen.getByRole("option", { name: /PO-ALPHA/i })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /PO-BETA/i })).toBeNull();
  });
});
