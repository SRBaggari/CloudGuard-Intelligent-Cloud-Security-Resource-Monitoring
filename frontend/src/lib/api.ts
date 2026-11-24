/** Typed fetch wrapper with JWT handling and transparent refresh-token rotation. */

const ACCESS_KEY = "cg-access";
const REFRESH_KEY = "cg-refresh";

// Tokens live in sessionStorage: they survive reloads but are cleared when the tab closes.
export const tokens = {
  get access() {
    return sessionStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    return sessionStorage.getItem(REFRESH_KEY);
  },
  set(access: string, refresh: string) {
    sessionStorage.setItem(ACCESS_KEY, access);
    sessionStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    sessionStorage.removeItem(ACCESS_KEY);
    sessionStorage.removeItem(REFRESH_KEY);
  },
};

export class ApiError extends Error {
  status: number;
  fieldErrors: { field: string; message: string }[];
  constructor(status: number, message: string, fieldErrors: { field: string; message: string }[] = []) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
  auth?: boolean;
  raw?: boolean;
  signal?: AbortSignal;
}

export function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const rt = tokens.refresh;
  if (!rt) return false;
  refreshing ??= (async () => {
    try {
      const r = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!r.ok) return false;
      const data = await r.json();
      tokens.set(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false;
    } finally {
      setTimeout(() => (refreshing = null), 0);
    }
  })();
  return refreshing;
}

function messageFrom(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  }
  return fallback;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, auth = true, raw = false, signal } = opts;
  const doFetch = () => {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (auth && tokens.access) headers["Authorization"] = `Bearer ${tokens.access}`;
    return fetch(buildUrl(path, query), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
  };

  let res: Response;
  try {
    res = await doFetch();
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "Cannot reach the CloudGuard API. Is the backend running?");
  }
  if (res.status === 401 && auth && tokens.refresh) {
    if (await refreshTokens()) res = await doFetch();
  }
  if (res.status === 401 && auth) {
    tokens.clear();
    window.dispatchEvent(new Event("cg:logout"));
  }
  if (!res.ok) {
    let data: unknown = null;
    try {
      data = await res.json();
    } catch {
      /* non-JSON error */
    }
    const fieldErrors =
      data && typeof data === "object" && "errors" in data ? ((data as { errors: never[] }).errors ?? []) : [];
    throw new ApiError(res.status, messageFrom(data, `Request failed (${res.status})`), fieldErrors);
  }
  if (raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Download an authenticated file (reports). */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const res = await api<Response>(path, { raw: true });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
