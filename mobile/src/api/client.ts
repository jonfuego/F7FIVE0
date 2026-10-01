/** Typed API client with single-flight refresh.
 *
 * Rules (spec M4):
 *  - The access token is kept in memory only; the refresh token lives only in
 *    the injected TokenStore (SecureStore in the app).
 *  - Concurrent 401s trigger exactly ONE refresh (single-flight); all waiters
 *    share the same in-flight refresh promise.
 *  - Network errors never clear the session (they throw NetworkError).
 *  - Only a definitive 401/403 from the refresh call (or a missing refresh
 *    token) signs the user out (clears the store, calls onLogout, throws
 *    AuthError).
 *
 * Everything is dependency-injected (fetch, tokenStore, onLogout) so the whole
 * module unit-tests in Node with no native modules.
 */
import type { TokenStore } from "./tokenStore";

export class NetworkError extends Error {
  constructor(message = "network_error", readonly cause?: unknown) {
    super(message);
    this.name = "NetworkError";
  }
}

export class AuthError extends Error {
  constructor(message = "auth_error") {
    super(message);
    this.name = "AuthError";
  }
}

export class ApiError extends Error {
  constructor(readonly status: number, message: string, readonly body?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ClientMeta {
  device_name?: string;
  platform?: string;
  client_version?: string;
}

export interface ApiClientDeps {
  /** A fixed origin, or a getter so the server can change at runtime. */
  baseUrl: string | (() => string);
  tokenStore: TokenStore;
  fetchImpl?: typeof fetch;
  onLogout?: () => void;
  clientMeta?: ClientMeta;
}

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

export class ApiClient {
  private accessToken: string | null = null;
  private refreshPromise: Promise<string> | null = null;
  private readonly baseUrlSource: string | (() => string);
  private readonly store: TokenStore;
  private readonly fetchImpl: typeof fetch;
  private readonly onLogout?: () => void;
  private readonly meta: ClientMeta;

  constructor(deps: ApiClientDeps) {
    this.baseUrlSource = deps.baseUrl;
    this.store = deps.tokenStore;
    this.fetchImpl = deps.fetchImpl ?? fetch;
    this.onLogout = deps.onLogout;
    this.meta = deps.clientMeta ?? {};
  }

  private get baseUrl(): string {
    const v = typeof this.baseUrlSource === "function" ? this.baseUrlSource() : this.baseUrlSource;
    return v.replace(/\/+$/, "");
  }

  hasSession(): boolean {
    return this.accessToken !== null;
  }

  /** Public auth header for authenticated media loads (e.g. <Image> headers on
   * /api/art/*). Empty when signed out. */
  authHeaders(): Record<string, string> {
    return this.authHeader();
  }

  baseUrlValue(): string {
    return this.baseUrl;
  }

  /** Adopt a refresh token already in the store (app launch): try one refresh
   * so we start with a valid access token. A network failure here is not a
   * logout; it just means we start offline and retry lazily. */
  async bootstrap(): Promise<boolean> {
    const refresh = await this.store.getRefresh();
    if (!refresh) return false;
    try {
      await this.refreshAccess();
      return true;
    } catch (e) {
      if (e instanceof AuthError) return false;
      // NetworkError: keep the (still-valid) refresh token; caller can retry.
      throw e;
    }
  }

  async login(username: string, password: string): Promise<void> {
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}/api/auth/login`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          username,
          password,
          client_type: "native",
          device_name: this.meta.device_name,
          platform: this.meta.platform,
          client_version: this.meta.client_version,
        }),
      });
    } catch (e) {
      throw new NetworkError("login_network_error", e);
    }
    if (res.status === 401) {
      throw new ApiError(401, "invalid_credentials");
    }
    if (!res.ok) {
      throw new ApiError(res.status, `login_failed_${res.status}`);
    }
    const body = (await res.json()) as TokenPair;
    this.accessToken = body.access_token;
    await this.store.setRefresh(body.refresh_token);
  }

  /** Adopt an already-issued token pair (e.g. from a passkey login performed
   * outside this client, which needs a native module the client stays free of).
   * Same effect as login(): access token in memory, refresh token in the store. */
  async adoptSession(pair: { access_token: string; refresh_token: string }): Promise<void> {
    this.accessToken = pair.access_token;
    await this.store.setRefresh(pair.refresh_token);
  }

  async logout(): Promise<void> {
    const refresh = await this.store.getRefresh();
    if (refresh) {
      try {
        await this.fetchImpl(`${this.baseUrl}/api/auth/logout`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            ...this.authHeader(),
          },
          body: JSON.stringify({ refresh_token: refresh }),
        });
      } catch {
        // Best effort; local clear happens regardless.
      }
    }
    await this.clearSession();
  }

  private authHeader(): Record<string, string> {
    return this.accessToken ? { authorization: `Bearer ${this.accessToken}` } : {};
  }

  private async clearSession(): Promise<void> {
    this.accessToken = null;
    await this.store.clear();
  }

  /** Single-flight refresh. All concurrent callers await the same promise. */
  private refreshAccess(): Promise<string> {
    if (!this.refreshPromise) {
      this.refreshPromise = this.doRefresh().finally(() => {
        this.refreshPromise = null;
      });
    }
    return this.refreshPromise;
  }

  private async doRefresh(): Promise<string> {
    const refresh = await this.store.getRefresh();
    if (!refresh) {
      // No refresh token at all -> definitive: send to login.
      await this.clearSession();
      this.onLogout?.();
      throw new AuthError("no_refresh_token");
    }
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}/api/auth/refresh`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
    } catch (e) {
      // Network failure: DO NOT clear the session; caller retries later.
      throw new NetworkError("refresh_network_error", e);
    }
    if (res.status === 401 || res.status === 403) {
      // Definitive auth failure: the refresh token is dead. Sign out.
      await this.clearSession();
      this.onLogout?.();
      throw new AuthError("refresh_rejected");
    }
    if (!res.ok) {
      // 5xx / transient: treat as network-ish, keep the session.
      throw new NetworkError(`refresh_failed_${res.status}`);
    }
    const body = (await res.json()) as TokenPair;
    this.accessToken = body.access_token;
    await this.store.setRefresh(body.refresh_token);
    return this.accessToken;
  }

  /** Authenticated fetch. On a 401 it refreshes once (single-flight) and
   * retries the request exactly once. */
  async request(path: string, init: RequestInit = {}): Promise<Response> {
    const url = path.startsWith("http") ? path : `${this.baseUrl}${path}`;
    let res: Response;
    try {
      res = await this.fetchImpl(url, this.withAuth(init));
    } catch (e) {
      throw new NetworkError("request_network_error", e);
    }
    if (res.status !== 401) return res;

    // 401 -> refresh (shared) then retry once.
    await this.refreshAccess();
    try {
      return await this.fetchImpl(url, this.withAuth(init));
    } catch (e) {
      throw new NetworkError("retry_network_error", e);
    }
  }

  /** JSON convenience wrapper. Throws ApiError on non-2xx. */
  async json<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await this.request(path, init);
    if (!res.ok) {
      let body: unknown;
      try {
        body = await res.json();
      } catch {
        body = undefined;
      }
      throw new ApiError(res.status, `request_failed_${res.status}`, body);
    }
    return (await res.json()) as T;
  }

  private withAuth(init: RequestInit): RequestInit {
    return {
      ...init,
      headers: {
        ...(init.headers ?? {}),
        ...this.authHeader(),
      },
    };
  }
}

export function createApiClient(deps: ApiClientDeps): ApiClient {
  return new ApiClient(deps);
}
