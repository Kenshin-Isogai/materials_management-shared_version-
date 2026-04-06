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

import { OrdersPage } from "../src/features/orders/OrdersPage";

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
  const sectionHeading =
    screen
      .getAllByRole("heading", { name })
      .find((element) => element.tagName === "H2") ?? screen.getByRole("heading", { name });
  return sectionHeading.closest("section");
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
      if (path === "/purchase-order-lines?per_page=200") {
        return [
          {
            order_id: 304,
            purchase_order_id: 41,
            purchase_order_number: "PO-41",
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
            quotation_document_url: "https://example.sharepoint.com/sites/procurement/0000001809",
            purchase_order_document_url: "https://example.sharepoint.com/sites/procurement/po-41",
          },
          {
            order_id: 305,
            purchase_order_id: 41,
            purchase_order_number: "PO-41",
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
            quotation_document_url: "https://example.sharepoint.com/sites/procurement/0000001809",
            purchase_order_document_url: "https://example.sharepoint.com/sites/procurement/po-41",
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
      if (path === "/purchase-orders?per_page=200") {
        return [
          {
            purchase_order_id: 41,
            supplier_id: 3,
            supplier_name: "オーテックス",
            purchase_order_number: "PO-41",
            purchase_order_document_url: "https://example.sharepoint.com/sites/procurement/po-41",
            import_locked: true,
            line_count: 2,
            first_order_date: "2025-10-21",
            last_order_date: "2025-10-21",
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
    renderPage();

    await waitFor(() => {
      expect(apiGetAllPagesMock).toHaveBeenCalledWith("/purchase-order-lines?per_page=200");
      expect(apiGetAllPagesMock).toHaveBeenCalledWith("/quotations?per_page=200");
      expect(apiGetAllPagesMock).toHaveBeenCalledWith("/purchase-orders?per_page=200");
    });

    const quotationsSection = sectionByHeading("Quotations");
    expect(quotationsSection).toBeTruthy();
    await waitFor(() => {
      expect(within(quotationsSection as HTMLElement).getByText("Showing 1 / 1 quotations")).toBeTruthy();
      const quotationButton = within(quotationsSection as HTMLElement).getByRole("button", { name: /0000001809/ });
      expect(quotationButton).toBeTruthy();
      expect(quotationButton.textContent).toContain("2 lines");
    });
  });

  it("opens quotation details with linked-line counts and document metadata", async () => {
    const user = userEvent.setup();
    renderPage();

    const quotationsSection = sectionByHeading("Quotations");
    expect(quotationsSection).toBeTruthy();
    await user.click(await within(quotationsSection as HTMLElement).findByRole("button", { name: /0000001809/ }));

    const quotationDetailsSection = screen.getByRole("heading", { name: "Quotation Details" }).closest("section");
    expect(quotationDetailsSection).toBeTruthy();

    await waitFor(() => {
      expect(within(quotationDetailsSection as HTMLElement).getByRole("button", { name: "Clear" })).toBeTruthy();
      expect(within(quotationDetailsSection as HTMLElement).getByText("#12")).toBeTruthy();
      expect(within(quotationDetailsSection as HTMLElement).getByText("Linked lines")).toBeTruthy();
      expect((quotationDetailsSection as HTMLElement).textContent).toContain("0000001809");
      expect((quotationDetailsSection as HTMLElement).textContent).toContain("2025-10-20");
      expect(within(quotationDetailsSection as HTMLElement).getByRole("link", { name: "Open document" })).toBeTruthy();
    });
  });

  it("keeps order details separate from quotation details", async () => {
    const user = userEvent.setup();
    renderPage();

    const orderListSection = sectionByHeading("Purchase Order Lines");
    expect(orderListSection).toBeTruthy();
    const orderRow = (await screen.findByText(/Line #305 .* BETA-200/)).closest(".rounded-2xl");
    expect(orderRow).toBeTruthy();

    await user.click(within(orderRow as HTMLElement).getByRole("button", { name: "Line Details" }));

    const orderDetailsSection = screen.getByRole("heading", { name: "Purchase Order Line Details" }).closest("section");
    const quotationDetailsSection = screen.getByRole("heading", { name: "Quotation Details" }).closest("section");
    expect(orderDetailsSection).toBeTruthy();
    expect(quotationDetailsSection).toBeTruthy();

    await waitFor(() => {
      expect(within(orderDetailsSection as HTMLElement).getByText(/Beta support part/)).toBeTruthy();
    });
    expect((orderDetailsSection as HTMLElement).textContent).toContain("#305");
    expect((quotationDetailsSection as HTMLElement).textContent).toContain("Select a quotation");
  });

  it("filters the expanded order list with search inputs", async () => {
    const user = userEvent.setup();
    renderPage();

    const orderListSection = sectionByHeading("Purchase Order Lines");
    expect(orderListSection).toBeTruthy();

    await user.type(screen.getByPlaceholderText("Search by order #, item, or quotation number"), "BETA");

    await waitFor(() => {
      expect(within(orderListSection as HTMLElement).getByText("Showing 1 / 2 orders")).toBeTruthy();
      expect(within(orderListSection as HTMLElement).getByText(/Line #305 .* BETA-200/)).toBeTruthy();
    });
    expect(within(orderListSection as HTMLElement).queryByText(/Line #304 .* AOMO3080-125/)).toBeNull();
  });

  it("keeps line actions in one shared action row", async () => {
    renderPage();

    const orderRow = (await screen.findByText(/Line #304 .* AOMO3080-125/)).closest(".rounded-2xl");
    expect(orderRow).toBeTruthy();

    const lineDetailsButton = within(orderRow as HTMLElement).getByRole("button", { name: "Line Details" });
    const markArrivedButton = within(orderRow as HTMLElement).getByRole("button", { name: "Mark Arrived" });
    const editOrderButton = within(orderRow as HTMLElement).getByRole("button", { name: "Edit Order" });
    const deleteButton = within(orderRow as HTMLElement).getByRole("button", { name: "Delete" });

    const actionRow = lineDetailsButton.parentElement;
    expect(actionRow).toBeTruthy();
    expect(actionRow).toBe(markArrivedButton.parentElement);
    expect(actionRow).toBe(editOrderButton.parentElement);
    expect(actionRow).toBe(deleteButton.parentElement);
    expect(actionRow?.className).toContain("flex-wrap");
    expect(actionRow?.className).toContain("items-center");
  });

  it("requires confirmation before deleting a purchase order line", async () => {
    const user = userEvent.setup();
    apiSendMock.mockResolvedValue({});

    renderPage();

    const orderRow = (await screen.findByText(/Line #304 .* AOMO3080-125/)).closest(".rounded-2xl");
    expect(orderRow).toBeTruthy();

    await user.click(within(orderRow as HTMLElement).getByRole("button", { name: "Delete" }));

    const confirmDialog = await screen.findByRole("dialog");
    expect(within(confirmDialog).getByRole("heading", { name: "Delete purchase order line?" })).toBeTruthy();
    expect(within(confirmDialog).getByText(/Line #304 \(AOMO3080-125\) will be deleted/)).toBeTruthy();
    expect(apiSendMock).not.toHaveBeenCalled();

    await user.click(within(confirmDialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(apiSendMock).not.toHaveBeenCalled();

    await user.click(within(orderRow as HTMLElement).getByRole("button", { name: "Delete" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(apiSendMock).toHaveBeenCalledWith(
        "/purchase-order-lines/304",
        expect.objectContaining({ method: "DELETE" }),
      );
    });
  });

  it("shows purchase-order headers separately from quotation headers", async () => {
    const user = userEvent.setup();
    renderPage();

    const purchaseOrdersSection = sectionByHeading("Purchase Orders");
    expect(purchaseOrdersSection).toBeTruthy();

    await waitFor(() => {
      expect(within(purchaseOrdersSection as HTMLElement).getByText("Showing 1 / 1 purchase orders")).toBeTruthy();
    });

    await user.click(within(purchaseOrdersSection as HTMLElement).getByRole("button", { name: /PO-41/ }));

    const purchaseOrderDetailsSection = screen.getByRole("heading", { name: "Purchase Order Details" }).closest("section");
    expect(purchaseOrderDetailsSection).toBeTruthy();

    await waitFor(() => {
      expect(within(purchaseOrderDetailsSection as HTMLElement).getByText("#41")).toBeTruthy();
      expect(within(purchaseOrderDetailsSection as HTMLElement).getByText("Linked quotations")).toBeTruthy();
      expect(within(purchaseOrderDetailsSection as HTMLElement).getByText("Line #304 · AOMO3080-125")).toBeTruthy();
      expect(within(purchaseOrderDetailsSection as HTMLElement).getByText("Line #305 · BETA-200")).toBeTruthy();
    });
  });

  it("uses the same capped scroll height for quotation and purchase-order header lists", async () => {
    renderPage();

    const quotationsSection = sectionByHeading("Quotations");
    const purchaseOrdersSection = sectionByHeading("Purchase Orders");
    expect(quotationsSection).toBeTruthy();
    expect(purchaseOrdersSection).toBeTruthy();

    await waitFor(() => {
      expect(within(quotationsSection as HTMLElement).getByText("Showing 1 / 1 quotations")).toBeTruthy();
      expect(within(purchaseOrdersSection as HTMLElement).getByText("Showing 1 / 1 purchase orders")).toBeTruthy();
    });

    const quotationList = within(quotationsSection as HTMLElement).getByText("Showing 1 / 1 quotations").closest("div");
    const purchaseOrderList = within(purchaseOrdersSection as HTMLElement).getByText("Showing 1 / 1 purchase orders").closest("div");

    expect(quotationList?.className).toContain("max-h-[42rem]");
    expect(quotationList?.className).toContain("overflow-y-auto");
    expect(purchaseOrderList?.className).toContain("max-h-[42rem]");
    expect(purchaseOrderList?.className).toContain("overflow-y-auto");
  });

  it("splits first and assigns only the created child order when a project is selected", async () => {
    const user = userEvent.setup();
    apiSendMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/purchase-order-lines/304") {
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
            purchase_order_id: 41,
            purchase_order_number: "PO-41",
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
            quotation_document_url: "https://example.sharepoint.com/sites/procurement/0000001809",
            purchase_order_document_url: "https://example.sharepoint.com/sites/procurement/po-41",
          },
          created_order: {
            order_id: 401,
            purchase_order_id: 41,
            purchase_order_number: "PO-41",
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
            quotation_document_url: "https://example.sharepoint.com/sites/procurement/0000001809",
            purchase_order_document_url: "https://example.sharepoint.com/sites/procurement/po-41",
          },
        };
      }
      if (path === "/purchase-order-lines/401") {
        expect(init?.method).toBe("PUT");
        expect(init?.body).toBe(JSON.stringify({ project_id: 12 }));
        return {};
      }
      throw new Error(`Unexpected apiSend path: ${path}`);
    });

    renderPage();

    const orderListSection = sectionByHeading("Purchase Order Lines");
    expect(orderListSection).toBeTruthy();
    const orderRow = (await screen.findByText(/Line #304 .* AOMO3080-125/)).closest(".rounded-2xl");
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
      "/purchase-order-lines/304",
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
      "/purchase-order-lines/401",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ project_id: 12 }),
      }),
    );
  });

  it("preserves explicit project clearing when splitting an assigned order", async () => {
    const user = userEvent.setup();
    apiSendMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/purchase-order-lines/305") {
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
            purchase_order_id: 41,
            purchase_order_number: "PO-41",
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
            quotation_document_url: "https://example.sharepoint.com/sites/procurement/0000001809",
            purchase_order_document_url: "https://example.sharepoint.com/sites/procurement/po-41",
          },
          created_order: {
            order_id: 402,
            purchase_order_id: 41,
            purchase_order_number: "PO-41",
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
            quotation_document_url: "https://example.sharepoint.com/sites/procurement/0000001809",
            purchase_order_document_url: "https://example.sharepoint.com/sites/procurement/po-41",
          },
        };
      }
      throw new Error(`Unexpected apiSend path: ${path}`);
    });

    renderPage();

    const orderListSection = sectionByHeading("Purchase Order Lines");
    expect(orderListSection).toBeTruthy();
    const orderRow = (await screen.findByText(/Line #305 .* BETA-200/)).closest(".rounded-2xl");
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
      "/purchase-order-lines/305",
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

  it("revalidates purchase-order headers after confirming an import", async () => {
    const user = userEvent.setup();
    apiSendFormMock.mockImplementation(async (path: string) => {
      if (path === "/purchase-order-lines/import-preview") {
        return {
          can_auto_accept: true,
          blocking_errors: [],
          duplicate_quotation_numbers: [],
          locked_purchase_orders: [],
          source_name: "orders.csv",
          supplier: {
            supplier_id: null,
            supplier_name: "Per-row supplier",
            exists: false,
            mode: "per_row",
          },
          thresholds: {
            auto_accept: 100,
            review: 80,
          },
          summary: {
            total_rows: 1,
            exact: 1,
            high_confidence: 0,
            needs_review: 0,
            unresolved: 0,
          },
          rows: [
            {
              row: 1,
              source_index: 0,
              source_name: "orders.csv",
              supplier_id: 3,
              supplier_name: "オーテックス",
              item_number: "AOMO3080-125",
              quantity: 15,
              purchase_order_number: "PO-41",
              quotation_number: "0000001809",
              order_date: "2025-10-21",
              expected_arrival: "2025-11-30",
              quotation_document_url: "https://example.sharepoint.com/sites/procurement/0000001809",
              purchase_order_document_url: "https://example.sharepoint.com/sites/procurement/po-41",
              status: "exact",
              confidence_score: 100,
              warnings: [],
              candidates: [],
              suggested_match: {
                item_id: 1,
                canonical_item_number: "AOMO3080-125",
                manufacturer_name: "AUTEX",
                item_number: "AOMO3080-125",
                units_per_order: 1,
                display_label: "AOMO3080-125",
                value_text: "AOMO3080-125",
                summary: "Autex test optic",
                match_source: "exact_item_number",
                match_reason: "Exact item-number match",
                confidence_score: 100,
              },
              order_amount: 15,
            },
          ],
        };
      }
      if (path === "/purchase-order-lines/import") {
        return {
          status: "ok",
          imported_count: 1,
          saved_alias_count: 0,
        };
      }
      throw new Error(`Unexpected apiSendForm path: ${path}`);
    });

    renderPage();

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement | null;
    expect(fileInput).toBeTruthy();
    const file = new File(["supplier,item_number,quantity\nオーテックス,AOMO3080-125,15\n"], "orders.csv", {
      type: "text/csv",
    });
    await user.upload(fileInput as HTMLInputElement, file);

    await waitFor(() => {
      expect(screen.getByText("1 file(s) selected")).toBeTruthy();
    });

    fireEvent.submit(screen.getByRole("button", { name: "Preview Import" }).closest("form") as HTMLFormElement);

    expect(await screen.findByRole("button", { name: "Confirm Import" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Confirm Import" }));

    await waitFor(() => {
      expect(apiSendFormMock).toHaveBeenCalledWith("/purchase-order-lines/import", expect.any(FormData));
    });
    await waitFor(() => {
      expect(
        apiGetAllPagesMock.mock.calls.filter(([path]) => path === "/purchase-orders?per_page=200")
      ).toHaveLength(2);
    });
  });

  it("does not show or submit a shared order-date field for CSV import", async () => {
    const user = userEvent.setup();
    apiSendFormMock.mockImplementation(async (path: string, form: FormData) => {
      if (path === "/purchase-order-lines/import-preview") {
        expect(form.get("default_order_date")).toBeNull();
        return {
          can_auto_accept: true,
          blocking_errors: [],
          duplicate_quotation_numbers: [],
          locked_purchase_orders: [],
          source_name: "orders.csv",
          supplier: {
            supplier_id: null,
            supplier_name: "Per-row supplier",
            exists: false,
            mode: "per_row",
          },
          thresholds: {
            auto_accept: 100,
            review: 80,
          },
          summary: {
            total_rows: 1,
            exact: 1,
            high_confidence: 0,
            needs_review: 0,
            unresolved: 0,
          },
          rows: [
            {
              row: 1,
              source_index: 0,
              source_name: "orders.csv",
              supplier_id: 3,
              supplier_name: "オーテックス",
              item_number: "AOMO3080-125",
              quantity: 15,
              purchase_order_number: "PO-41",
              quotation_number: "0000001809",
              issue_date: "2025-10-20",
              order_date: "2025-10-21",
              expected_arrival: "2025-11-30",
              quotation_document_url: "https://example.sharepoint.com/sites/procurement/0000001809",
              purchase_order_document_url: "https://example.sharepoint.com/sites/procurement/po-41",
              status: "exact",
              confidence_score: 100,
              warnings: [],
              candidates: [],
              suggested_match: {
                item_id: 1,
                canonical_item_number: "AOMO3080-125",
                manufacturer_name: "AUTEX",
                item_number: "AOMO3080-125",
                units_per_order: 1,
                display_label: "AOMO3080-125",
                value_text: "AOMO3080-125",
                summary: "Autex test optic",
                match_source: "exact_item_number",
                match_reason: "Exact item-number match",
                confidence_score: 100,
              },
              order_amount: 15,
            },
          ],
        };
      }
      throw new Error(`Unexpected apiSendForm path: ${path}`);
    });

    renderPage();

    expect(document.querySelector('input[type="date"]')).toBeNull();
    expect(
      screen.getByText(/any needed order date should come from the CSV/i),
    ).toBeTruthy();

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement | null;
    expect(fileInput).toBeTruthy();
    const file = new File(["supplier,item_number,quantity\nオーテックス,AOMO3080-125,15\n"], "orders.csv", {
      type: "text/csv",
    });
    await user.upload(fileInput as HTMLInputElement, file);

    fireEvent.submit(screen.getByRole("button", { name: "Preview Import" }).closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(apiSendFormMock).toHaveBeenCalledWith("/purchase-order-lines/import-preview", expect.any(FormData));
    });
  });

  it("highlights item number and quantity in the import preview raw input", async () => {
    const user = userEvent.setup();
    apiSendFormMock.mockImplementation(async (path: string) => {
      if (path === "/purchase-order-lines/import-preview") {
        return {
          can_auto_accept: true,
          blocking_errors: [],
          duplicate_quotation_numbers: [],
          locked_purchase_orders: [],
          source_name: "orders.csv",
          supplier: {
            supplier_id: null,
            supplier_name: "Per-row supplier",
            exists: false,
            mode: "per_row",
          },
          thresholds: {
            auto_accept: 100,
            review: 80,
          },
          summary: {
            total_rows: 1,
            exact: 1,
            high_confidence: 0,
            needs_review: 0,
            unresolved: 0,
          },
          rows: [
            {
              row: 1,
              source_index: 0,
              source_name: "orders.csv",
              supplier_id: 3,
              supplier_name: "オーテックス",
              item_number: "AOMO3080-125",
              quantity: 15,
              purchase_order_number: "PO-41",
              quotation_number: "0000001809",
              order_date: "2025-10-21",
              expected_arrival: "2025-11-30",
              quotation_document_url: "https://example.sharepoint.com/sites/procurement/0000001809",
              purchase_order_document_url: "https://example.sharepoint.com/sites/procurement/po-41",
              status: "exact",
              confidence_score: 100,
              warnings: [],
              candidates: [],
              suggested_match: {
                item_id: 1,
                canonical_item_number: "AOMO3080-125",
                manufacturer_name: "AUTEX",
                item_number: "AOMO3080-125",
                units_per_order: 1,
                display_label: "AOMO3080-125",
                value_text: "AOMO3080-125",
                summary: "Autex test optic",
                match_source: "exact_item_number",
                match_reason: "Exact item-number match",
                confidence_score: 100,
              },
              order_amount: 15,
            },
          ],
        };
      }
      throw new Error(`Unexpected apiSendForm path: ${path}`);
    });

    renderPage();

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement | null;
    expect(fileInput).toBeTruthy();
    const file = new File(["supplier,item_number,quantity\nオーテックス,AOMO3080-125,15\n"], "orders.csv", {
      type: "text/csv",
    });
    await user.upload(fileInput as HTMLInputElement, file);

    fireEvent.submit(screen.getByRole("button", { name: "Preview Import" }).closest("form") as HTMLFormElement);

    expect(await screen.findByRole("button", { name: "Confirm Import" })).toBeTruthy();

    const row = screen
      .getAllByText("AOMO3080-125")
      .map((element) => element.closest("tr"))
      .find((candidate) => candidate?.textContent?.includes("Quantity"));
    expect(row).toBeTruthy();
    expect(within(row as HTMLElement).getByText("Item Number")).toBeTruthy();
    expect(within(row as HTMLElement).getByText("Quantity")).toBeTruthy();
    expect(within(row as HTMLElement).getByText("15")).toBeTruthy();
    expect((row as HTMLElement).textContent).toContain("orders.csv | オーテックス | PO PO-41 | quotation 0000001809");
  });

  it("revalidates purchase-order headers after marking a line arrived", async () => {
    const user = userEvent.setup();
    apiSendMock.mockResolvedValue({});

    renderPage();

    const orderRow = (await screen.findByText(/Line #304 .* AOMO3080-125/)).closest(".rounded-2xl");
    expect(orderRow).toBeTruthy();
    await user.click(within(orderRow as HTMLElement).getByRole("button", { name: "Mark Arrived" }));

    await waitFor(() => {
      expect(apiSendMock).toHaveBeenCalledWith(
        "/purchase-order-lines/304/arrival",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({}),
        }),
      );
    });
    await waitFor(() => {
      expect(
        apiGetAllPagesMock.mock.calls.filter(([path]) => path === "/purchase-orders?per_page=200")
      ).toHaveLength(2);
    });
  });

  it("revalidates purchase-order headers after deleting a line", async () => {
    const user = userEvent.setup();
    apiSendMock.mockResolvedValue({});

    renderPage();

    const orderRow = (await screen.findByText(/Line #304 .* AOMO3080-125/)).closest(".rounded-2xl");
    expect(orderRow).toBeTruthy();
    await user.click(within(orderRow as HTMLElement).getByRole("button", { name: "Delete" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(apiSendMock).toHaveBeenCalledWith(
        "/purchase-order-lines/304",
        expect.objectContaining({
          method: "DELETE",
        }),
      );
    });
    await waitFor(() => {
      expect(
        apiGetAllPagesMock.mock.calls.filter(([path]) => path === "/purchase-orders?per_page=200")
      ).toHaveLength(2);
    });
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
      expect(apiSendFormMock).toHaveBeenCalledWith("/purchase-order-lines/import-preview", expect.any(FormData));
    });

    expect(
      await screen.findByText(
        "Preview failed: imports/orders/registered/pdf_files/Autex/example.pdf",
      ),
    ).toBeTruthy();
  });
});
