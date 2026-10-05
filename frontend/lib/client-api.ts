// Browser-side fetch wrapper with transparent refresh.
//
// All authenticated data fetches from client components should go through
// apiGet / apiPost so that a single expired access token triggers exactly
// one /api/session/refresh round-trip and the caller never sees the 401.
//
// If refresh fails, the user is bounced to /login and the promise never
// resolves (we replace the whole location).

"use client";

export class ApiError extends Error {
  status: number;
  detail: string | null;
  constructor(status: number, detail: string | null, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

type Options = {
  signal?: AbortSignal;
  body?: unknown;
  method?: string;
};

// Single-flight session refresh. When the access token expires, several
// requests get a 401 at the same moment (Admin alone polls on four timers).
// Without a shared lock each 401 refreshed on its own: the first rotated the
// token, the second used the grace window, and the rest presented a revoked
// token, which the API treats as reuse and kills the session. Here every 401
// awaits one shared in-flight refresh promise, so the token rotates once.
let inFlightRefresh: Promise<boolean> | null = null;

export function refreshSession(): Promise<boolean> {
  if (!inFlightRefresh) {
    inFlightRefresh = fetch("/api/session/refresh", { method: "POST" })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => {
        inFlightRefresh = null;
      });
  }
  return inFlightRefresh;
}

export async function apiGet<T>(path: string, opts: Options = {}): Promise<T> {
  return request<T>(path, { ...opts, method: "GET" });
}

export async function apiPost<T>(path: string, body: unknown, opts: Options = {}): Promise<T> {
  return request<T>(path, { ...opts, method: "POST", body });
}

export async function apiPut<T>(path: string, body: unknown, opts: Options = {}): Promise<T> {
  return request<T>(path, { ...opts, method: "PUT", body });
}

export async function apiPatch<T>(path: string, body: unknown, opts: Options = {}): Promise<T> {
  return request<T>(path, { ...opts, method: "PATCH", body });
}

export async function apiDelete<T = void>(path: string, opts: Options = {}): Promise<T> {
  return request<T>(path, { ...opts, method: "DELETE" });
}

async function request<T>(path: string, opts: Options): Promise<T> {
  const first = await doFetch(path, opts);
  if (first.status !== 401) return handle<T>(first);

  // One refresh attempt shared across every concurrent 401, then retry the
  // original call exactly once. A second 401 after refresh means the refresh
  // cookie is dead.
  const refreshed = await refreshSession();
  if (!refreshed) {
    redirectToLogin();
    return new Promise<T>(() => {}); // never resolves; navigation is underway
  }
  const retry = await doFetch(path, opts);
  if (retry.status === 401) {
    redirectToLogin();
    return new Promise<T>(() => {});
  }
  return handle<T>(retry);
}

function redirectToLogin(): void {
  const here = window.location.pathname + window.location.search;
  const next = here && !here.startsWith("/login") ? here : "/";
  // Stop the persistent dock audio before navigating; otherwise mobile
  // browsers keep buffering the current track through the route change.
  try {
    const audio = document.getElementById("mh-dock-audio") as HTMLAudioElement | null;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    if ("mediaSession" in navigator) {
      navigator.mediaSession.metadata = null;
      navigator.mediaSession.playbackState = "none";
    }
  } catch {
    // SSR or unsupported browser; teardown is best-effort.
  }
  window.location.replace(`/login?next=${encodeURIComponent(next)}`);
}

function doFetch(path: string, opts: Options): Promise<Response> {
  const headers: Record<string, string> = {};
  let body: string | undefined;
  if (opts.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  return fetch(path, {
    method: opts.method ?? "GET",
    headers,
    body,
    signal: opts.signal,
    cache: "no-store",
  });
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) {
    // 204 No Content lands here too; give the caller `undefined as T`.
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }
  const payload = await safeJson(res);
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? String((payload as { detail?: unknown }).detail ?? "")
      : null;
  throw new ApiError(res.status, detail, `HTTP ${res.status}${detail ? `: ${detail}` : ""}`);
}

async function safeJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}
