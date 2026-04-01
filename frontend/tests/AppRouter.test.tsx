import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { SWRConfig } from "swr";
import { ApiClientError } from "../src/lib/types";

const defaultApiGet = async (path: string) => {
  if (path === "/dashboard/summary") {
    return {
      overdue_orders: [],
      expiring_reservations: [],
      low_stock_alerts: [],
      recent_activity: [],
    };
  }
  if (path === "/users/me") {
    return {
      user_id: 1,
      username: "admin",
      display_name: "Admin",
      role: "admin",
      is_active: true,
      created_at: "2026-03-08T00:00:00+09:00",
      updated_at: "2026-03-08T00:00:00+09:00",
      email: "admin@example.com",
      external_subject: null,
      identity_provider: null,
      hosted_domain: null,
    };
  }
  if (path === "/auth/registration-status") {
    return {
      state: "not_requested",
      email: "admin@example.com",
      identity_provider: "identity_platform",
      external_subject: "sub-admin",
      current_user: null,
      request: null,
    };
  }
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

vi.mock("../src/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/lib/api")>();
  return {
    ...actual,
    apiDownload: (...args: unknown[]) => apiDownloadMock(...args),
    apiGet: (...args: unknown[]) => apiGetMock(...args),
    apiGetAllPages: (...args: unknown[]) => apiGetAllPagesMock(...args),
    apiGetWithPagination: (...args: unknown[]) => apiGetWithPaginationMock(...args),
    apiSend: (...args: unknown[]) => apiSendMock(...args),
    getStoredUsernameOrNull: () => null,
    setStoredUsername: vi.fn(),
    subscribeUsersChanged: () => () => {},
  };
});

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
    window.sessionStorage.clear();
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

  it("redirects the removed /rfq route back to the dashboard", async () => {
    const router = renderRouter("/rfq");

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Dashboard" })).toBeTruthy();
    });

    expect(screen.queryByText("RFQ Workspace")).toBeNull();
    expect(router.state.location.pathname).toBe("/");
  });

  it("routes signed-in unmapped identities into registration when protected requests return auth errors", async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === "/dashboard/summary" || path === "/users/me") {
        throw new ApiClientError({
          message: "Bearer token is required",
          statusCode: 401,
          code: "AUTH_REQUIRED",
        });
      }
      return defaultApiGet(path);
    });

    act(() => {
      window.sessionStorage.setItem("materials.auth-session", JSON.stringify({ accessToken: "token" }));
    });

    renderRouter("/");

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Register for access" })).toBeTruthy();
    });
    expect(
      screen.getByText("Signed-in identities need admin approval before this application can grant access."),
    ).toBeTruthy();
  });

  it("shows an environment-unavailable message when dashboard requests cannot reach the backend", async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === "/dashboard/summary") {
        throw new ApiClientError({
          message: "Could not reach the backend service.",
          isNetworkError: true,
        });
      }
      return defaultApiGet(path);
    });

    renderRouter("/");

    await waitFor(() => {
      expect(screen.getByText("Environment unavailable")).toBeTruthy();
    });
    expect(
      screen.getByText(
        "Dashboard is unavailable because the backend or database is not ready. If this is dev or staging, start Cloud SQL and try again.",
      ),
    ).toBeTruthy();
  });

  it("redirects signed-in identities without an active app user to /registration", async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === "/users/me") {
        throw new ApiClientError({
          message: "User not found",
          statusCode: 403,
          code: "USER_NOT_FOUND",
        });
      }
      if (path === "/auth/registration-status") {
        return {
          state: "not_requested",
          email: "pending@example.com",
          identity_provider: "identity_platform",
          external_subject: "sub-pending",
          current_user: null,
          request: null,
        };
      }
      return defaultApiGet(path);
    });

    act(() => {
      window.sessionStorage.setItem("materials.auth-session", JSON.stringify({ accessToken: "token" }));
    });

    const router = renderRouter("/");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/registration");
    });
    expect(screen.getByRole("heading", { name: "Register for access" })).toBeTruthy();
  });

  it("redirects approved users away from /registration", async () => {
    act(() => {
      window.sessionStorage.setItem("materials.auth-session", JSON.stringify({ accessToken: "token" }));
    });

    const router = renderRouter("/registration");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeTruthy();
  });

});

