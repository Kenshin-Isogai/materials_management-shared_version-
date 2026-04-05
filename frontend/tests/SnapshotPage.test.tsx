import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiGetMock = vi.fn();
const apiDownloadMock = vi.fn();

vi.mock("../src/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/lib/api")>();
  return {
    ...actual,
    apiGet: (...args: unknown[]) => apiGetMock(...args),
    apiDownload: (...args: unknown[]) => apiDownloadMock(...args),
  };
});

import { SnapshotPage } from "../src/features/inventory/SnapshotPage";

function todayJstForTest(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function renderSnapshotPage() {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MemoryRouter>
        <SnapshotPage />
      </MemoryRouter>
    </SWRConfig>,
  );
}

describe("SnapshotPage", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiDownloadMock.mockReset();
    const expectedDate = todayJstForTest();
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === "/users/me") {
        return {
          user_id: 1,
          username: "snapshot.operator",
          display_name: "Snapshot Operator",
          role: "operator",
          is_active: true,
          created_at: "2026-04-05T00:00:00+09:00",
          updated_at: "2026-04-05T00:00:00+09:00",
        };
      }
      return {
        date: expectedDate,
        mode: "future",
        basis: "net_available",
        rows: [],
      };
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("loads today's net-available snapshot on first render", async () => {
    renderSnapshotPage();

    const expectedDate = todayJstForTest();

    await waitFor(() => {
      expect(apiGetMock).toHaveBeenCalledWith(`/inventory/snapshot?date=${expectedDate}&mode=future&basis=net_available`);
    });

    const snapshotCall = apiGetMock.mock.calls.find((call) =>
      String(call[0]).startsWith("/inventory/snapshot?"),
    );
    const requestPath = snapshotCall?.[0];
    expect(requestPath).toMatch(/^\/inventory\/snapshot\?/);
    expect(requestPath).toContain("mode=future");
    expect(requestPath).toContain("basis=net_available");
    expect(requestPath).toContain(`date=${expectedDate}`);

    const dateInput = screen.getByDisplayValue(expectedDate);
    expect(dateInput).toBeTruthy();
    expect(await screen.findByText(/Net available subtracts current active reservation allocations/i)).toBeTruthy();
  });

  it("downloads snapshot csv for the selected parameters", async () => {
    apiDownloadMock.mockResolvedValue(undefined);
    const expectedDate = todayJstForTest();

    renderSnapshotPage();

    await waitFor(() => {
      expect(apiGetMock).toHaveBeenCalledWith(`/inventory/snapshot?date=${expectedDate}&mode=future&basis=net_available`);
    });

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await waitFor(() => {
      expect(apiDownloadMock).toHaveBeenCalledTimes(1);
    });

    expect(apiDownloadMock.mock.calls[0]?.[0]).toMatch(/^\/inventory\/snapshot\/export\.csv\?/);
    expect(apiDownloadMock.mock.calls[0]?.[0]).toContain(`date=${expectedDate}`);
    expect(apiDownloadMock.mock.calls[0]?.[0]).toContain("mode=future");
    expect(apiDownloadMock.mock.calls[0]?.[0]).toContain("basis=net_available");
    expect(await screen.findByText("Snapshot CSV downloaded.")).toBeTruthy();
  });

  it("hides snapshot csv export for non-operators", async () => {
    const expectedDate = todayJstForTest();
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === "/users/me") {
        return {
          user_id: 2,
          username: "snapshot.viewer",
          display_name: "Snapshot Viewer",
          role: "viewer",
          is_active: true,
          created_at: "2026-04-05T00:00:00+09:00",
          updated_at: "2026-04-05T00:00:00+09:00",
        };
      }
      return {
        date: expectedDate,
        mode: "future",
        basis: "net_available",
        rows: [],
      };
    });

    renderSnapshotPage();

    await waitFor(() => {
      expect(apiGetMock).toHaveBeenCalledWith(`/inventory/snapshot?date=${expectedDate}&mode=future&basis=net_available`);
    });

    expect(screen.queryByRole("button", { name: "Export CSV" })).toBeNull();
  });
});
