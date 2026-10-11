// node:test coverage for the in-memory list cache. Run: node --test "lib/*.test.ts"
import { test } from "node:test";
import assert from "node:assert/strict";
import { getList, invalidateLists, LIST_FRESH_MS, pickListLoad, setList } from "./list-cache.ts";

test("nothing cached: fetch with placeholders", () => {
  invalidateLists();
  assert.equal(getList("movies"), null);
  assert.deepEqual(pickListLoad(null), { paint: false, fetch: true });
});

test("a fresh copy is painted and not fetched again", () => {
  invalidateLists();
  setList("movies", [1, 2, 3], 1000);
  const got = getList<number[]>("movies", 1000 + 5_000);
  assert.deepEqual(got?.data, [1, 2, 3]);
  assert.equal(got?.ageMs, 5_000);
  assert.deepEqual(pickListLoad(got), { paint: true, fetch: false });
});

test("an old copy is painted first, then fetched", () => {
  invalidateLists();
  setList("movies", ["a"], 0);
  const got = getList("movies", LIST_FRESH_MS);
  assert.deepEqual(pickListLoad(got), { paint: true, fetch: true });
});

test("force always fetches, but still paints the copy", () => {
  invalidateLists();
  setList("movies", ["a"], 0);
  const got = getList("movies", 1);
  assert.deepEqual(pickListLoad(got, { force: true }), { paint: true, fetch: true });
});

test("invalidate drops one list or all of them", () => {
  invalidateLists();
  setList("movies", [1], 0);
  setList("series", [2], 0);
  invalidateLists("movies");
  assert.equal(getList("movies"), null);
  assert.notEqual(getList("series"), null);
  invalidateLists();
  assert.equal(getList("series"), null);
});

test("a clock that runs backwards never gives a negative age", () => {
  invalidateLists();
  setList("movies", [1], 5_000);
  assert.equal(getList("movies", 1_000)?.ageMs, 0);
});
