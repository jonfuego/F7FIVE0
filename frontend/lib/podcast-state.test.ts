// node:test coverage for the episode state labels on the show page and the
// In progress row.
//
// Run: node --test frontend/lib/podcast-state.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { episodeStateLabel, isFinished, progressFraction } from "./podcast-state.ts";

test("a new episode says New", () => {
  assert.equal(episodeStateLabel({ kind: "new" }, 3600), "New");
});

test("a played episode says Played", () => {
  assert.equal(episodeStateLabel({ kind: "played" }, 3600), "Played");
});

test("an episode in progress says how long is left", () => {
  assert.equal(episodeStateLabel({ kind: "in_progress", position_sec: 600 }, 3600), "50 min left");
  assert.equal(episodeStateLabel({ kind: "in_progress", position_sec: 3500 }, 3600), "2 min left");
  assert.equal(episodeStateLabel({ kind: "in_progress", position_sec: 3590 }, 3600), "1 min left");
  assert.equal(episodeStateLabel({ kind: "in_progress", position_sec: 600 }, 5400), "1 hr 20 min left");
});

test("without a length it says where to resume", () => {
  assert.equal(episodeStateLabel({ kind: "in_progress", position_sec: 600 }, null), "Resume at 10:00");
  assert.equal(episodeStateLabel({ kind: "in_progress", position_sec: 3723 }, undefined), "Resume at 1:02:03");
});

test("progress fraction is held between 0 and 1", () => {
  assert.equal(progressFraction({ kind: "in_progress", position_sec: 900 }, 3600), 0.25);
  assert.equal(progressFraction({ kind: "in_progress", position_sec: 9000 }, 3600), 1);
  assert.equal(progressFraction({ kind: "new" }, 3600), 0);
  assert.equal(progressFraction({ kind: "played" }, 3600), 1);
  assert.equal(progressFraction({ kind: "in_progress", position_sec: 10 }, null), 0);
});

test("finished means played", () => {
  assert.equal(isFinished({ kind: "played" }), true);
  assert.equal(isFinished({ kind: "new" }), false);
  assert.equal(isFinished({ kind: "in_progress", position_sec: 5 }), false);
});
