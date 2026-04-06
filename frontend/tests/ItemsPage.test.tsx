import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiGetMock = vi.fn();
const apiGetWithPaginationMock = vi.fn();
const apiSendMock = vi.fn();

vi.mock("../src/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/lib/api")>();
  return {
    ...actual,
    apiGet: (...args: unknown[]) => apiGetMock(...args),
    apiGetWithPagination: (...args: unknown[]) => apiGetWithPaginationMock(...args),
    apiSend: (...args: unknown[]) => apiSendMock(...args),
  };
});

import { ItemsPage } from "../src/features/items/ItemsPage";

function renderPage() {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MemoryRouter>
        <ItemsPage />
      </MemoryRouter>
    </SWRConfig>,
  );
}

describe("ItemsPage", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === "/manufacturers") {
        return [
          { manufacturer_id: 1, name: "Thorlabs" },
          { manufacturer_id: 2, name: "Edmund Optics" },
        ];
      }
      if (path === "/suppliers") {
        return [
          { supplier_id: 1, name: "Misumi" },
          { supplier_id: 2, name: "Digikey" },
        ];
      }
      if (path === "/categories") {
        return ["Lens", "Mirror"];
      }
      throw new Error(`Unexpected apiGet path: ${path}`);
    });
    apiGetWithPaginationMock.mockReset();
    apiGetWithPaginationMock.mockImplementation(async (path: string) => {
      if (path === "/items?q=" || path === "/items?per_page=1000" || path === "/items/import-jobs?per_page=20") {
        return { data: [], pagination: undefined };
      }
      throw new Error(`Unexpected apiGetWithPagination path: ${path}`);
    });
    apiSendMock.mockReset();
    apiSendMock.mockResolvedValue({
      item_id: 1,
      item_number: "LENS-001",
      manufacturer_name: "Thorlabs",
      category: "Lens",
      url: null,
      description: null,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("offers registered manufacturer and supplier names as bulk-entry suggestions while keeping free-text inputs", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Bulk Item Entry" })).toBeTruthy();
    });

    const manufacturerInput = screen.getAllByPlaceholderText("Thorlabs")[0];
    const supplierInput = screen.getAllByPlaceholderText("Supplier for alias")[0];

    expect(manufacturerInput.getAttribute("list")).toBe("bulk-item-manufacturer-options");
    expect(supplierInput.getAttribute("list")).toBe("bulk-item-supplier-options");

    const manufacturerOptions = document.querySelectorAll(
      '#bulk-item-manufacturer-options option',
    );
    const supplierOptions = document.querySelectorAll('#bulk-item-supplier-options option');

    expect(Array.from(manufacturerOptions).map((node) => node.getAttribute("value"))).toEqual([
      "Thorlabs",
      "Edmund Optics",
    ]);
    expect(Array.from(supplierOptions).map((node) => node.getAttribute("value"))).toEqual([
      "Misumi",
      "Digikey",
    ]);
  });

  it("shows a completion summary after bulk item submit", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Bulk Item Entry" })).toBeTruthy();
    });

    fireEvent.change(screen.getAllByPlaceholderText("LENS-001")[0], {
      target: { value: "LENS-001" },
    });
    fireEvent.change(screen.getAllByPlaceholderText("Thorlabs")[0], {
      target: { value: "Thorlabs" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Submit Bulk Rows" }));

    await waitFor(() => {
      expect(screen.getByText("Bulk submit completed: created 1 item(s), upserted 0 alias row(s).")).toBeTruthy();
    });

    expect(apiSendMock).toHaveBeenCalledWith("/items", expect.objectContaining({ method: "POST" }));
  });
});
