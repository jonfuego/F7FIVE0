// node:test coverage for the Admin > Library health helpers.
//
// Run: node --test frontend/lib/library-health.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { emptyMissingListText, kindBreakdown, kindTotal } from "./library-health.ts";

// The hand-test response (L-05): the page used to draw none of this.
const UNMATCHED = { movie: 1, series: 1, artist: 5, album: 3 };
const MISSING_ART = { movie: 1, series: 1, artist: 0, album: 0 };

test("kindTotal sums every kind", () => {
  assert.equal(kindTotal(UNMATCHED), 10);
  assert.equal(kindTotal(MISSING_ART), 2);
  assert.equal(kindTotal({}), 0);
  assert.equal(kindTotal(null), 0);
  assert.equal(kindTotal(undefined), 0);
});

test("kindBreakdown names the non-zero kinds in a fixed order", () => {
  assert.equal(kindBreakdown(UNMATCHED), "1 movie, 1 TV show, 5 artists, 3 albums");
  assert.equal(kindBreakdown(MISSING_ART), "1 movie, 1 TV show");
  assert.equal(kindBreakdown({ album: 2, movie: 3 }), "3 movies, 2 albums");
});

test("kindBreakdown is empty when nothing is counted", () => {
  assert.equal(kindBreakdown({ movie: 0, series: 0 }), "");
  assert.equal(kindBreakdown({}), "");
  assert.equal(kindBreakdown(null), "");
});

test("kindBreakdown keeps an unknown kind after the known ones", () => {
  assert.equal(kindBreakdown({ zebra: 2, movie: 1 }), "1 movie, 2 zebra");
});

test("empty list text explains why missing files are not listed yet", () => {
  assert.equal(emptyMissingListText(0), "No missing files.");
  const four = emptyMissingListText(4);
  assert.match(four, /^4 files are missing, none eligible for cleanup yet\./);
  assert.match(four, /7 days/);
  assert.match(emptyMissingListText(1), /^1 file is missing/);
});
