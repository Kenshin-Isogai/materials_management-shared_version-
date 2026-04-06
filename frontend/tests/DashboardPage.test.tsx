import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiGetMock = vi.fn();

vi.mock("../src/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/lib/api")>();
  return {
    ...actual,
    apiGet: (...args: unknown[]) => apiGetMock(...args),
  };
});

import { DashboardPage } from "../src/features/dashboard/DashboardPage";

function buildOrder(orderId: number) {
  return {
    order_id: orderId,
    item_number: `ITEM-${orderId}`,
    supplier_name: `Supplier ${orderId}`,
    expected_arrival: `2026-02-${String((orderId % 28) + 1).padStart(2, "0")}`,
  };
}

function buildRow(prefix: string, index: number, quantityKey = "quantity") {
  return {
    item_number: `${prefix}-${index}`,
    [quantityKey]: index,
    expiration_date: `2026-05-${String((index % 28) + 1).padStart(2, "0")}`,
    action: `${prefix}-action-${index}`,
    entity_type: "inventory",
    created_at: `2026-04-${String((index % 28) + 1).padStart(2, "0")}T09:00:00+09:00`,
  };
}

function renderPage() {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </SWRConfig>,
  );
}

describe("DashboardPage", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === "/dashboard/summary") {
        return {
          overdue_orders: Array.from({ length: 10 }, (_, index) => buildOrder(index + 101)),
          expiring_reservations: Array.from({ length: 10 }, (_, index) => buildRow("RES", index + 1)),
          low_stock_alerts: Array.from({ length: 10 }, (_, index) => buildRow("LOW", index + 1)),
          recent_activity: Array.from({ length: 10 }, (_, index) => buildRow("ACT", index + 1)),
          pending_registration_requests: 0,
        };
      }
      throw new Error(`Unexpected apiGet path: ${path}`);
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("shows a single overdue-orders table when more than eight rows are present", async () => {
    renderPage();

    const article = await screen.findByRole("heading", { name: "Overdue Orders" });
    const overduePanel = article.closest("article");
    expect(overduePanel).toBeTruthy();

    await waitFor(() => {
      expect(within(overduePanel as HTMLElement).getByRole("table")).toBeTruthy();
    });
    expect(within(overduePanel as HTMLElement).queryByRole("list")).toBeNull();
    expect(within(overduePanel as HTMLElement).getAllByRole("row")).toHaveLength(11);
    expect(within(overduePanel as HTMLElement).getAllByText("#101")).toHaveLength(1);
    expect(screen.getByLabelText("Dashboard overdue orders list").className).toContain("max-h-[24rem]");
    expect(screen.getByLabelText("Dashboard overdue orders list").className).toContain("overflow-y-auto");
  });

  it("switches back to the compact list when filtering down to eight or fewer rows", async () => {
    const user = userEvent.setup();
    renderPage();

    const article = await screen.findByRole("heading", { name: "Overdue Orders" });
    const overduePanel = article.closest("article");
    expect(overduePanel).toBeTruthy();

    await user.type(within(overduePanel as HTMLElement).getByPlaceholderText("Filter overdue orders"), "ITEM-101");

    await waitFor(() => {
      expect(within(overduePanel as HTMLElement).getByRole("list")).toBeTruthy();
    });
    expect(within(overduePanel as HTMLElement).queryByRole("table")).toBeNull();
    expect(within(overduePanel as HTMLElement).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByLabelText("Dashboard overdue orders list").className).toContain("max-h-[24rem]");
    expect(screen.getByLabelText("Dashboard overdue orders list").className).toContain("overflow-y-auto");
  });

  it("caps all dashboard detail panels with independent vertical scroll regions", async () => {
    renderPage();

    const lowStockList = await screen.findByLabelText("Dashboard low stock list");
    const expiringReservationsList = screen.getByLabelText("Dashboard expiring reservations list");
    const recentActivityList = screen.getByLabelText("Dashboard recent activity list");

    expect(lowStockList.className).toContain("max-h-[24rem]");
    expect(lowStockList.className).toContain("overflow-y-auto");
    expect(expiringReservationsList.className).toContain("max-h-[24rem]");
    expect(expiringReservationsList.className).toContain("overflow-y-auto");
    expect(recentActivityList.className).toContain("max-h-[24rem]");
    expect(recentActivityList.className).toContain("overflow-y-auto");
    expect(within(lowStockList).getAllByRole("listitem")).toHaveLength(10);
    expect(within(expiringReservationsList).getAllByRole("listitem")).toHaveLength(10);
    expect(within(recentActivityList).getAllByRole("listitem")).toHaveLength(10);
  });
});
