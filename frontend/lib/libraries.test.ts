// node:test coverage for the visible-libraries loader and the Organizer filter.
//
// Run: node --test frontend/lib/libraries.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  LIBRARIES_PATH,
  loadLibraries,
  organizerLibraries,
  parseLibraries,
} from "./libraries.ts";

// The live 1.0.18 answer of GET /api/libraries: a bare array.
const BACKEND_ANSWER = [
  { id: "m1", name: "Movies", kind: "movies", sort_order: 0 },
  { id: "t1", name: "TV", kind: "tv", sort_order: 0 },
  { id: "a1", name: "Music", kind: "music", sort_order: 0 },
  { id: "v1", name: "Music videos", kind: "music_videos", sort_order: 0 },
  { id: "p1", name: "Podcasts", kind: "podcasts", sort_order: 0 },
];

test("parses the backend's bare array", () => {
  const libs = parseLibraries(BACKEND_ANSWER);
  assert.equal(libs.length, 5);
  assert.deepEqual(libs[0], { id: "m1", name: "Movies", kind: "movies", sort_order: 0 });
});

test("a wrapped object is not the backend shape and gives []", () => {
  assert.deepEqual(parseLibraries({ libraries: BACKEND_ANSWER }), []);
  assert.deepEqual(parseLibraries(null), []);
});

test("drops entries with no id or kind", () => {
  assert.deepEqual(parseLibraries([{ name: "x" }, null, "y", { id: "a", kind: "" }]), []);
});

test("Organizer lists movies, TV and music from the bare array", () => {
  const libs = organizerLibraries(parseLibraries(BACKEND_ANSWER));
  assert.deepEqual(
    libs.map((l) => l.id),
    ["m1", "t1", "a1"],
  );
});

test("loadLibraries asks the BFF path and parses the array", async () => {
  let asked = "";
  const libs = await loadLibraries(async (path) => {
    asked = path;
    return BACKEND_ANSWER;
  });
  assert.equal(asked, LIBRARIES_PATH);
  assert.equal(libs.length, 5);
});

test("loadLibraries returns [] on a fetch failure", async () => {
  const libs = await loadLibraries(async () => {
    throw new Error("down");
  });
  assert.deepEqual(libs, []);
});
