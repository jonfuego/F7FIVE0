// node:test coverage for episodeSubtitle.
//
// Run: node --test frontend/lib/format.test.ts
//
// The scene-named TV folders (Smallville S04E02) put the episode code in the
// card title. The subtitle must not repeat the title underneath itself.

import { test } from "node:test";
import assert from "node:assert/strict";
import { episodeSubtitle } from "./format.ts";

test("bare episode code under a title that repeats it returns null", () => {
  // Card title carries the code and there is no episode title, so the second
  // line would just be the title again. Hide it.
  assert.equal(episodeSubtitle("Smallville S04E02", "S04E02"), null);
});

test("subtitle equal to the title returns null", () => {
  assert.equal(
    episodeSubtitle("Smallville S04E02", "S04E02 - Smallville S04E02"),
    null,
  );
});

test("keeps a real episode title when the code matches", () => {
  assert.equal(
    episodeSubtitle("Smallville S04E02", "S04E02 - Red"),
    "Red",
  );
});

test("leaves the subtitle alone when the title has no code", () => {
  assert.equal(
    episodeSubtitle("Smallville", "S04E02 - Red"),
    "S04E02 - Red",
  );
});

test("passes through a non-code subtitle", () => {
  assert.equal(episodeSubtitle("Smallville", "Season 4"), "Season 4");
});

test("null and undefined subtitles return null", () => {
  assert.equal(episodeSubtitle("Smallville S04E02", null), null);
  assert.equal(episodeSubtitle("Smallville S04E02", undefined), null);
});
