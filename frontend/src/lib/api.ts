import {
  getStoredAccessTokenOrNull as getStoredAccessTokenOrNullFromAuth,
  getValidAccessTokenOrNull,
  setStoredAccessToken as setStoredAccessTokenInAuth,
} from "./auth";
import { ApiClientError, type ApiResponse } from "./types";

function normalizeApiBase(value: unknown): string {
  const raw = String(value ?? "/api").trim() || "/api";
  if (raw === "/") return "";
  return raw.endsWith("/") ? raw.slice(0, -1) : raw;
}

const API_BASE = normalizeApiBase(import.meta.env.VITE_API_BASE);
const USERS_CHANGED_EVENT = "materials:users-changed";

function toAbsolutePath(path: string): string {
  if (path.startsWith("/")) return path;
  return `/${path}`;
}

function buildApiUrl(path: string): string {
  return `${API_BASE}${toAbsolutePath(path)}`;
}

export function setStoredAccessToken(token: string | null): void {
  setStoredAccessTokenInAuth(token);
}

export function getStoredAccessTokenOrNull(): string | null {
  return getStoredAccessTokenOrNullFromAuth();
}

export function notifyUsersChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(USERS_CHANGED_EVENT));
}

export function subscribeUsersChanged(listener: () => void): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }
  const handler = () => listener();
  window.addEventListener(USERS_CHANGED_EVENT, handler);
  return () => window.removeEventListener(USERS_CHANGED_EVENT, handler);
}

function isMutationMethod(method: string | undefined): boolean {
  const normalized = String(method ?? "GET").toUpperCase();
  return !["GET", "HEAD", "OPTIONS"].includes(normalized);
}

type BuildHeadersOptions = {
  allowAnonymousMutation?: boolean;
};

async function buildHeaders(init?: RequestInit, options?: BuildHeadersOptions): Promise<Headers> {
  const headers = new Headers(init?.headers ?? {});
  let accessToken: string | null = null;
  try {
    accessToken = await getValidAccessTokenOrNull();
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error;
    }
    throw new ApiClientError({
      message: "Sign in again to continue.",
      statusCode: 401,
      code: "INVALID_TOKEN",
      details: error,
    });
  }
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  if (isMutationMethod(init?.method)) {
    if (!accessToken && !options?.allowAnonymousMutation) {
      throw new ApiClientError({
        message: "Set an access token before performing changes.",
        statusCode: 401,
        code: "AUTH_REQUIRED",
      });
    }
  }
  return headers;
}

async function fetchApi(path: string, init?: RequestInit): Promise<Response> {
  const headers = await buildHeaders(init);
  try {
    return await fetch(buildApiUrl(path), {
      ...init,
      headers,
    });
  } catch (error) {
    throw new ApiClientError({
      message: "Could not reach the backend service.",
      isNetworkError: true,
      details: error,
    });
  }
}

async function performFetch(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(buildApiUrl(path), init);
  } catch (error) {
    throw new ApiClientError({
      message: "Could not reach the backend service.",
      isNetworkError: true,
      details: error,
    });
  }
}

function extractFilename(
  contentDisposition: string | null,
  fallbackFilename: string
): string {
  if (!contentDisposition) return fallbackFilename;
  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
  return filenameMatch?.[1] ?? fallbackFilename;
}

async function parseJson<T>(res: Response): Promise<ApiResponse<T>> {
  const text = await res.text();
  try {
    return JSON.parse(text) as ApiResponse<T>;
  } catch {
    throw new Error(text || `HTTP ${res.status}`);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetchApi(path);
  const payload = await parseJson<T>(res);
  if (!res.ok || payload.status === "error") {
    throw new ApiClientError({
      message: payload.status === "error" ? payload.error.message : `HTTP ${res.status}`,
      statusCode: res.status,
      code: payload.status === "error" ? payload.error.code : null,
      details: payload.status === "error" ? payload.error.details : null,
    });
  }
  return payload.data;
}

export async function apiGetWithPagination<T>(path: string): Promise<{
  data: T;
  pagination?: {
    page: number;
    per_page: number;
    total: number;
    total_pages: number;
  };
}> {
  const res = await fetchApi(path);
  const payload = await parseJson<T>(res);
  if (!res.ok || payload.status === "error") {
    throw new ApiClientError({
      message: payload.status === "error" ? payload.error.message : `HTTP ${res.status}`,
      statusCode: res.status,
      code: payload.status === "error" ? payload.error.code : null,
      details: payload.status === "error" ? payload.error.details : null,
    });
  }
  return { data: payload.data, pagination: payload.pagination };
}

export async function apiGetAllPages<T>(path: string): Promise<T[]> {
  const url = new URL(toAbsolutePath(path), "http://local.api");
  if (!url.searchParams.has("per_page")) {
    url.searchParams.set("per_page", "500");
  }

  const allRows: T[] = [];
  let page = 1;

  while (true) {
    url.searchParams.set("page", String(page));
    const requestPath = `${url.pathname}${url.search}`;
    const response = await apiGetWithPagination<T[]>(requestPath);
    allRows.push(...response.data);

    const pagination = response.pagination;
    if (!pagination || pagination.total_pages <= page) {
      break;
    }
    page += 1;
  }

  return allRows;
}

export async function apiSend<T>(
  path: string,
  init?: RequestInit,
  options?: BuildHeadersOptions
): Promise<T> {
  const headers = await buildHeaders({ ...init, method: init?.method ?? "POST" }, options);
  headers.set("Content-Type", "application/json");
  const res = await performFetch(path, {
    ...init,
    method: init?.method ?? "POST",
    headers,
  });
  const payload = await parseJson<T>(res);
  if (!res.ok || payload.status === "error") {
    throw new ApiClientError({
      message: payload.status === "error" ? payload.error.message : `HTTP ${res.status}`,
      statusCode: res.status,
      code: payload.status === "error" ? payload.error.code : null,
      details: payload.status === "error" ? payload.error.details : null,
    });
  }
  return payload.data;
}

export async function apiSendForm<T>(
  path: string,
  formData: FormData
): Promise<T> {
  const res = await fetchApi(path, { method: "POST", body: formData });
  const payload = await parseJson<T>(res);
  if (!res.ok || payload.status === "error") {
    throw new ApiClientError({
      message: payload.status === "error" ? payload.error.message : `HTTP ${res.status}`,
      statusCode: res.status,
      code: payload.status === "error" ? payload.error.code : null,
      details: payload.status === "error" ? payload.error.details : null,
    });
  }
  return payload.data;
}

export async function apiDownload(
  path: string,
  fallbackFilename: string,
  init?: RequestInit
): Promise<void> {
  const res = await fetchApi(path, init);
  if (!res.ok) {
    const contentType = res.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const payload = await parseJson<unknown>(res);
      throw new ApiClientError({
        message: payload.status === "error" ? payload.error.message : `HTTP ${res.status}`,
        statusCode: res.status,
        code: payload.status === "error" ? payload.error.code : null,
        details: payload.status === "error" ? payload.error.details : null,
      });
    }
    throw new ApiClientError({
      message: (await res.text()) || `HTTP ${res.status}`,
      statusCode: res.status,
    });
  }

  const blob = await res.blob();
  const filename = extractFilename(res.headers.get("content-disposition"), fallbackFilename);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
