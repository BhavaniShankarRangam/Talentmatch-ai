// Thin fetch wrapper. The access token lives in sessionStorage (cleared when the tab closes).
const TOKEN_KEY = "tm_token";

export class ApiError extends Error {
  status: number;
  errors: string[];
  body: unknown;
  constructor(status: number, message: string, errors: string[] = [], body: unknown = null) {
    super(message);
    this.status = status;
    this.errors = errors;
    this.body = body;
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token stays in memory only via reload-less session */
  }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function parseError(status: number, body: any): ApiError {
  const detail = body?.detail;
  if (typeof detail === "string") return new ApiError(status, detail, [], body);
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    return new ApiError(status, detail.message ?? "Request failed", detail.errors ?? [], body);
  }
  if (Array.isArray(detail)) {
    const errs = detail.map((d: any) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`);
    return new ApiError(status, "Validation error", errs, body);
  }
  return new ApiError(status, `Request failed (${status})`, [], body);
}

export async function api<T = any>(
  path: string,
  opts: { method?: string; body?: unknown; form?: FormData; headers?: Record<string, string>; raw?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(`/api${path}`, { method: opts.method ?? (body ? "POST" : "GET"), headers, body });
  if (res.status === 401 && token) onUnauthorized();
  if (!res.ok) {
    let parsed: unknown = null;
    try {
      parsed = await res.json();
    } catch {
      /* non-JSON error */
    }
    throw parseError(res.status, parsed);
  }
  if (opts.raw) return res as unknown as T;
  return (await res.json()) as T;
}

/** Fetch an authenticated binary (resume, CSV) and open/save it without exposing the token in a URL. */
export async function openAuthenticatedFile(path: string, filename?: string) {
  const res = await api<Response>(path, { raw: true });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  if (filename) {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  } else {
    window.open(url, "_blank", "noopener");
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}
