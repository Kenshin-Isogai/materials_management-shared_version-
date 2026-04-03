import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

const apiGetAllPagesMock = vi.fn();
const apiSendMock = vi.fn();

vi.mock("../src/lib/api", () => ({
  apiGetAllPages: (...args: unknown[]) => apiGetAllPagesMock(...args),
  apiSend: (...args: unknown[]) => apiSendMock(...args),
}));

import { ArrivalPage } from "../src/features/orders/ArrivalPage";

function renderPage() {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MemoryRouter>
        <ArrivalPage />
      </MemoryRouter>
    </SWRConfig>
  );
}

describe("ArrivalPage", () => {
  beforeEach(() => {
    apiGetAllPagesMock.mockReset();
    apiSendMock.mockReset();
    apiGetAllPagesMock.mockResolvedValue([
      {
        order_id: 601,
        purchase_order_id: 71,
        item_id: 1,
        quotation_id: 31,
        project_id: null,
        project_name: null,
        canonical_item_number: "ARR-OVERDUE-ITEM",
        order_amount: 5,
        ordered_quantity: 5,
        ordered_item_number: "ARR-OVERDUE-ITEM",
        order_date: "2026-03-20",
        expected_arrival: "2026-03-25",
        arrival_date: null,
        status: "Ordered",
        supplier_id: 10,
        supplier_name: "Arrival Supplier",
        quotation_number: "Q-ARR-001",
        quotation_document_url: "https://example.com/q-1",
        purchase_order_document_url: "https://example.com/po-1",
        arrival_bucket: "overdue",
        overdue_days: 8,
        days_until_expected: -8,
      },
      {
        order_id: 602,
        purchase_order_id: 71,
        item_id: 1,
        quotation_id: 32,
        project_id: 9,
        project_name: "Project Arrival",
        canonical_item_number: "ARR-SCHEDULED-ITEM",
        order_amount: 3,
        ordered_quantity: 3,
        ordered_item_number: "ARR-SCHEDULED-ITEM",
        order_date: "2026-03-22",
        expected_arrival: "2026-04-10",
        arrival_date: null,
        status: "Ordered",
        supplier_id: 10,
        supplier_name: "Arrival Supplier",
        quotation_number: "Q-ARR-002",
        quotation_document_url: "https://example.com/q-2",
        purchase_order_document_url: "https://example.com/po-2",
        arrival_bucket: "scheduled",
        overdue_days: null,
        days_until_expected: 8,
      },
      {
        order_id: 603,
        purchase_order_id: 72,
        item_id: 2,
        quotation_id: 33,
        project_id: null,
        project_name: null,
        canonical_item_number: "ARR-NOETA-ITEM",
        order_amount: 2,
        ordered_quantity: 2,
        ordered_item_number: "ARR-NOETA-ITEM",
        order_date: "2026-03-23",
        expected_arrival: null,
        arrival_date: null,
        status: "Ordered",
        supplier_id: 11,
        supplier_name: "No ETA Supplier",
        quotation_number: "Q-ARR-003",
        quotation_document_url: "https://example.com/q-3",
        purchase_order_document_url: "https://example.com/po-3",
        arrival_bucket: "no_eta",
        overdue_days: null,
        days_until_expected: null,
      },
    ]);
  });

  afterEach(() => {
    cleanup();
  });

  it("loads the arrival schedule and renders grouped sections", async () => {
    renderPage();

    await waitFor(() => {
      expect(apiGetAllPagesMock).toHaveBeenCalledWith("/arrival-schedule?per_page=200");
    });

    expect(await screen.findByRole("heading", { name: "Arrival" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Overdue" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Scheduled" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "No ETA" })).toBeTruthy();
    expect(screen.getAllByText(/Line #601/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Line #602/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Line #603/).length).toBeGreaterThan(0);
  });

  it("marks an arrival from the detail pane and refreshes the schedule", async () => {
    const user = userEvent.setup();
    apiSendMock.mockResolvedValue({});

    renderPage();

    await screen.findByText(/Line #601/);
    await user.click(screen.getByRole("button", { name: "Mark Arrived" }));

    await waitFor(() => {
      expect(apiSendMock).toHaveBeenCalledWith(
        "/purchase-order-lines/601/arrival",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({}),
        })
      );
    });
    await waitFor(() => {
      expect(apiGetAllPagesMock).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Marked order line #601 as arrived.")).toBeTruthy();
  });

  it("switches to the calendar view", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText(/Line #601/);
    await user.click(screen.getByRole("button", { name: "Calendar" }));

    expect(screen.getByRole("heading", { name: "Arrival Calendar" })).toBeTruthy();
    expect(screen.getByLabelText("Arrival month")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "No ETA" })).toBeTruthy();
  });

  it("submits a partial arrival from the detail pane", async () => {
    const user = userEvent.setup();
    apiSendMock.mockResolvedValue({});

    renderPage();

    await screen.findByText(/Line #601/);
    fireEvent.change(screen.getByLabelText("Partial arrival quantity"), {
      target: { value: "2" },
    });
    await user.click(screen.getByRole("button", { name: "Record Partial Arrival" }));

    await waitFor(() => {
      expect(apiSendMock).toHaveBeenCalledWith(
        "/purchase-order-lines/601/partial-arrival",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ quantity: 2 }),
        })
      );
    });
    expect(await screen.findByText("Recorded partial arrival of 2 units for order line #601.")).toBeTruthy();
  });
});
