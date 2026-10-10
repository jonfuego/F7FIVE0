// node:test coverage for the Admin / Account profile load.
//
// Run: node --test frontend/lib/load-me.test.ts
//
// CAUSE this guards against: the Admin and Account pages loaded
// /api/session/me with a raw fetch() that did not refresh on a 401. On first
// navigation after the ~15-min access token expired, the BFF returned 401, the
// raw fetch surfaced it as "not ok", and the page was left with a null profile,
// which renders blank (Admin skeleton forever, Account error on an empty page)
// until a manual browser reload re-mints the token. loadMe now runs through the
// shared apiGet, which does the single-flight /api/session/refresh + retry, so
// the page renders on the first navigation even right after the token expired.
//
// The first test fails before the fix: the old raw-fetch loader (modeled here)
// never calls /api/session/refresh and returns null on the expired-token 401.
// loadMe driven by apiGet refreshes once and returns the profile.

import { test } from "node:test";
import assert from "node:assert/strict";
import { apiGet } from "./client-api.ts";
import { loadMe } from "./load-me.ts";

type Me = { id: string; username: string; role: string };

// Fetch stub: /api/session/me answers 401 until a refresh has run (the expired
// access token), then 200 with the profile. /api/session/refresh flips that
// flag and counts calls so we can prove exactly one round-trip.
function installExpiredTokenStub() {
  let tokenFresh = false;
  let refreshCalls = 0;
  const me: Me = { id: "u1", username: "jon", role: "admin" };
  const origFetch = globalThis.fetch;
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input);
    if (url === "/api/session/refresh") {
      refreshCalls += 1;
      tokenFresh = true;
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }
    if (url === "/api/session/me") {
      if (!tokenFresh) return new Response(null, { status: 401 });
      return new Response(JSON.stringify(me), { status: 200 });
    }
    return new Response(null, { status: 404 });
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

// The old code path the two pages used: a raw fetch with no refresh. Kept here
// only to prove the regression; nothing ships it.
async function rawFetchLoad(): Promise<Me | null> {
  const res = await fetch("/api/session/me", { cache: "no-store" });
  if (!res.ok) return null;
  return (await res.json()) as Me;
}

test("loadMe refreshes an expired access token and returns the profile on first load", async () => {
  const stub = installExpiredTokenStub();
  try {
    // The old raw-fetch loader never refreshes: it returns null on the 401,
    // which is the blank-page bug.
    const viaRawFetch = await rawFetchLoad();
    assert.equal(viaRawFetch, null, "raw fetch returns null on the expired-token 401 (the bug)");
    assert.equal(stub.refreshCalls, 0, "raw fetch never tried to refresh");

    // loadMe driven by apiGet (the fix) refreshes once and returns the profile.
    const profile = await loadMe(apiGet);
    assert.ok(profile, "loadMe returns the profile after refreshing");
    assert.equal(profile?.username, "jon");
    assert.equal(stub.refreshCalls, 1, "loadMe refreshed exactly once");
  } finally {
    stub.restore();
  }
});

test("loadMe does not refresh when the access token is already valid", async () => {
  const stub = installExpiredTokenStub();
  try {
    // Prime the token as valid by refreshing first, then a clean load must not
    // refresh again.
    await fetch("/api/session/refresh", { method: "POST" });
    const before = stub.refreshCalls;
    const profile = await loadMe(apiGet);
    assert.ok(profile);
    assert.equal(stub.refreshCalls, before, "no extra refresh when the token is valid");
  } finally {
    stub.restore();
  }
});
