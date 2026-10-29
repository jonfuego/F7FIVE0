// node:test coverage for the single-flight session refresh.
//
// Run: node --test frontend/lib/client-api.test.ts
//
// When many requests get a 401 at the same moment, they must share one
// /api/session/refresh round-trip. Without that, the second refresh uses the
// grace window and the rest trip reuse detection and the session dies.

import { test } from "node:test";
import assert from "node:assert/strict";
import { ApiError, apiDelete, apiGet, apiPost, refreshSession } from "./client-api.ts";

// Minimal Response-returning fetch stub. The data paths 401 once, then 200
// after the shared refresh; the refresh path counts its calls and stalls
// briefly so every 401 piles up behind the same in-flight promise.
function installFetchStub() {
  let refreshCalls = 0;
  const seen = new Map<string, number>();
  const origFetch = globalThis.fetch;
  globalThis.fetch = (async (input: unknown, init?: unknown) => {
    const url = String(input);
    if (url === "/api/session/refresh") {
      refreshCalls += 1;
      await new Promise((r) => setTimeout(r, 25));
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }
    const hit = (seen.get(url) ?? 0) + 1;
    seen.set(url, hit);
    if (hit === 1) return new Response(null, { status: 401 });
    return new Response(JSON.stringify({ url }), { status: 200 });
  }) as typeof fetch;
  return {
    get refreshCalls() {
      return refreshCalls;
    },
    restore() {
      globalThis.fetch = origFetch;
    },
  };
}

test("six concurrent 401s trigger exactly one refresh", async () => {
  const stub = installFetchStub();
  try {
    const paths = [
      "/api/library/sections",
      "/api/library/continue",
      "/api/library/recent",
      "/api/admin/audio/progress",
      "/api/admin/transcodes",
      "/api/session/me",
    ];
    const results = await Promise.all(paths.map((p) => apiGet<{ url: string }>(p)));
    assert.equal(stub.refreshCalls, 1, "refresh must be called exactly once");
    assert.equal(results.length, 6);
    for (let i = 0; i < paths.length; i += 1) {
      assert.equal(results[i].url, paths[i]);
    }
  } finally {
    stub.restore();
  }
});

test("a later expiry refreshes again after the first promise settles", async () => {
  const stub = installFetchStub();
  try {
    await Promise.all([apiGet("/api/a"), apiGet("/api/b"), apiGet("/api/c")]);
    // The in-flight promise has cleared; a fresh batch refreshes once more.
    await Promise.all([apiGet("/api/d"), apiGet("/api/e")]);
    assert.equal(stub.refreshCalls, 2);
  } finally {
    stub.restore();
  }
});

test("refreshSession shares one promise while in flight", async () => {
  const stub = installFetchStub();
  try {
    const a = refreshSession();
    const b = refreshSession();
    assert.equal(a, b, "concurrent callers get the same promise");
    assert.equal(await a, "refreshed");
    stub; // one refresh call recorded
    assert.equal(stub.refreshCalls, 1);
  } finally {
    stub.restore();
  }
});

// --- Refresh outage handling -------------------------------------------------
// A restart, a 5xx or a dropped connection during refresh must not sign
// anyone out; only a real 401 from the refresh call does.

function installRefreshStub(answers: Array<number | "throw">) {
  let refreshCalls = 0;
  const origFetch = globalThis.fetch;
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input);
    if (url === "/api/session/refresh") {
      refreshCalls += 1;
      const a = answers.length > 1 ? answers.shift()! : answers[0];
      if (a === "throw") throw new TypeError("fetch failed");
      return new Response(JSON.stringify({}), { status: a });
    }
    return new Response(null, { status: 401 }); // the data call: always expired
  }) as typeof fetch;
  return {
    get refreshCalls() {
      return refreshCalls;
    },
    restore() {
      globalThis.fetch = origFetch;
    },
  };
}

const noSleep = async () => {};

test("refreshSession: a real 401 signs out after one try", async () => {
  const stub = installRefreshStub([401]);
  try {
    assert.equal(await refreshSession(noSleep), "sign-out");
    assert.equal(stub.refreshCalls, 1);
  } finally {
    stub.restore();
  }
});

test("refreshSession: 503 then 200 retries and refreshes", async () => {
  const stub = installRefreshStub([503, 200]);
  try {
    assert.equal(await refreshSession(noSleep), "refreshed");
    assert.equal(stub.refreshCalls, 2);
  } finally {
    stub.restore();
  }
});

test("refreshSession: a dropped connection retries twice then keeps the session", async () => {
  const stub = installRefreshStub(["throw"]);
  try {
    assert.equal(await refreshSession(noSleep), "keep-session");
    assert.equal(stub.refreshCalls, 3);
  } finally {
    stub.restore();
  }
});

test("refreshSession: concurrent callers share one retrying refresh", async () => {
  const stub = installRefreshStub([502, 502, 200]);
  try {
    const [a, b] = await Promise.all([refreshSession(noSleep), refreshSession(noSleep)]);
    assert.equal(a, "refreshed");
    assert.equal(b, "refreshed");
    assert.equal(stub.refreshCalls, 3);
  } finally {
    stub.restore();
  }
});

test("apiGet: a 500 from refresh does not redirect to /login; the call fails with 503", async () => {
  const stub = installRefreshStub([500]);
  let replaced: string | null = null;
  const g = globalThis as unknown as { window?: unknown };
  const origWindow = g.window;
  g.window = {
    location: { pathname: "/movies", search: "", replace: (u: string) => (replaced = u) },
  };
  try {
    await assert.rejects(
      apiGet("/api/library/sections"),
      (e: unknown) => e instanceof ApiError && e.status === 503,
    );
    assert.equal(replaced, null, "must not navigate to /login");
    assert.equal(stub.refreshCalls, 3, "first try plus two retries");
  } finally {
    g.window = origWindow;
    stub.restore();
  }
});

test("apiGet: a 401 from refresh redirects to /login", async () => {
  const stub = installRefreshStub([401]);
  let replaced: string | null = null;
  const g = globalThis as unknown as { window?: unknown };
  const origWindow = g.window;
  g.window = {
    location: { pathname: "/movies", search: "", replace: (u: string) => (replaced = u) },
  };
  try {
    void apiGet("/api/library/sections"); // never resolves by design
    await new Promise((r) => setTimeout(r, 50));
    assert.equal(replaced, "/login?next=%2Fmovies");
  } finally {
    g.window = origWindow;
    stub.restore();
  }
});

// The art dialog (components/ArtOverrideModal.tsx) used plain fetch(), so an
// expired access token showed a raw "token_expired". Its calls now go through
// apiPost / apiDelete; these cover the multipart upload and the delete.
test("a FormData upload is sent untouched and resent after one refresh", async () => {
  const origFetch = globalThis.fetch;
  const calls: { url: string; body: unknown; ct: string | undefined }[] = [];
  let refreshCalls = 0;
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/session/refresh") {
      refreshCalls += 1;
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }
    const headers = (init?.headers ?? {}) as Record<string, string>;
    calls.push({ url, body: init?.body, ct: headers["content-type"] });
    if (calls.length === 1) {
      return new Response(JSON.stringify({ detail: "token_expired" }), { status: 401 });
    }
    return new Response(JSON.stringify({ role: "thumb" }), { status: 200 });
  }) as typeof fetch;
  try {
    const form = new FormData();
    form.append("file", new Blob([new Uint8Array([1, 2, 3])], { type: "image/png" }), "a.png");
    const out = await apiPost<{ role: string }>("/api/admin/art/artist/x/thumb", form);
    assert.equal(out.role, "thumb");
    assert.equal(refreshCalls, 1);
    assert.equal(calls.length, 2);
    for (const c of calls) {
      // Same FormData object both times, no JSON content-type, so the browser
      // writes the multipart boundary itself.
      assert.equal(c.body, form);
      assert.equal(c.ct, undefined);
    }
  } finally {
    globalThis.fetch = origFetch;
  }
});

test("a JSON body still goes out as JSON", async () => {
  const origFetch = globalThis.fetch;
  let seen: { body: unknown; ct: string | undefined } | null = null;
  globalThis.fetch = (async (_input: unknown, init?: RequestInit) => {
    const headers = (init?.headers ?? {}) as Record<string, string>;
    seen = { body: init?.body, ct: headers["content-type"] };
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  }) as typeof fetch;
  try {
    await apiPost("/api/admin/art/artist/x/thumb/from-url", { url: "https://e.test/a.jpg" });
    assert.deepEqual(seen, {
      body: JSON.stringify({ url: "https://e.test/a.jpg" }),
      ct: "application/json",
    });
  } finally {
    globalThis.fetch = origFetch;
  }
});

test("apiDelete refreshes on token_expired and resolves on 204", async () => {
  const origFetch = globalThis.fetch;
  let hits = 0;
  let refreshCalls = 0;
  globalThis.fetch = (async (input: unknown) => {
    if (String(input) === "/api/session/refresh") {
      refreshCalls += 1;
      return new Response(null, { status: 200 });
    }
    hits += 1;
    if (hits === 1) {
      return new Response(JSON.stringify({ detail: "token_expired" }), { status: 401 });
    }
    return new Response(null, { status: 204 });
  }) as typeof fetch;
  try {
    assert.equal(await apiDelete("/api/admin/art/artist/x/thumb"), undefined);
    assert.equal(refreshCalls, 1);
    assert.equal(hits, 2);
  } finally {
    globalThis.fetch = origFetch;
  }
});
