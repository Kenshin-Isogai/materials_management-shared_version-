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
          expiring_reservations: [],
          low_stock_alerts: [],
          recent_activity: [],
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
  });
});
