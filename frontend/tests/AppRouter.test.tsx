import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { SWRConfig } from "swr";

const defaultApiGet = async (path: string) => {
  if (path === "/workspace/summary") {
    return {
      generated_at: "2026-03-08T00:00:00+09:00",
      projects: [],
      pipeline: [],
    };
  }
  if (path === "/projects/1") {
    return {
      project_id: 1,
      name: "Project Alpha",
      status: "PLANNING",
      planned_start: "2026-03-10",
      requirement_count: 0,
      description: null,
      requirements: [],
    };
  }
  throw new Error(`Unexpected apiGet path: ${path}`);
};

const apiGetMock = vi.fn(defaultApiGet);

const apiGetAllPagesMock = vi.fn(async () => []);
const apiGetWithPaginationMock = vi.fn(async () => ({ data: [], pagination: undefined }));
const apiSendMock = vi.fn();
const apiDownloadMock = vi.fn();

vi.mock("../src/lib/api", () => ({
  apiDownload: (...args: unknown[]) => apiDownloadMock(...args),
  apiGet: (...args: unknown[]) => apiGetMock(...args),
  apiGetAllPages: (...args: unknown[]) => apiGetAllPagesMock(...args),
  apiGetWithPagination: (...args: unknown[]) => apiGetWithPaginationMock(...args),
  apiSend: (...args: unknown[]) => apiSendMock(...args),
}));

vi.mock("../src/components/ProjectEditor", () => ({
  ProjectEditor: ({ onDirtyChange }: { onDirtyChange?: (isDirty: boolean) => void }) => {
    useEffect(() => {
      onDirtyChange?.(true);
    }, [onDirtyChange]);
    return <div>Mock Project Editor</div>;
  },
}));

import { appRoutes } from "../src/App";

const activeRouters: Array<{ dispose: () => void }> = [];

function renderRouter(initialEntry: string) {
  const router = createMemoryRouter(appRoutes, {
    initialEntries: [initialEntry],
  });
  activeRouters.push(router);

  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <RouterProvider router={router} />
    </SWRConfig>,
  );

  return router;
}

describe("app router", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiGetMock.mockImplementation(defaultApiGet);
    apiGetAllPagesMock.mockReset();
    apiGetAllPagesMock.mockImplementation(async () => []);
    apiGetWithPaginationMock.mockReset();
    apiGetWithPaginationMock.mockImplementation(async () => ({ data: [], pagination: undefined }));
    apiSendMock.mockReset();
    apiDownloadMock.mockReset();
  });

  afterEach(() => {
    while (activeRouters.length) {
      activeRouters.pop()?.dispose();
    }
    cleanup();
  });

  it("renders the workspace route through a data router without crashing", async () => {
    renderRouter("/workspace");

    expect(screen.getByRole("heading", { name: "Workspace" })).toBeTruthy();

    await waitFor(() => {
      expect(apiGetMock).toHaveBeenCalledWith("/workspace/summary");
    });

    expect(screen.getByText("No projects available yet.")).toBeTruthy();
  });

  it("navigates from /rfq to / without freezing on the RFQ page", async () => {
    const router = renderRouter("/rfq");

    expect(screen.getByRole("heading", { name: "RFQ Workspace" })).toBeTruthy();

    await act(async () => {
      router.navigate("/");
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Dashboard" })).toBeTruthy();
    });

    expect(screen.queryByText("RFQ Workspace")).toBeNull();
  });

});

