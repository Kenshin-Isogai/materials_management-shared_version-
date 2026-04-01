const AUTH_SESSION_STORAGE_KEY = "materials.auth-session";
const AUTH_SESSION_CHANGED_EVENT = "materials:auth-session-changed";
const IDENTITY_PLATFORM_API_KEY = String(import.meta.env.VITE_IDENTITY_PLATFORM_API_KEY ?? "").trim();
const EXPIRY_SAFETY_WINDOW_MS = 60_000;

type StoredAuthSession = {
  accessToken: string;
  refreshToken?: string | null;
  expiresAt?: number | null;
  email?: string | null;
};

type IdentityPlatformSignInResponse = {
  idToken?: string;
  refreshToken?: string;
  expiresIn?: string;
  email?: string;
  error?: {
    message?: string;
  };
};

type IdentityPlatformRefreshResponse = {
  id_token?: string;
  refresh_token?: string;
  expires_in?: string;
  user_id?: string;
  error?: {
    message?: string;
  };
};

let refreshInFlight: Promise<StoredAuthSession | null> | null = null;

function normalizeSession(value: unknown): StoredAuthSession | null {
  if (!value) return null;
  if (typeof value === "string") {
    const token = value.trim();
    return token ? { accessToken: token } : null;
  }
  if (typeof value !== "object") return null;
  const candidate = value as StoredAuthSession;
  const accessToken = String(candidate.accessToken ?? "").trim();
  if (!accessToken) return null;
  const refreshToken = candidate.refreshToken ? String(candidate.refreshToken).trim() : null;
  const expiresAt =
    typeof candidate.expiresAt === "number" && Number.isFinite(candidate.expiresAt)
      ? candidate.expiresAt
      : null;
  const email = candidate.email ? String(candidate.email).trim() : null;
  return {
    accessToken,
    refreshToken,
    expiresAt,
    email,
  };
}

function emitAuthSessionChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(AUTH_SESSION_CHANGED_EVENT));
}

function readStoredAuthSession(): StoredAuthSession | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
  if (!raw) return null;
  try {
    return normalizeSession(JSON.parse(raw));
  } catch {
    return normalizeSession(raw);
  }
}

function writeStoredAuthSession(session: StoredAuthSession | null): void {
  if (typeof window === "undefined") return;
  if (!session) {
    window.localStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
    emitAuthSessionChanged();
    return;
  }
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(session));
  emitAuthSessionChanged();
}

function buildIdentityPlatformUrl(path: string): string {
  return `https://identitytoolkit.googleapis.com/v1/${path}?key=${encodeURIComponent(
    IDENTITY_PLATFORM_API_KEY,
  )}`;
}

function buildSecureTokenUrl(): string {
  return `https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(
    IDENTITY_PLATFORM_API_KEY,
  )}`;
}

function toExpiryTimestamp(expiresInSeconds: string | undefined): number | null {
  const seconds = Number.parseInt(String(expiresInSeconds ?? ""), 10);
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  return Date.now() + seconds * 1000;
}

function sessionNeedsRefresh(session: StoredAuthSession): boolean {
  if (!session.refreshToken || !session.expiresAt) return false;
  return session.expiresAt <= Date.now() + EXPIRY_SAFETY_WINDOW_MS;
}

async function postIdentityPlatformJson<T>(path: string, body: object): Promise<T> {
  const response = await fetch(buildIdentityPlatformUrl(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as T & { error?: { message?: string } };
  if (!response.ok || payload.error?.message) {
    throw new Error(payload.error?.message || `HTTP ${response.status}`);
  }
  return payload;
}

async function refreshIdentityPlatformSession(refreshToken: string): Promise<StoredAuthSession> {
  const response = await fetch(buildSecureTokenUrl(), {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
    }),
  });
  const payload = (await response.json()) as IdentityPlatformRefreshResponse;
  if (!response.ok || payload.error?.message || !payload.id_token) {
    throw new Error(payload.error?.message || `HTTP ${response.status}`);
  }
  return {
    accessToken: payload.id_token,
    refreshToken: payload.refresh_token?.trim() || refreshToken,
    expiresAt: toExpiryTimestamp(payload.expires_in),
  };
}

export function isIdentityPlatformConfigured(): boolean {
  return Boolean(IDENTITY_PLATFORM_API_KEY);
}

export function getStoredAccessTokenOrNull(): string | null {
  return readStoredAuthSession()?.accessToken ?? null;
}

export function setStoredAccessToken(token: string | null): void {
  const normalized = String(token ?? "").trim();
  writeStoredAuthSession(normalized ? { accessToken: normalized } : null);
}

export function clearStoredAuthSession(): void {
  writeStoredAuthSession(null);
}

export function subscribeAuthSessionChanged(listener: () => void): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }
  const handler = () => listener();
  window.addEventListener(AUTH_SESSION_CHANGED_EVENT, handler);
  return () => window.removeEventListener(AUTH_SESSION_CHANGED_EVENT, handler);
}

export async function getValidAccessTokenOrNull(): Promise<string | null> {
  const session = readStoredAuthSession();
  if (!session) return null;
  if (!sessionNeedsRefresh(session)) {
    return session.accessToken;
  }
  if (!session.refreshToken || !isIdentityPlatformConfigured()) {
    return session.accessToken;
  }
  if (!refreshInFlight) {
    refreshInFlight = refreshIdentityPlatformSession(session.refreshToken)
      .then((nextSession) => {
        writeStoredAuthSession(nextSession);
        return nextSession;
      })
      .catch((error) => {
        clearStoredAuthSession();
        throw error;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  const refreshedSession = await refreshInFlight;
  return refreshedSession?.accessToken ?? null;
}

export async function signInWithIdentityPlatformEmailPassword(
  email: string,
  password: string,
): Promise<void> {
  if (!isIdentityPlatformConfigured()) {
    throw new Error("Identity Platform API key is not configured.");
  }
  const payload = await postIdentityPlatformJson<IdentityPlatformSignInResponse>(
    "accounts:signInWithPassword",
    {
      email: email.trim(),
      password,
      returnSecureToken: true,
    },
  );
  if (!payload.idToken) {
    throw new Error("Identity Platform did not return an ID token.");
  }
  writeStoredAuthSession({
    accessToken: payload.idToken,
    refreshToken: payload.refreshToken?.trim() || null,
    expiresAt: toExpiryTimestamp(payload.expiresIn),
    email: payload.email?.trim() || email.trim(),
  });
}
