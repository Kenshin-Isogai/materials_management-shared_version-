import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

const apiDownloadMock = vi.fn();
const apiGetMock = vi.fn();
const apiGetAllPagesMock = vi.fn();
const apiGetWithPaginationMock = vi.fn();
const apiSendMock = vi.fn();
const apiSendFormMock = vi.fn();

vi.mock("../src/lib/api", () => ({
  apiDownload: (...args: unknown[]) => apiDownloadMock(...args),
  apiGet: (...args: unknown[]) => apiGetMock(...args),
  apiGetAllPages: (...args: unknown[]) => apiGetAllPagesMock(...args),
  apiGetWithPagination: (...args: unknown[]) => apiGetWithPaginationMock(...args),
  apiSend: (...args: unknown[]) => apiSendMock(...args),
  apiSendForm: (...args: unknown[]) => apiSendFormMock(...args),
}));

vi.mock("../src/components/CatalogPicker", () => ({
  CatalogPicker: ({
    onQueryChange,
    placeholder,
  }: {
    onQueryChange?: (value: string) => void;
    placeholder?: string;
  }) => (
    <input
      aria-label={placeholder ?? "Catalog Picker"}
      className="input"
      placeholder={placeholder ?? "Catalog Picker"}
      onChange={(event) => onQueryChange?.(event.target.value)}
    />
  ),
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

function sectionByHeading(name: string) {
  return screen.getByRole("heading", { name }).closest("section");
}

describe("OrdersPage", () => {
  beforeEach(() => {
    apiDownloadMock.mockReset();
    apiGetMock.mockReset();
    apiGetAllPagesMock.mockReset();
    apiGetWithPaginationMock.mockReset();
    apiSendMock.mockReset();
    apiSendFormMock.mockReset();

    apiGetMock.mockResolvedValue([]);

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
          {
            order_id: 305,
            item_id: 2,
            quotation_id: 12,
            project_id: 9,
            project_name: "Project Lens",
            canonical_item_number: "BETA-200",
            order_amount: 8,
            ordered_quantity: 8,
            ordered_item_number: "BETA-200",
            order_date: "2025-10-21",
            expected_arrival: "2025-12-10",
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
            quotation_document_url: "https://example.sharepoint.com/sites/procurement/0000001809",
          },
        ];
      }
      if (path === "/projects?per_page=200") {
        return [
          {
            project_id: 9,
            name: "Project Lens",
            status: "CONFIRMED",
            planned_start: "2025-12-01",
          },
          {
            project_id: 12,
            name: "Project Prism",
            status: "CONFIRMED",
            planned_start: "2025-12-20",
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
            {
              item_id: 2,
              item_number: "BETA-200",
              manufacturer_id: 8,
              manufacturer_name: "BETACO",
              category: "Mechanics",
              description: "Beta support part",
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
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(apiGetAllPagesMock).toHaveBeenCalledWith("/orders?per_page=200");
      expect(apiGetAllPagesMock).toHaveBeenCalledWith("/quotations?per_page=200");
    });

    const quotationsSection = sectionByHeading("Imported Quotations");
    expect(quotationsSection).toBeTruthy();
    await user.click(within(quotationsSection as HTMLElement).getByRole("button", { name: "Expand" }));

    const quotationRow = await screen.findByText("0000001809");
    const tableRow = quotationRow.closest("tr");
    expect(tableRow).toBeTruthy();
    expect(within(tableRow as HTMLElement).getByText("2")).toBeTruthy();
  });

  it("opens quotation details with every linked order", async () => {
    const user = userEvent.setup();
    renderPage();

    const quotationsSection = sectionByHeading("Imported Quotations");
    expect(quotationsSection).toBeTruthy();
    await user.click(within(quotationsSection as HTMLElement).getByRole("button", { name: "Expand" }));

    const quotationCell = await screen.findByText("0000001809");
    const tableRow = quotationCell.closest("tr");
    expect(tableRow).toBeTruthy();

    await user.click(within(tableRow as HTMLElement).getByRole("button", { name: "View Orders" }));

    const quotationDetailsSection = screen.getByRole("heading", { name: "Quotation Details" }).closest("section");
    expect(quotationDetailsSection).toBeTruthy();

    await waitFor(() => {
      expect(within(quotationDetailsSection as HTMLElement).getByRole("button", { name: "Clear" })).toBeTruthy();
      expect(within(quotationDetailsSection as HTMLElement).getByText("Linked orders:", { exact: false })).toBeTruthy();
      expect(within(quotationDetailsSection as HTMLElement).getByText("#304")).toBeTruthy();
      expect(within(quotationDetailsSection as HTMLElement).getByText("#305")).toBeTruthy();
      expect(within(quotationDetailsSection as HTMLElement).getByText("AOMO3080-125")).toBeTruthy();
      expect(within(quotationDetailsSection as HTMLElement).getByText("BETA-200")).toBeTruthy();
    });
  });

  it("keeps order details separate from quotation details", async () => {
    const user = userEvent.setup();
    renderPage();

    const orderListSection = sectionByHeading("Order List");
    expect(orderListSection).toBeTruthy();
    await user.click(within(orderListSection as HTMLElement).getByRole("button", { name: "Expand" }));

    const orderRow = (await screen.findByText("BETA-200")).closest("tr");
    expect(orderRow).toBeTruthy();

    await user.click(within(orderRow as HTMLElement).getByRole("button", { name: "Order Details" }));

    const orderDetailsSection = screen.getByRole("heading", { name: "Order Details" }).closest("section");
    const quotationDetailsSection = screen.getByRole("heading", { name: "Quotation Details" }).closest("section");
    expect(orderDetailsSection).toBeTruthy();
    expect(quotationDetailsSection).toBeTruthy();

    await waitFor(() => {
      expect(within(orderDetailsSection as HTMLElement).getByText("Beta support part", { exact: false })).toBeTruthy();
    });
    expect((orderDetailsSection as HTMLElement).textContent).toContain("#305");
    expect((quotationDetailsSection as HTMLElement).textContent).toContain("Select");
  });

  it("filters the expanded order list with search inputs", async () => {
    const user = userEvent.setup();
    renderPage();

    const orderListSection = sectionByHeading("Order List");
    expect(orderListSection).toBeTruthy();
    await user.click(within(orderListSection as HTMLElement).getByRole("button", { name: "Expand" }));

    await user.type(screen.getByPlaceholderText("Search by order #, item, or quotation number"), "BETA");

    await waitFor(() => {
      expect(within(orderListSection as HTMLElement).getByText("Showing 1 / 2 orders")).toBeTruthy();
      expect(within(orderListSection as HTMLElement).getByText("BETA-200")).toBeTruthy();
    });
    expect(within(orderListSection as HTMLElement).queryByText("AOMO3080-125")).toBeNull();
  });

  it("supports collapsing imported quotations", async () => {
    const user = userEvent.setup();
    renderPage();

    const quotationsSection = sectionByHeading("Imported Quotations");
    expect(quotationsSection).toBeTruthy();

    expect(within(quotationsSection as HTMLElement).queryByPlaceholderText("Search by quotation number")).toBeNull();

    await user.click(within(quotationsSection as HTMLElement).getByRole("button", { name: "Expand" }));
    expect(within(quotationsSection as HTMLElement).getByPlaceholderText("Search by quotation number")).toBeTruthy();

    await user.click(within(quotationsSection as HTMLElement).getByRole("button", { name: "Collapse" }));
    expect(within(quotationsSection as HTMLElement).queryByPlaceholderText("Search by quotation number")).toBeNull();
  });

  it("splits first and assigns only the created child order when a project is selected", async () => {
    const user = userEvent.setup();
    apiSendMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/orders/304") {
        expect(init?.method).toBe("PUT");
        expect(init?.body).toBe(
          JSON.stringify({
            expected_arrival: "2025-12-15",
            split_quantity: 5,
          }),
        );
        return {
          order_id: 304,
          split_order_id: 401,
          updated_order: {
            order_id: 304,
            item_id: 1,
            quotation_id: 12,
            project_id: null,
            project_name: null,
            canonical_item_number: "AOMO3080-125",
            order_amount: 10,
            ordered_quantity: 10,
            ordered_item_number: "AOMO3080-125",
            order_date: "2025-10-21",
            expected_arrival: "2025-11-30",
            arrival_date: null,
            status: "Ordered",
            supplier_name: "オーテックス",
            quotation_number: "0000001809",
          },
          created_order: {
            order_id: 401,
            item_id: 1,
            quotation_id: 12,
            project_id: null,
            project_name: null,
            canonical_item_number: "AOMO3080-125",
            order_amount: 5,
            ordered_quantity: 5,
            ordered_item_number: "AOMO3080-125",
            order_date: "2025-10-21",
            expected_arrival: "2025-12-15",
            arrival_date: null,
            status: "Ordered",
            supplier_name: "オーテックス",
            quotation_number: "0000001809",
          },
        };
      }
      if (path === "/orders/401") {
        expect(init?.method).toBe("PUT");
        expect(init?.body).toBe(JSON.stringify({ project_id: 12 }));
        return {};
      }
      throw new Error(`Unexpected apiSend path: ${path}`);
    });

    renderPage();

    const orderListSection = sectionByHeading("Order List");
    expect(orderListSection).toBeTruthy();
    await user.click(within(orderListSection as HTMLElement).getByRole("button", { name: "Expand" }));

    const orderRow = (await screen.findByText("AOMO3080-125")).closest("tr");
    expect(orderRow).toBeTruthy();
    await user.click(within(orderRow as HTMLElement).getByRole("button", { name: "Edit Order" }));

    const inputs = within(orderRow as HTMLElement);
    const dateInput = (orderRow as HTMLElement).querySelector('input[type="date"]') as HTMLInputElement | null;
    expect(dateInput).toBeTruthy();
    fireEvent.change(dateInput as HTMLInputElement, { target: { value: "2025-12-15" } });
    await user.type(inputs.getByPlaceholderText("Split qty (1-14)"), "5");
    await user.selectOptions(inputs.getByRole("combobox"), "12");
    await user.click(inputs.getByRole("button", { name: "Save Order" }));

    await waitFor(() => {
      expect(apiSendMock).toHaveBeenCalledTimes(2);
    });
    expect(apiSendMock).toHaveBeenNthCalledWith(
      1,
      "/orders/304",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          expected_arrival: "2025-12-15",
          split_quantity: 5,
        }),
      }),
    );
    expect(apiSendMock).toHaveBeenNthCalledWith(
      2,
      "/orders/401",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ project_id: 12 }),
      }),
    );
  });

  it("preserves explicit project clearing when splitting an assigned order", async () => {
    const user = userEvent.setup();
    apiSendMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/orders/305") {
        expect(init?.method).toBe("PUT");
        expect(init?.body).toBe(
          JSON.stringify({
            expected_arrival: "2025-12-22",
            split_quantity: 3,
            project_id: null,
          }),
        );
        return {
          order_id: 305,
          split_order_id: 402,
          updated_order: {
            order_id: 305,
            item_id: 2,
            quotation_id: 12,
            project_id: null,
            project_name: null,
            canonical_item_number: "BETA-200",
            order_amount: 5,
            ordered_quantity: 5,
            ordered_item_number: "BETA-200",
            order_date: "2025-10-21",
            expected_arrival: "2025-12-10",
            arrival_date: null,
            status: "Ordered",
            supplier_name: "オーテックス",
            quotation_number: "0000001809",
          },
          created_order: {
            order_id: 402,
            item_id: 2,
            quotation_id: 12,
            project_id: null,
            project_name: null,
            canonical_item_number: "BETA-200",
            order_amount: 3,
            ordered_quantity: 3,
            ordered_item_number: "BETA-200",
            order_date: "2025-10-21",
            expected_arrival: "2025-12-22",
            arrival_date: null,
            status: "Ordered",
            supplier_name: "オーテックス",
            quotation_number: "0000001809",
          },
        };
      }
      throw new Error(`Unexpected apiSend path: ${path}`);
    });

    renderPage();

    const orderListSection = sectionByHeading("Order List");
    expect(orderListSection).toBeTruthy();
    await user.click(within(orderListSection as HTMLElement).getByRole("button", { name: "Expand" }));

    const orderRow = (await screen.findByText("BETA-200")).closest("tr");
    expect(orderRow).toBeTruthy();
    await user.click(within(orderRow as HTMLElement).getByRole("button", { name: "Edit Order" }));

    const inputs = within(orderRow as HTMLElement);
    const dateInput = (orderRow as HTMLElement).querySelector('input[type="date"]') as HTMLInputElement | null;
    expect(dateInput).toBeTruthy();
    fireEvent.change(dateInput as HTMLInputElement, { target: { value: "2025-12-22" } });
    await user.type(inputs.getByPlaceholderText("Split qty (1-7)"), "3");
    await user.selectOptions(inputs.getByRole("combobox"), "");
    await user.click(inputs.getByRole("button", { name: "Save Order" }));

    await waitFor(() => {
      expect(apiSendMock).toHaveBeenCalledTimes(1);
    });
    expect(apiSendMock).toHaveBeenCalledWith(
      "/orders/305",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          expected_arrival: "2025-12-22",
          split_quantity: 3,
          project_id: null,
        }),
      }),
    );
  });

  it("points preview pdf-link failures to the upload-first recovery path", async () => {
    const user = userEvent.setup();
    apiSendFormMock.mockRejectedValue(
      new Error("imports/orders/registered/pdf_files/Autex/example.pdf"),
    );

    renderPage();

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement | null;
    expect(fileInput).toBeTruthy();
    const file = new File(["quotation_number,item_number\nQ-1,ITEM-1\n"], "orders.csv", {
      type: "text/csv",
    });
    Object.defineProperty(fileInput, "files", {
      value: [file],
      configurable: true,
    });
    fireEvent.change(fileInput!);

    fireEvent.submit(screen.getByRole("button", { name: "Preview Import" }).closest("form") as HTMLFormElement);
    await waitFor(() => {
      expect(apiSendFormMock).toHaveBeenCalledWith("/orders/import-preview", expect.any(FormData));
    });

    expect(
      await screen.findByText(
        "Preview failed: imports/orders/registered/pdf_files/Autex/example.pdf",
      ),
    ).toBeTruthy();
  });
});
