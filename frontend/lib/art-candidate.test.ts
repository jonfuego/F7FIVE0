import { test } from "node:test";
import assert from "node:assert/strict";
import { candidateTileSrc } from "./art-candidate.ts";

test("tile uses the preview URL when the candidate has one", () => {
  assert.equal(
    candidateTileSrc({
      url: "https://image.tmdb.org/t/p/original/p.jpg",
      preview_url: "https://image.tmdb.org/t/p/w342/p.jpg",
    }),
    "https://image.tmdb.org/t/p/w342/p.jpg",
  );
});

test("tile falls back to the full URL with no preview", () => {
  const url = "https://x.example/p.jpg";
  assert.equal(candidateTileSrc({ url }), url);
  assert.equal(candidateTileSrc({ url, preview_url: null }), url);
  assert.equal(candidateTileSrc({ url, preview_url: "" }), url);
  assert.equal(candidateTileSrc({ url, preview_url: "  " }), url);
});
