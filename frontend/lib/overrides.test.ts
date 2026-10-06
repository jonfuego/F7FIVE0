// node:test coverage for the detail pages' Edit button loader.
//
// Run: node --test frontend/lib/overrides.test.ts
//
// The bug: after the 15-minute access cookie lapsed, the override fetch got a
// 401 and the page returned without a refresh, a modal or a message. The
// loader now goes through apiGet (refresh once, retry) and reports failures.

import { test } from "node:test";
import assert from "node:assert/strict";
import { apiGet, ApiError } from "./client-api.ts";
import { loadOverride, overridePath } from "./overrides.ts";

const ID = "acc57596-3a95-41a9-9022-760d5a0593f3";

test("an expired access token is refreshed and the override still loads", async () => {
  const calls: string[] = [];
  let refreshed = false;
  const orig = globalThis.fetch;
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input);
    calls.push(url);
    if (url === "/api/session/refresh") {
      refreshed = true;
      return new Response("{}", { status: 200 });
    }
    if (url === overridePath("movie", ID)) {
      if (!refreshed) return new Response(JSON.stringify({ detail: "token_expired" }), { status: 401 });
      return new Response(JSON.stringify({ kind: "movie", entity_id: ID }), { status: 200 });
    }
    return new Response("{}", { status: 404 });
  }) as typeof fetch;
  try {
    const res = await loadOverride<{ kind: string }>(apiGet, "movie", ID);
    assert.equal(res.ok, true);
    assert.equal(res.ok && res.data.kind, "movie");
    assert.deepEqual(calls, [overridePath("movie", ID), "/api/session/refresh", overridePath("movie", ID)]);
  } finally {
    globalThis.fetch = orig;
  }
});

test("a server error becomes a message instead of nothing", async () => {
  const res = await loadOverride(async () => {
    throw new ApiError(500, "internal_error", "HTTP 500: internal_error");
  }, "series", ID);
  assert.equal(res.ok, false);
  assert.match(!res.ok ? res.error : "", /Couldn't open the editor \(HTTP 500/);
});

test("forbidden and missing get plain messages", async () => {
  const forbidden = await loadOverride(async () => {
    throw new ApiError(403, "admin_required", "HTTP 403");
  }, "artist", ID);
  assert.deepEqual(forbidden, { ok: false, error: "Only admins can edit this." });
  const missing = await loadOverride(async () => {
    throw new ApiError(404, "not_found", "HTTP 404");
  }, "music_video_release", ID);
  assert.deepEqual(missing, { ok: false, error: "This item isn't in the library any more." });
});

test("a network failure is reported", async () => {
  const res = await loadOverride(async () => {
    throw new TypeError("Failed to fetch");
  }, "movie", ID);
  assert.deepEqual(res, { ok: false, error: "Couldn't open the editor (Failed to fetch)." });
});

test("the path names the kind and id", () => {
  assert.equal(overridePath("music_video_release", ID), `/api/admin/override/music_video_release/${ID}`);
});
