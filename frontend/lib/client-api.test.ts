// node:test coverage for the single-flight session refresh.
//
// Run: node --test frontend/lib/client-api.test.ts
//
// When many requests get a 401 at the same moment, they must share one
// /api/session/refresh round-trip. Without that, the second refresh uses the
// grace window and the rest trip reuse detection and the session dies.

import { test } from "node:test";
import assert from "node:assert/strict";
import { apiGet, refreshSession } from "./client-api.ts";

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
    assert.equal(await a, true);
    stub; // one refresh call recorded
    assert.equal(stub.refreshCalls, 1);
  } finally {
    stub.restore();
  }
});
