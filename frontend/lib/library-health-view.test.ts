import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_HEALTH_VIEW, HEALTH_VIEWS, healthTileCount, healthViewFromSearch, healthViewHref,
} from "./library-health-view.ts";

test("?view= picks the list, anything else falls back to the default", () => {
  for (const v of HEALTH_VIEWS) assert.equal(healthViewFromSearch(`?view=${v}`), v);
  assert.equal(healthViewFromSearch("view=errors"), "errors");
  assert.equal(healthViewFromSearch("?view=nope"), DEFAULT_HEALTH_VIEW);
  assert.equal(healthViewFromSearch(""), DEFAULT_HEALTH_VIEW);
});

test("hrefs round-trip through the parser", () => {
  assert.equal(healthViewHref("missing"), "/admin/library-health?view=missing");
  for (const v of HEALTH_VIEWS) {
    assert.equal(healthViewFromSearch(healthViewHref(v).split("?")[1]), v);
  }
});

test("each tile shows its own count", () => {
  const c = { missing_files_total: 350, missing_files_eligible: 0, probe_errors: 40, unreachable_folders: 1 };
  assert.deepEqual(HEALTH_VIEWS.map((v) => healthTileCount(v, c)), [350, 0, 40, 1]);
});
