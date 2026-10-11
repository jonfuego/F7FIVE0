// node:test coverage for the art BFF header helpers.
// Run: node --test frontend/lib/art-proxy.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { artResponseHeaders, artUpstreamHeaders } from "./art-proxy.ts";

test("forwards If-None-Match and the Bearer", () => {
  const h = artUpstreamHeaders("Bearer t", new Headers({ "if-none-match": '"abc"' }));
  assert.equal(h.authorization, "Bearer t");
  assert.equal(h["if-none-match"], '"abc"');
});

test("no If-None-Match when the browser sent none", () => {
  const h = artUpstreamHeaders("Bearer t", new Headers());
  assert.equal("if-none-match" in h, false);
});

test("passes Cache-Control and ETag through, no max-age=3600", () => {
  const up = new Headers({
    "content-type": "image/webp",
    "cache-control": "private, max-age=31536000, immutable",
    etag: '"1-2-w300"',
  });
  const h = artResponseHeaders(up);
  assert.equal(h.get("cache-control"), "private, max-age=31536000, immutable");
  assert.equal(h.get("etag"), '"1-2-w300"');
  assert.equal(h.get("content-type"), "image/webp");
});

test("a 304 keeps its ETag and cache-control", () => {
  const h = artResponseHeaders(new Headers({ etag: '"x"', "cache-control": "private, max-age=31536000, immutable" }));
  assert.equal(h.get("etag"), '"x"');
});

test("missing upstream Cache-Control falls back to private", () => {
  assert.equal(artResponseHeaders(new Headers()).get("cache-control"), "private, no-cache");
});
