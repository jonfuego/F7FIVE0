// node:test coverage for the pure library-nav rules.
//
// Run: node --test frontend/lib/library-nav.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  kindShowsNames,
  kindsWithMultipleLibraries,
  librariesForKind,
  libraryNavEntries,
  type LibraryInfo,
} from "./library-nav.ts";

const LIBS: LibraryInfo[] = [
  { id: "m1", name: "Movies", kind: "movies", sort_order: 0 },
  { id: "m2", name: "Kids Movies", kind: "movies", sort_order: 1 },
  { id: "tv1", name: "TV", kind: "tv", sort_order: 0 },
  { id: "mu1", name: "Music", kind: "music", sort_order: 0 },
];

test("a kind with more than one library shows names", () => {
  assert.equal(kindShowsNames(LIBS, "movies"), true);
});

test("a kind with exactly one library does not show names", () => {
  assert.equal(kindShowsNames(LIBS, "tv"), false);
  assert.equal(kindShowsNames(LIBS, "music"), false);
});

test("a kind with no libraries does not show names", () => {
  assert.equal(kindShowsNames(LIBS, "podcasts"), false);
});

test("nav entries are empty for a single-library kind and listed for multi", () => {
  assert.deepEqual(libraryNavEntries(LIBS, "tv"), []);
  const movies = libraryNavEntries(LIBS, "movies");
  assert.equal(movies.length, 2);
  // Ordered by sort_order.
  assert.deepEqual(movies.map((e) => e.id), ["m1", "m2"]);
});

test("librariesForKind sorts by sort_order then name", () => {
  const mixed: LibraryInfo[] = [
    { id: "b", name: "Bravo", kind: "movies", sort_order: 1 },
    { id: "a", name: "Alpha", kind: "movies", sort_order: 1 },
    { id: "z", name: "Zero", kind: "movies", sort_order: 0 },
  ];
  assert.deepEqual(librariesForKind(mixed, "movies").map((l) => l.id), ["z", "a", "b"]);
});

test("kindsWithMultipleLibraries lists only multi-library kinds", () => {
  assert.deepEqual(kindsWithMultipleLibraries(LIBS), ["movies"]);
});
