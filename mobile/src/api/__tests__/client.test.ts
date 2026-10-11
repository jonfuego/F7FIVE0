import { ApiClient, AuthError, NetworkError } from "../client";
import type { TokenStore } from "../tokenStore";

function memStore(initial: string | null = "refresh-0"): TokenStore & {
  value: string | null;
  clearCount: number;
} {
  let value = initial;
  let clearCount = 0;
  return {
    get value() {
      return value;
    },
    set value(v: string | null) {
      value = v;
    },
    get clearCount() {
      return clearCount;
    },
    async getRefresh() {
      return value;
    },
    async setRefresh(t: string) {
      value = t;
    },
    async clear() {
      clearCount += 1;
      value = null;
    },
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    async json() {
      return body;
    },
  } as unknown as Response;
}

const TOKENS = { access_token: "access-new", refresh_token: "refresh-new" };

describe("ApiClient single-flight refresh", () => {
  it("triggers exactly one refresh for concurrent 401s", async () => {
    const store = memStore();
    let refreshCalls = 0;
    const fetchImpl = jest.fn(async (url: string) => {
      if (url.endsWith("/api/auth/refresh")) {
        refreshCalls += 1;
        // simulate latency so all three requests are in-flight together
        await new Promise((r) => setTimeout(r, 5));
        return jsonResponse(200, TOKENS);
      }
      // First hit 401 (no token yet), then 200 after refresh sets the token.
      return jsonResponse(refreshCalls === 0 ? 401 : 200, { ok: true });
    }) as unknown as typeof fetch;

    const client = new ApiClient({ baseUrl: "http://x", tokenStore: store, fetchImpl });
    const [a, b, c] = await Promise.all([
      client.request("/api/library/songs"),
      client.request("/api/library/albums"),
      client.request("/api/library/artists"),
    ]);
    expect(a.status).toBe(200);
    expect(b.status).toBe(200);
    expect(c.status).toBe(200);
    expect(refreshCalls).toBe(1);
    expect(store.value).toBe("refresh-new");
  });
});

describe("ApiClient never logs out on network errors", () => {
  it("propagates a NetworkError from the request without clearing the session", async () => {
    const store = memStore();
    let loggedOut = false;
    const fetchImpl = jest.fn(async () => {
      throw new Error("ECONNRESET");
    }) as unknown as typeof fetch;
    const client = new ApiClient({
      baseUrl: "http://x",
      tokenStore: store,
      fetchImpl,
      sleepImpl: async () => {},
      onLogout: () => {
        loggedOut = true;
      },
    });
    await expect(client.request("/api/library/songs")).rejects.toBeInstanceOf(NetworkError);
    expect(loggedOut).toBe(false);
    expect(store.clearCount).toBe(0);
    expect(store.value).toBe("refresh-0");
  });

  it("keeps the session when the refresh call itself hits a network error", async () => {
    const store = memStore();
    let loggedOut = false;
    const fetchImpl = jest.fn(async (url: string) => {
      if (url.endsWith("/api/auth/refresh")) throw new Error("offline");
      return jsonResponse(401, {});
    }) as unknown as typeof fetch;
    const client = new ApiClient({
      baseUrl: "http://x",
      tokenStore: store,
      fetchImpl,
      sleepImpl: async () => {},
      onLogout: () => {
        loggedOut = true;
      },
    });
    await expect(client.request("/api/library/songs")).rejects.toBeInstanceOf(NetworkError);
    expect(loggedOut).toBe(false);
    expect(store.clearCount).toBe(0);
  });
});

describe("ApiClient logs out only on a definitive refresh failure", () => {
  it("clears the session and calls onLogout when refresh returns 401", async () => {
    const store = memStore();
    let loggedOut = false;
    const fetchImpl = jest.fn(async (url: string) => {
      if (url.endsWith("/api/auth/refresh")) return jsonResponse(401, { detail: "refresh_token_revoked" });
      return jsonResponse(401, {});
    }) as unknown as typeof fetch;
    const client = new ApiClient({
      baseUrl: "http://x",
      tokenStore: store,
      fetchImpl,
      onLogout: () => {
        loggedOut = true;
      },
    });
    await expect(client.request("/api/library/songs")).rejects.toBeInstanceOf(AuthError);
    expect(loggedOut).toBe(true);
    expect(store.clearCount).toBe(1);
    expect(store.value).toBeNull();
  });

  it("does not log out on a transient 500 from refresh", async () => {
    const store = memStore();
    let loggedOut = false;
    const fetchImpl = jest.fn(async (url: string) => {
      if (url.endsWith("/api/auth/refresh")) return jsonResponse(500, {});
      return jsonResponse(401, {});
    }) as unknown as typeof fetch;
    const client = new ApiClient({
      baseUrl: "http://x",
      tokenStore: store,
      fetchImpl,
      sleepImpl: async () => {},
      onLogout: () => {
        loggedOut = true;
      },
    });
    await expect(client.request("/api/library/songs")).rejects.toBeInstanceOf(NetworkError);
    expect(loggedOut).toBe(false);
    expect(store.clearCount).toBe(0);
  });
});

describe("ApiClient refresh outage handling", () => {
  function setup(refreshAnswer: (n: number) => Response | Promise<Response>) {
    const store = memStore();
    const slept: number[] = [];
    let refreshCalls = 0;
    let loggedOut = false;
    const fetchImpl = jest.fn(async (url: string) => {
      if (url.endsWith("/api/auth/refresh")) {
        refreshCalls += 1;
        return refreshAnswer(refreshCalls);
      }
      return jsonResponse(refreshCalls === 0 ? 401 : 200, { ok: true });
    }) as unknown as typeof fetch;
    const client = new ApiClient({
      baseUrl: "http://x",
      tokenStore: store,
      fetchImpl,
      sleepImpl: async (ms) => {
        slept.push(ms);
      },
      onLogout: () => {
        loggedOut = true;
      },
    });
    return {
      client,
      store,
      slept,
      get refreshCalls() {
        return refreshCalls;
      },
      get loggedOut() {
        return loggedOut;
      },
    };
  }

  it.each([500, 502, 503, 504])(
    "a %i from refresh retries twice (0.5 s, 1.5 s), then keeps the session",
    async (status) => {
      const t = setup(() => jsonResponse(status, {}));
      await expect(t.client.request("/api/library/songs")).rejects.toBeInstanceOf(NetworkError);
      expect(t.refreshCalls).toBe(3);
      expect(t.slept).toEqual([500, 1500]);
      expect(t.loggedOut).toBe(false);
      expect(t.store.clearCount).toBe(0);
      expect(t.store.value).toBe("refresh-0");
    },
  );

  it("a dropped connection retries twice, then keeps the session", async () => {
    const t = setup(() => {
      throw new TypeError("Network request failed");
    });
    await expect(t.client.request("/api/library/songs")).rejects.toBeInstanceOf(NetworkError);
    expect(t.refreshCalls).toBe(3);
    expect(t.loggedOut).toBe(false);
    expect(t.store.clearCount).toBe(0);
  });

  it("a timed-out refresh (aborted) is treated as try again, not sign-out", async () => {
    const t = setup(() => {
      const e = new Error("aborted");
      e.name = "AbortError";
      throw e;
    });
    await expect(t.client.request("/api/library/songs")).rejects.toBeInstanceOf(NetworkError);
    expect(t.loggedOut).toBe(false);
    expect(t.store.clearCount).toBe(0);
  });

  it("a 503 then a 200 refreshes after one retry and the request succeeds", async () => {
    const t = setup((n) => (n === 1 ? jsonResponse(503, {}) : jsonResponse(200, TOKENS)));
    const res = await t.client.request("/api/library/songs");
    expect(res.status).toBe(200);
    expect(t.refreshCalls).toBe(2);
    expect(t.slept).toEqual([500]);
    expect(t.store.value).toBe("refresh-new");
    expect(t.loggedOut).toBe(false);
  });

  it("a 401 signs out at once, with no retry", async () => {
    const t = setup(() => jsonResponse(401, { detail: "refresh_token_revoked" }));
    await expect(t.client.request("/api/library/songs")).rejects.toBeInstanceOf(AuthError);
    expect(t.refreshCalls).toBe(1);
    expect(t.slept).toEqual([]);
    expect(t.loggedOut).toBe(true);
    expect(t.store.clearCount).toBe(1);
  });

  it("a 403 from refresh no longer signs out (a proxy answer, not a dead token)", async () => {
    const t = setup(() => jsonResponse(403, {}));
    await expect(t.client.request("/api/library/songs")).rejects.toBeInstanceOf(NetworkError);
    expect(t.refreshCalls).toBe(1);
    expect(t.loggedOut).toBe(false);
    expect(t.store.clearCount).toBe(0);
  });

  it("concurrent requests still share one retrying refresh", async () => {
    const t = setup((n) => (n === 1 ? jsonResponse(502, {}) : jsonResponse(200, TOKENS)));
    const results = await Promise.all([
      t.client.request("/api/a"),
      t.client.request("/api/b"),
      t.client.request("/api/c"),
    ]);
    expect(results.map((r) => r.status)).toEqual([200, 200, 200]);
    expect(t.refreshCalls).toBe(2);
  });

  it("bootstrap at launch with the server down is not a sign-out", async () => {
    const t = setup(() => jsonResponse(503, {}));
    await expect(t.client.bootstrap()).rejects.toBeInstanceOf(NetworkError);
    expect(t.loggedOut).toBe(false);
    expect(t.store.value).toBe("refresh-0");
  });
});

describe("adoptSession", () => {
  it("stores the refresh token and uses the access token on the next call", async () => {
    const store = memStore(null);
    const seen: (string | null)[] = [];
    const fetchImpl = jest.fn(async (_url: string, init?: RequestInit) => {
      seen.push(new Headers(init?.headers).get("authorization"));
      return jsonResponse(200, { ok: true });
    });
    const api = new ApiClient({
      baseUrl: "https://media.example.com",
      tokenStore: store,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    } as unknown as ConstructorParameters<typeof ApiClient>[0]);
    await api.adoptSession({ access_token: "acc-1", refresh_token: "ref-1" });
    expect(store.value).toBe("ref-1");
    await api.json("/api/auth/me");
    expect(seen[0]).toBe("Bearer acc-1");
  });
});
