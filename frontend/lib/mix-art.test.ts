// node:test coverage for mixArtSrc. Run: node --test frontend/lib/mix-art.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { hasMixArt, mixArtSrc } from "./mix-art.ts";

test("falls back to the static default with no override", () => {
  assert.equal(mixArtSrc("random", null), "/mix/random.svg");
  assert.equal(mixArtSrc("most-played", {}), "/mix/most-played.svg");
  assert.equal(mixArtSrc("random", { random: null }), "/mix/random.svg");
});
test("uses the override, keeping the cache key", () => {
  const map = { "most-played": "/api/art/mix/abc/cover?v=99" };
  assert.equal(mixArtSrc("most-played", map), "/api/art/mix/abc/cover?v=99");
  assert.equal(mixArtSrc("random", map), "/mix/random.svg");
});
test("all 11 mixes have a picture slot and a default file", async () => {
  const { MIX_ART_KEYS } = await import("./mix-art.ts");
  const { readdirSync } = await import("node:fs");
  assert.equal(MIX_ART_KEYS.length, 11);
  assert.equal(new Set(MIX_ART_KEYS).size, 11);
  const files = new Set(readdirSync(new URL("../public/mix/", import.meta.url)));
  for (const key of MIX_ART_KEYS) {
    assert.equal(hasMixArt(key), true, key);
    assert.equal(mixArtSrc(key, null), `/mix/${key}.svg`);
    assert.ok(files.has(`${key}.svg`), `public/mix/${key}.svg exists`);
  }
  assert.equal(files.size, 11);
});
test("a new mix uses its override", () => {
  const map = { "by-genre": "/api/art/mix/xyz/cover?v=5" };
  assert.equal(mixArtSrc("by-genre", map), "/api/art/mix/xyz/cover?v=5");
});
test("unknown keys get null", () => {
  assert.equal(hasMixArt("by-planet"), false);
  assert.equal(mixArtSrc("by-planet", { "by-planet": "/api/art/mix/x/cover?v=1" }), null);
});
