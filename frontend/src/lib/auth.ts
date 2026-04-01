const AUTH_SESSION_STORAGE_KEY = "materials.auth-session";
const LEGACY_ACCESS_TOKEN_STORAGE_KEY = "materials.access-token";
const AUTH_SESSION_CHANGED_EVENT = "materials:auth-session-changed";
const IDENTITY_PLATFORM_API_KEY = String(import.meta.env.VITE_IDENTITY_PLATFORM_API_KEY ?? "").trim();
const EXPIRY_SAFETY_WINDOW_MS = 60_000;

type StoredAuthSession = {
  accessToken: string;
  refreshToken?: string | null;
  expiresAt?: number | null;
  email?: string | null;
  emailVerified?: boolean | null;
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

type IdentityPlatformSignUpResponse = IdentityPlatformSignInResponse;

type IdentityPlatformOobCodeResponse = {
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
let refreshInFlightToken: string | null = null;

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
  const emailVerified =
    typeof candidate.emailVerified === "boolean" ? candidate.emailVerified : null;
  return {
    accessToken,
    refreshToken,
    expiresAt,
    email,
    emailVerified,
  };
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const segments = token.split(".");
  if (segments.length < 2) return null;
  try {
    const base64 = segments[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = `${base64}${"=".repeat((4 - (base64.length % 4)) % 4)}`;
    const decoded = atob(padded);
    return JSON.parse(decoded) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function deriveSessionMetadata(accessToken: string): Pick<StoredAuthSession, "email" | "emailVerified"> {
  const claims = decodeJwtPayload(accessToken);
  const email = claims && typeof claims.email === "string" ? claims.email.trim() : null;
  const emailVerified =
    claims && typeof claims.email_verified === "boolean" ? claims.email_verified : null;
  return { email, emailVerified };
}

function emitAuthSessionChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(AUTH_SESSION_CHANGED_EVENT));
}

function getPersistentStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

function getSessionStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage;
}

function clearLegacyStoredToken(): void {
  getPersistentStorage()?.removeItem(LEGACY_ACCESS_TOKEN_STORAGE_KEY);
  getSessionStorage()?.removeItem(LEGACY_ACCESS_TOKEN_STORAGE_KEY);
}

function readStoredAuthSession(): StoredAuthSession | null {
  const sessionStorage = getSessionStorage();
  const raw = sessionStorage?.getItem(AUTH_SESSION_STORAGE_KEY) ?? null;
  if (!raw) return null;
  try {
    return normalizeSession(JSON.parse(raw));
  } catch {
    return normalizeSession(raw);
  }
}

function migrateLegacyStoredTokenIfNeeded(): StoredAuthSession | null {
  const sessionStorage = getSessionStorage();
  const persistentStorage = getPersistentStorage();
  const legacyToken =
    sessionStorage?.getItem(LEGACY_ACCESS_TOKEN_STORAGE_KEY) ??
    persistentStorage?.getItem(LEGACY_ACCESS_TOKEN_STORAGE_KEY) ??
    null;
  const normalized = normalizeSession(legacyToken);
  if (!normalized) return null;
  if (sessionStorage) {
    sessionStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(normalized));
  }
  clearLegacyStoredToken();
  emitAuthSessionChanged();
  return normalized;
}

function writeStoredAuthSession(session: StoredAuthSession | null): void {
  const sessionStorage = getSessionStorage();
  const persistentStorage = getPersistentStorage();
  if (!sessionStorage && !persistentStorage) return;
  if (!session) {
    sessionStorage?.removeItem(AUTH_SESSION_STORAGE_KEY);
    clearLegacyStoredToken();
    refreshInFlight = null;
    refreshInFlightToken = null;
    emitAuthSessionChanged();
    return;
  }
  sessionStorage?.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(session));
  clearLegacyStoredToken();
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
    ...deriveSessionMetadata(payload.id_token),
  };
}

export function isIdentityPlatformConfigured(): boolean {
  return Boolean(IDENTITY_PLATFORM_API_KEY);
}

export function getStoredAccessTokenOrNull(): string | null {
  return (readStoredAuthSession() ?? migrateLegacyStoredTokenIfNeeded())?.accessToken ?? null;
}

export function getStoredAuthSessionSnapshot(): StoredAuthSession | null {
  return readStoredAuthSession() ?? migrateLegacyStoredTokenIfNeeded();
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
  const session = readStoredAuthSession() ?? migrateLegacyStoredTokenIfNeeded();
  if (!session) return null;
  if (!sessionNeedsRefresh(session)) {
    return session.accessToken;
  }
  if (!session.refreshToken || !isIdentityPlatformConfigured()) {
    return session.accessToken;
  }
  if (!refreshInFlight) {
    refreshInFlightToken = session.refreshToken;
    refreshInFlight = refreshIdentityPlatformSession(session.refreshToken)
      .then((nextSession) => {
        const currentSession = readStoredAuthSession();
        if (
          !currentSession ||
          !refreshInFlightToken ||
          currentSession.refreshToken !== refreshInFlightToken
        ) {
          return currentSession;
        }
        const mergedSession: StoredAuthSession = {
          ...currentSession,
          ...nextSession,
          email: nextSession.email ?? currentSession.email ?? null,
          emailVerified: nextSession.emailVerified ?? currentSession.emailVerified ?? null,
        };
        writeStoredAuthSession(mergedSession);
        return mergedSession;
      })
      .catch((error) => {
        const currentSession = readStoredAuthSession();
        if (currentSession?.refreshToken === refreshInFlightToken) {
          clearStoredAuthSession();
        }
        throw error;
      })
      .finally(() => {
        refreshInFlight = null;
        refreshInFlightToken = null;
      });
  }
  const refreshedSession = await refreshInFlight;
  return refreshedSession?.accessToken ?? null;
}

export async function refreshStoredAuthSessionNow(): Promise<string | null> {
  const session = readStoredAuthSession() ?? migrateLegacyStoredTokenIfNeeded();
  if (!session) return null;
  if (!session.refreshToken || !isIdentityPlatformConfigured()) {
    return session.accessToken;
  }
  const nextSession = await refreshIdentityPlatformSession(session.refreshToken);
  const mergedSession: StoredAuthSession = {
    ...session,
    ...nextSession,
    email: nextSession.email ?? session.email ?? null,
    emailVerified: nextSession.emailVerified ?? session.emailVerified ?? null,
  };
  writeStoredAuthSession(mergedSession);
  return mergedSession.accessToken;
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
  const sessionMeta = deriveSessionMetadata(payload.idToken);
  writeStoredAuthSession({
    accessToken: payload.idToken,
    refreshToken: payload.refreshToken?.trim() || null,
    expiresAt: toExpiryTimestamp(payload.expiresIn),
    email: payload.email?.trim() || sessionMeta.email || email.trim(),
    emailVerified: sessionMeta.emailVerified,
  });
}

export async function signUpWithIdentityPlatformEmailPassword(
  email: string,
  password: string,
): Promise<void> {
  if (!isIdentityPlatformConfigured()) {
    throw new Error("Identity Platform API key is not configured.");
  }
  const payload = await postIdentityPlatformJson<IdentityPlatformSignUpResponse>(
    "accounts:signUp",
    {
      email: email.trim(),
      password,
      returnSecureToken: true,
    },
  );
  if (!payload.idToken) {
    throw new Error("Identity Platform did not return an ID token.");
  }
  const derived = deriveSessionMetadata(payload.idToken);
  writeStoredAuthSession({
    accessToken: payload.idToken,
    refreshToken: payload.refreshToken?.trim() || null,
    expiresAt: toExpiryTimestamp(payload.expiresIn),
    email: payload.email?.trim() || derived.email || email.trim(),
    emailVerified: derived.emailVerified,
  });
}

export async function sendIdentityPlatformVerificationEmail(idToken?: string | null): Promise<void> {
  if (!isIdentityPlatformConfigured()) {
    throw new Error("Identity Platform API key is not configured.");
  }
  const effectiveIdToken = String(idToken ?? readStoredAuthSession()?.accessToken ?? "").trim();
  if (!effectiveIdToken) {
    throw new Error("Sign in before requesting a verification email.");
  }
  await postIdentityPlatformJson<IdentityPlatformOobCodeResponse>("accounts:sendOobCode", {
    requestType: "VERIFY_EMAIL",
    idToken: effectiveIdToken,
  });
}
