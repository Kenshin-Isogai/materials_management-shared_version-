import type { ApiResponse } from "./types";

const API_BASE = String(import.meta.env.VITE_API_BASE ?? "/api").trim() || "/api";
const USERNAME_STORAGE_KEY = "materials.username";
const USERS_CHANGED_EVENT = "materials:users-changed";

function toAbsolutePath(path: string): string {
  if (path.startsWith("/")) return path;
  return `/${path}`;
}

function getStoredUsername(): string | null {
  if (typeof window === "undefined") return null;
  const value = window.localStorage.getItem(USERNAME_STORAGE_KEY);
  return value && value.trim() ? value.trim() : null;
}

export function setStoredUsername(username: string | null): void {
  if (typeof window === "undefined") return;
  if (username && username.trim()) {
    window.localStorage.setItem(USERNAME_STORAGE_KEY, username.trim());
    return;
  }
  window.localStorage.removeItem(USERNAME_STORAGE_KEY);
}

export function getStoredUsernameOrNull(): string | null {
  return getStoredUsername();
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

function buildHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers ?? {});
  const username = getStoredUsername();
  if (isMutationMethod(init?.method)) {
    if (!username) {
      throw new Error("Select a user before performing changes.");
    }
    headers.set("X-User-Name", username);
  }
  return headers;
}

async function fetchApi(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${toAbsolutePath(path)}`, {
    ...init,
    headers: buildHeaders(init),
  });
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
    throw new Error(
      payload.status === "error" ? payload.error.message : `HTTP ${res.status}`
    );
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
    throw new Error(
      payload.status === "error" ? payload.error.message : `HTTP ${res.status}`
    );
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
  init?: RequestInit
): Promise<T> {
  const headers = buildHeaders({ ...init, method: init?.method ?? "POST" });
  headers.set("Content-Type", "application/json");
  const res = await fetch(`${API_BASE}${toAbsolutePath(path)}`, {
    ...init,
    method: init?.method ?? "POST",
    headers,
  });
  const payload = await parseJson<T>(res);
  if (!res.ok || payload.status === "error") {
    throw new Error(
      payload.status === "error" ? payload.error.message : `HTTP ${res.status}`
    );
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
    throw new Error(
      payload.status === "error" ? payload.error.message : `HTTP ${res.status}`
    );
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
      throw new Error(
        payload.status === "error" ? payload.error.message : `HTTP ${res.status}`
      );
    }
    throw new Error((await res.text()) || `HTTP ${res.status}`);
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
