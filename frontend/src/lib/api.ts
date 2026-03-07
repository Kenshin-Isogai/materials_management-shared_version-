import type { ApiResponse } from "./types";

const configuredApiBase = String(import.meta.env.VITE_API_BASE ?? "").trim();
const defaultHost =
  typeof window !== "undefined" && window.location.hostname
    ? window.location.hostname
    : "127.0.0.1";
const fallbackApiBases = [8000, 8001, 8010, 18000].map(
  (port) => `http://${defaultHost}:${port}/api`
);
let lastWorkingApiBase: string | null = configuredApiBase || null;
let probingPromise: Promise<string> | null = null;

function toAbsolutePath(path: string): string {
  if (path.startsWith("/")) return path;
  return `/${path}`;
}

function candidateApiBases(): string[] {
  if (configuredApiBase) return [configuredApiBase];
  const bases = [lastWorkingApiBase, ...fallbackApiBases].filter(Boolean) as string[];
  return Array.from(new Set(bases));
}

async function resolveApiBase(): Promise<string> {
  if (configuredApiBase) return configuredApiBase;
  if (lastWorkingApiBase) return lastWorkingApiBase;
  if (!probingPromise) {
    probingPromise = (async () => {
      for (const base of fallbackApiBases) {
        try {
          const response = await fetch(`${base}/health`);
          if (!response.ok) continue;
          const payload = (await response.json()) as { status?: string };
          if (payload.status === "ok") {
            lastWorkingApiBase = base;
            return base;
          }
        } catch {
          continue;
        }
      }
      return fallbackApiBases[0];
    })();
  }
  const resolved = await probingPromise;
  lastWorkingApiBase = resolved;
  return resolved;
}

async function fetchApi(path: string, init?: RequestInit): Promise<Response> {
  const normalizedPath = toAbsolutePath(path);
  await resolveApiBase();
  const bases = candidateApiBases();
  let lastError: unknown = null;

  for (const base of bases) {
    try {
      const response = await fetch(`${base}${normalizedPath}`, init);
      lastWorkingApiBase = base;
      return response;
    } catch (error) {
      lastError = error;
    }
  }

  const attempted = bases.join(", ");
  throw new Error(
    `Failed to fetch backend API. Tried: ${attempted}. ${String(lastError ?? "")}`.trim()
  );
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
  const res = await fetchApi(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
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

export async function apiDownload(path: string, fallbackFilename: string): Promise<void> {
  const res = await fetchApi(path);
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
