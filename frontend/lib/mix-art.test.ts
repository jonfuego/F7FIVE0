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
test("mixes without a picture slot get null", () => {
  assert.equal(hasMixArt("by-year"), false);
  assert.equal(mixArtSrc("by-year", { "by-year": "/api/art/mix/x/cover?v=1" }), null);
});
