import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReservationsPage } from "@/features/inventory/ReservationsPage";

const useSWRMock = vi.fn();

vi.mock("swr", () => ({
  default: (key: string, fetcher: unknown) => useSWRMock(key, fetcher),
}));

vi.mock("@/components/ApiErrorNotice", () => ({
  ApiErrorNotice: () => <div>api error</div>,
}));

vi.mock("@/components/ImportPreviewSummary", () => ({
  ImportPreviewSummary: () => <div>preview summary</div>,
}));

vi.mock("@/components/CatalogPicker", () => ({
  CatalogPicker: () => <div>catalog picker</div>,
}));

const activeReservation = {
  reservation_id: 101,
  item_id: 1,
  item_number: "ITEM-ACTIVE",
  quantity: 2,
  purpose: "Bench work",
  deadline: "2026-04-20",
  status: "ACTIVE" as const,
  note: null,
  created_at: "2026-04-10T00:00:00+09:00",
  stock_backed_quantity: 2,
  incoming_backed_quantity: 0,
};

const releasedReservation = {
  reservation_id: 102,
  item_id: 1,
  item_number: "ITEM-RELEASED",
  quantity: 1,
  purpose: "Old work",
  deadline: "2026-04-05",
  status: "RELEASED" as const,
  note: null,
  created_at: "2026-04-09T00:00:00+09:00",
  stock_backed_quantity: 0,
  incoming_backed_quantity: 0,
};

describe("ReservationsPage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    useSWRMock.mockReset();
    useSWRMock.mockImplementation((key: string) => {
      if (key === "/reservations?status=ACTIVE&per_page=200") {
        return {
          data: { data: [activeReservation], pagination: { page: 1, per_page: 200, total: 1, total_pages: 1 } },
          error: undefined,
          isLoading: false,
          mutate: vi.fn(),
        };
      }
      if (key === "/reservations?per_page=200") {
        return {
          data: {
            data: [activeReservation, releasedReservation],
            pagination: { page: 1, per_page: 200, total: 2, total_pages: 1 },
          },
          error: undefined,
          isLoading: false,
          mutate: vi.fn(),
        };
      }
      if (key === "/reservations-summary-options") {
        return {
          data: [activeReservation, releasedReservation],
          error: undefined,
          isLoading: false,
          mutate: vi.fn(),
        };
      }
      if (key === "/items-options-reservations") {
        return {
          data: { data: [], pagination: { page: 1, per_page: 1000, total: 0, total_pages: 1 } },
          error: undefined,
          isLoading: false,
          mutate: vi.fn(),
        };
      }
      return {
        data: [],
        error: undefined,
        isLoading: false,
        mutate: vi.fn(),
      };
    });
  });

  it("defaults the reservation list to active rows and uses needed-by wording", () => {
    render(
      <MemoryRouter>
        <ReservationsPage />
      </MemoryRouter>
    );

    const reservationListSection = screen
      .getAllByRole("heading", { name: "Reservation List" })[0]
      .closest("section");

    expect(reservationListSection).not.toBeNull();
    expect(useSWRMock).toHaveBeenCalledWith("/reservations?status=ACTIVE&per_page=200", expect.any(Function));
    expect(screen.getAllByText("Needed By").length).toBeGreaterThan(0);
    expect(within(reservationListSection as HTMLElement).getByRole("button", { name: "Active Only (1)" })).toBeTruthy();
    expect(screen.getByText("ITEM-ACTIVE")).not.toBeNull();
    expect(screen.queryByText("ITEM-RELEASED")).toBeNull();
  });

  it("shows released history rows when history is enabled", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <ReservationsPage />
      </MemoryRouter>
    );

    const reservationListSection = screen
      .getAllByRole("heading", { name: "Reservation List" })[0]
      .closest("section");

    expect(reservationListSection).not.toBeNull();
    await user.click(within(reservationListSection as HTMLElement).getByRole("button", { name: "Include History (1)" }));

    expect(useSWRMock).toHaveBeenCalledWith("/reservations?per_page=200", expect.any(Function));
    expect(screen.getByText("ITEM-RELEASED")).not.toBeNull();
    expect(screen.getByText("RELEASED")).not.toBeNull();
  });
});
