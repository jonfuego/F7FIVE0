// node:test coverage for artSized. Run: node --test frontend/lib/art-url.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { artSized } from "./art-url.ts";

test("adds w after the v cache key", () => {
  assert.equal(artSized("/api/art/movie/abc/poster?v=12", 300), "/api/art/movie/abc/poster?v=12&w=300");
});
test("starts a query when there is none", () => {
  assert.equal(artSized("/api/art/movie/abc/poster", 600), "/api/art/movie/abc/poster?w=600");
});
test("replaces an existing w", () => {
  assert.equal(artSized("/api/art/movie/abc/poster?v=1&w=600", 300), "/api/art/movie/abc/poster?v=1&w=300");
});
test("leaves remote URLs and null alone", () => {
  assert.equal(artSized("https://image.tmdb.org/x.jpg", 300), "https://image.tmdb.org/x.jpg");
  assert.equal(artSized(null, 300), null);
});
