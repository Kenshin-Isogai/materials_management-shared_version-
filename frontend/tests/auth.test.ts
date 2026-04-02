import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const originalApiKey = import.meta.env.VITE_IDENTITY_PLATFORM_API_KEY;

async function loadAuthModule() {
  vi.resetModules();
  return import("../src/lib/auth");
}

describe("auth session handling", () => {
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
    vi.unstubAllGlobals();
  });

  it("refreshes when the token is inside the safety window", async () => {
    const now = 1_700_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(now);
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("securetoken.googleapis.com")) {
        return {
          ok: true,
          json: async () => ({
            id_token: "refreshed-token",
            refresh_token: "refresh-1",
            expires_in: "3600",
          }),
        };
      }
      if (url.includes("accounts:lookup")) {
        return {
          ok: true,
          json: async () => ({
            users: [{ email: "user@example.com", emailVerified: true }],
          }),
        };
      }
      throw new Error(`Unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.sessionStorage.setItem(
      "materials.auth-session",
      JSON.stringify({
        accessToken: "old-token",
        refreshToken: "refresh-1",
        expiresAt: now + 30_000,
        email: "user@example.com",
      }),
    );

    const auth = await loadAuthModule();
    await expect(auth.getValidAccessTokenOrNull()).resolves.toBe("refreshed-token");

    const stored = JSON.parse(window.sessionStorage.getItem("materials.auth-session") ?? "{}");
    expect(stored.accessToken).toBe("refreshed-token");
    expect(stored.refreshToken).toBe("refresh-1");
    expect(stored.email).toBe("user@example.com");
    expect(stored.emailVerified).toBe(true);
  });

  it("clears the session when refresh fails", async () => {
    const now = 1_700_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(now);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 400,
        json: async () => ({
          error: { message: "TOKEN_EXPIRED" },
        }),
      })),
    );
    window.sessionStorage.setItem(
      "materials.auth-session",
      JSON.stringify({
        accessToken: "old-token",
        refreshToken: "refresh-1",
        expiresAt: now + 30_000,
      }),
    );

    const auth = await loadAuthModule();
    await expect(auth.getValidAccessTokenOrNull()).rejects.toThrow("TOKEN_EXPIRED");
    expect(window.sessionStorage.getItem("materials.auth-session")).toBeNull();
  });

  it("does not attempt refresh for manual token fallback", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    window.localStorage.setItem("materials.access-token", "manual-token");

    const auth = await loadAuthModule();
    await expect(auth.getValidAccessTokenOrNull()).resolves.toBe("manual-token");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem("materials.auth-session")).toContain("manual-token");
  });

  it("stores sign-up session metadata and can send a verification email", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("accounts:signUp")) {
        return {
          ok: true,
          json: async () => ({
            idToken:
              "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6InNpZ251cEBleGFtcGxlLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjpmYWxzZX0.signature",
            refreshToken: "refresh-signup",
            expiresIn: "3600",
            email: "signup@example.com",
          }),
        };
      }
      if (url.includes("accounts:sendOobCode")) {
        return {
          ok: true,
          json: async () => ({
            email: "signup@example.com",
          }),
        };
      }
      throw new Error(`Unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth = await loadAuthModule();
    await auth.signUpWithIdentityPlatformEmailPassword("signup@example.com", "password");
    await auth.sendIdentityPlatformVerificationEmail();

    const stored = JSON.parse(window.sessionStorage.getItem("materials.auth-session") ?? "{}");
    expect(stored.email).toBe("signup@example.com");
    expect(stored.emailVerified).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("can force-refresh the stored session after email verification", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("securetoken.googleapis.com")) {
        return {
          ok: true,
          json: async () => ({
            id_token:
              "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6InNpZ251cEBleGFtcGxlLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlfQ.signature",
            refresh_token: "refresh-signup",
            expires_in: "3600",
          }),
        };
      }
      throw new Error(`Unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.sessionStorage.setItem(
      "materials.auth-session",
      JSON.stringify({
        accessToken:
          "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6InNpZ251cEBleGFtcGxlLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjpmYWxzZX0.signature",
        refreshToken: "refresh-signup",
        expiresAt: Date.now() + 3_600_000,
        email: "signup@example.com",
        emailVerified: false,
      }),
    );

    const auth = await loadAuthModule();
    await auth.refreshStoredAuthSessionNow();

    const stored = JSON.parse(window.sessionStorage.getItem("materials.auth-session") ?? "{}");
    expect(stored.email).toBe("signup@example.com");
    expect(stored.emailVerified).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries refresh once when lookup says the email is verified but the refreshed token is still stale", async () => {
    let refreshCount = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("securetoken.googleapis.com")) {
        refreshCount += 1;
        return {
          ok: true,
          json: async () => ({
            id_token:
              refreshCount === 1
                ? "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6InNpZ251cEBleGFtcGxlLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjpmYWxzZX0.signature"
                : "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6InNpZ251cEBleGFtcGxlLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlfQ.signature",
            refresh_token: "refresh-signup",
            expires_in: "3600",
          }),
        };
      }
      if (url.includes("accounts:lookup")) {
        return {
          ok: true,
          json: async () => ({
            users: [{ email: "signup@example.com", emailVerified: true }],
          }),
        };
      }
      throw new Error(`Unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.sessionStorage.setItem(
      "materials.auth-session",
      JSON.stringify({
        accessToken:
          "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6InNpZ251cEBleGFtcGxlLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjpmYWxzZX0.signature",
        refreshToken: "refresh-signup",
        expiresAt: Date.now() + 3_600_000,
        email: "signup@example.com",
        emailVerified: false,
      }),
    );

    const auth = await loadAuthModule();
    await auth.refreshStoredAuthSessionNow();

    const stored = JSON.parse(window.sessionStorage.getItem("materials.auth-session") ?? "{}");
    expect(stored.emailVerified).toBe(true);
    expect(refreshCount).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("can apply an email verification action code", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("accounts:update")) {
        return {
          ok: true,
          json: async () => ({
            email: "signup@example.com",
          }),
        };
      }
      throw new Error(`Unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const auth = await loadAuthModule();
    await auth.applyIdentityPlatformEmailVerificationCode("sample-oob-code");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0] ?? "")).toContain("accounts:update");
  });
});
