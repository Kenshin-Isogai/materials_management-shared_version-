import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

const apiDownloadMock = vi.fn();
const apiGetAllPagesMock = vi.fn();
const apiGetWithPaginationMock = vi.fn();
const apiSendMock = vi.fn();
const apiSendFormMock = vi.fn();

vi.mock("../src/lib/api", () => ({
  apiDownload: (...args: unknown[]) => apiDownloadMock(...args),
  apiGetAllPages: (...args: unknown[]) => apiGetAllPagesMock(...args),
  apiGetWithPagination: (...args: unknown[]) => apiGetWithPaginationMock(...args),
  apiSend: (...args: unknown[]) => apiSendMock(...args),
  apiSendForm: (...args: unknown[]) => apiSendFormMock(...args),
}));

vi.mock("../src/components/CatalogPicker", () => ({
  CatalogPicker: () => <div>Catalog Picker</div>,
}));

import { OrdersPage } from "../src/pages/OrdersPage";

function renderPage() {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MemoryRouter>
        <OrdersPage />
      </MemoryRouter>
    </SWRConfig>,
  );
}

describe("OrdersPage", () => {
  beforeEach(() => {
    apiDownloadMock.mockReset();
    apiGetAllPagesMock.mockReset();
    apiGetWithPaginationMock.mockReset();
    apiSendMock.mockReset();
    apiSendFormMock.mockReset();

    apiGetAllPagesMock.mockImplementation(async (path: string) => {
      if (path === "/orders?per_page=200") {
        return [
          {
            order_id: 304,
            item_id: 1,
            quotation_id: 12,
            project_id: null,
            project_name: null,
            canonical_item_number: "AOMO3080-125",
            order_amount: 15,
            ordered_quantity: 15,
            ordered_item_number: "AOMO3080-125",
            order_date: "2025-10-21",
            expected_arrival: "2025-11-30",
            arrival_date: null,
            status: "Ordered",
            supplier_name: "オーテックス",
            quotation_number: "0000001809",
          },
        ];
      }
      if (path === "/quotations?per_page=200") {
        return [
          {
            quotation_id: 12,
            supplier_id: 3,
            supplier_name: "オーテックス",
            quotation_number: "0000001809",
            issue_date: "2025-10-20",
            pdf_link: "imports/orders/registered/pdf_files/オーテックス/0000001809.pdf",
          },
        ];
      }
      throw new Error(`Unexpected apiGetAllPages path: ${path}`);
    });
    apiGetWithPaginationMock.mockImplementation(async (path: string) => {
      if (path === "/items?per_page=500") {
        return {
          data: [
            {
              item_id: 1,
              item_number: "AOMO3080-125",
              manufacturer_id: 7,
              manufacturer_name: "AUTEX",
              category: "Optics",
              description: "Autex test optic",
            },
          ],
          pagination: undefined,
        };
      }
      throw new Error(`Unexpected apiGetWithPagination path: ${path}`);
    });

    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 0;
    });
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows quotation order counts using all fetched order pages", async () => {
    renderPage();

    await waitFor(() => {
      expect(apiGetAllPagesMock).toHaveBeenCalledWith("/orders?per_page=200");
      expect(apiGetAllPagesMock).toHaveBeenCalledWith("/quotations?per_page=200");
    });

    const quotationRow = await screen.findByText("0000001809");
    const tableRow = quotationRow.closest("tr");
    expect(tableRow).toBeTruthy();
    expect(within(tableRow as HTMLElement).getByText("1")).toBeTruthy();
  });

  it("opens order context from quotation details when the linked order is older", async () => {
    const user = userEvent.setup();
    renderPage();

    const quotationCell = await screen.findByText("0000001809");
    const tableRow = quotationCell.closest("tr");
    expect(tableRow).toBeTruthy();

    await user.click(within(tableRow as HTMLElement).getByRole("button", { name: "Details" }));

    const orderContextSection = screen.getByRole("heading", { name: "Order Context" }).closest("section");
    expect(orderContextSection).toBeTruthy();

    await waitFor(() => {
      expect(within(orderContextSection as HTMLElement).getByRole("button", { name: "Clear" })).toBeTruthy();
      expect(within(orderContextSection as HTMLElement).getByText("AOMO3080-125")).toBeTruthy();
      expect(within(orderContextSection as HTMLElement).getByText("Autex test optic", { exact: false })).toBeTruthy();
    });
    expect(screen.queryByText("No linked orders found for quotation #12.")).toBeNull();
  });
});
