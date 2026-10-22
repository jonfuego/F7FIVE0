import { test } from "node:test";
import assert from "node:assert/strict";
import { LIBRARIES_PATH, loadLibraries, organizerLibraries } from "./libraries.ts";

const rows = [
  { id: "a", name: "Movies", kind: "movies", sort_order: 0 },
  { id: "b", name: "TV", kind: "tv", sort_order: 0 },
  { id: "c", name: "Music", kind: "music", sort_order: 0 },
  { id: "d", name: "Podcasts", kind: "podcasts", sort_order: 0 },
];

test("loadLibraries reads the bare array GET /api/libraries answers", async () => {
  let asked = "";
  const libs = await loadLibraries(async (path) => {
    asked = path;
    return rows;
  });
  assert.equal(asked, LIBRARIES_PATH);
  assert.deepEqual(libs.map((l) => l.id), ["a", "b", "c", "d"]);
});

test("loadLibraries returns [] for a wrapped object (the shape the Organizer used to expect)", async () => {
  assert.deepEqual(await loadLibraries(async () => ({ libraries: rows })), []);
});

test("organizerLibraries keeps movies, tv and music only", () => {
  assert.deepEqual(organizerLibraries(rows).map((l) => l.kind), ["movies", "tv", "music"]);
});
