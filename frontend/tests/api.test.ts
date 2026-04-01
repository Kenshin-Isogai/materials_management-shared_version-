import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const originalApiKey = import.meta.env.VITE_IDENTITY_PLATFORM_API_KEY;

async function loadApiModule() {
  vi.resetModules();
  return import("../src/lib/api");
}

describe("api client auth error handling", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    import.meta.env.VITE_IDENTITY_PLATFORM_API_KEY = "test-api-key";
    vi.restoreAllMocks();
  });

  afterEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    import.meta.env.VITE_IDENTITY_PLATFORM_API_KEY = originalApiKey;
  });

  it("preserves auth-required errors when mutation headers cannot be prepared", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const api = await loadApiModule();

    await expect(api.apiSendForm("/items/import", new FormData())).rejects.toMatchObject({
      name: "ApiClientError",
      message: "Set an access token before performing changes.",
      statusCode: 401,
      code: "AUTH_REQUIRED",
      isNetworkError: false,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("classifies expired token refresh as an auth error", async () => {
    const now = 1_700_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(now);
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("https://securetoken.googleapis.com/")) {
        return {
          ok: false,
          status: 400,
          json: async () => ({
            error: { message: "TOKEN_EXPIRED" },
          }),
        };
      }
      throw new Error(`Unexpected fetch call: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.sessionStorage.setItem(
      "materials.auth-session",
      JSON.stringify({
        accessToken: "old-token",
        refreshToken: "refresh-1",
        expiresAt: now + 30_000,
      }),
    );

    const api = await loadApiModule();

    await expect(api.apiSendForm("/items/import", new FormData())).rejects.toMatchObject({
      name: "ApiClientError",
      message: "Session expired. Please sign in again.",
      statusCode: 401,
      code: "INVALID_TOKEN",
      isNetworkError: false,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
