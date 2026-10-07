// node:test coverage for the Home hero Play resolver.
//
// Run: node --test frontend/lib/play-action.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveHeroPlay, watchHref } from "./play-action.ts";

test("album always plays in the dock, never navigates", () => {
  assert.deepEqual(resolveHeroPlay("album", null), { type: "album" });
  // An id is irrelevant for albums; they still stay on the page.
  assert.deepEqual(resolveHeroPlay("album", "mf-1"), { type: "album" });
});

test("a movie with a playable file goes to /watch/<id>", () => {
  assert.deepEqual(resolveHeroPlay("movie", "mf-42"), {
    type: "watch",
    href: "/watch/mf-42",
  });
});

test("a series on-deck / first-episode file goes to /watch/<id>", () => {
  assert.deepEqual(resolveHeroPlay("series", "ep-7"), {
    type: "watch",
    href: "/watch/ep-7",
  });
});

test("a music video goes to /watch/<id>", () => {
  assert.deepEqual(resolveHeroPlay("music_video", "mv-9"), {
    type: "watch",
    href: "/watch/mv-9",
  });
});

test("a video kind with nothing on disk is inert", () => {
  assert.deepEqual(resolveHeroPlay("movie", null), { type: "none" });
  assert.deepEqual(resolveHeroPlay("series", undefined), { type: "none" });
});

test("watchHref builds the player route", () => {
  assert.equal(watchHref("abc"), "/watch/abc");
});
