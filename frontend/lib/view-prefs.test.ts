// node:test coverage for saved library views (defaults and merge).
//
// Run: node --test frontend/lib/view-prefs.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { ADMIN_SECTION_IDS, mergeViewPrefs, resolveViewPref, viewPrefPath } from "./view-prefs.ts";

test("nothing stored gives every default", () => {
  assert.deepEqual(mergeViewPrefs({}), {
    "music.browse": "artists",
    "movies.genre": "All",
    "movies.sort": "title",
    "tv.status": "All",
    "musicvideos.sort": "name",
    "mixes.inputs": {},
    "admin.collapsed": [...ADMIN_SECTION_IDS],
  });
  assert.equal(mergeViewPrefs(null)["music.browse"], "artists");
});

test("admin.collapsed keeps known section ids and drops the rest", () => {
  assert.deepEqual(resolveViewPref("admin.collapsed", ["updates", "history"]), ["updates", "history"]);
  // A stale id is not trusted; the whole value is rejected and falls back to
  // the default (every section collapsed) if any id is unknown.
  assert.deepEqual(resolveViewPref("admin.collapsed", ["updates", "gone"]), [...ADMIN_SECTION_IDS]);
  assert.deepEqual(resolveViewPref("admin.collapsed", "updates"), [...ADMIN_SECTION_IDS]);
  // An empty list is a real choice (the user opened everything) and is kept.
  assert.deepEqual(resolveViewPref("admin.collapsed", []), []);
});

test("admin.collapsed with nothing stored collapses every section", () => {
  assert.deepEqual(resolveViewPref("admin.collapsed", undefined), [...ADMIN_SECTION_IDS]);
  assert.equal(resolveViewPref("admin.collapsed", null).length, ADMIN_SECTION_IDS.length);
});

test("the Radarr, Sonarr and Lidarr card can be folded and remembered", () => {
  assert.deepEqual(resolveViewPref("admin.collapsed", ["arr", "metadata"]), ["arr", "metadata"]);
});

test("the Scans card can be folded and remembered, and is collapsed by default", () => {
  assert.ok((ADMIN_SECTION_IDS as readonly string[]).includes("scans"));
  assert.deepEqual(resolveViewPref("admin.collapsed", ["scans", "arr"]), ["scans", "arr"]);
  assert.ok((resolveViewPref("admin.collapsed", undefined) as string[]).includes("scans"));
  // A list saved before the Library section went away is still valid.
  assert.deepEqual(resolveViewPref("admin.collapsed", ["library", "updates"]), ["library", "updates"]);
});

test("a stored view wins over the default (pick Albums, come back, still Albums)", () => {
  const m = mergeViewPrefs({ "music.browse": "albums", "movies.genre": "Comedy", "tv.status": "Watching" });
  assert.equal(m["music.browse"], "albums");
  assert.equal(m["movies.genre"], "Comedy");
  assert.equal(m["tv.status"], "Watching");
});

test("invalid stored values fall back to the default", () => {
  assert.equal(resolveViewPref("music.browse", "playlists"), "artists");
  assert.equal(resolveViewPref("movies.sort", 3), "title");
  assert.equal(resolveViewPref("movies.genre", ""), "All");
  assert.deepEqual(resolveViewPref("mixes.inputs", { "by-year": { year: 1985 } }), {});
  assert.deepEqual(resolveViewPref("mixes.inputs", { "by-year": { year: "1985" } }), { "by-year": { year: "1985" } });
});

test("keys the web doesn't know are ignored", () => {
  const m = mergeViewPrefs({ "sort:movies": { sortKey: "year" }, "hub:video": "shows" });
  assert.equal("sort:movies" in m, false);
});

test("path goes through the library BFF", () => {
  assert.equal(viewPrefPath("music.browse"), "/api/library/view-prefs/music.browse");
});
