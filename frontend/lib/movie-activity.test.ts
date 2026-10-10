// node:test coverage for the movie activity line (item 8): nothing when
// unwatched, "Watched <date>" when finished, "N min left" when partway.
//
// Run: node --test frontend/lib/movie-activity.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { movieActivityLine } from "./movie-activity.ts";

test("unwatched shows nothing", () => {
  assert.equal(movieActivityLine(null), null);
  assert.equal(movieActivityLine(undefined), null);
  assert.equal(movieActivityLine({ completed_at: null, position_sec: 0, duration_sec: 7200 }), null);
});

test("finished shows a Watched date", () => {
  const line = movieActivityLine({ completed_at: "2026-03-03T10:00:00Z", position_sec: 7200, duration_sec: 7200 });
  assert.ok(line && line.startsWith("Watched "), line ?? "null");
});

test("partway shows minutes left", () => {
  // 7200s total, 4500s in -> 2700s left -> 45 min.
  assert.equal(
    movieActivityLine({ completed_at: null, position_sec: 4500, duration_sec: 7200 }),
    "45 min left",
  );
  // Right at the end rounds to "Almost done".
  assert.equal(
    movieActivityLine({ completed_at: null, position_sec: 7190, duration_sec: 7200 }),
    "Almost done",
  );
});
