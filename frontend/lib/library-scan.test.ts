// node:test coverage for the library scan wording and Admin helpers.
//
// Run: node --test frontend/lib/library-scan.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  SCAN_POLL_MS, SCANNING_TEXT, countsText, emptyLibraryText, mvCountsText, mvScanHeadline,
  ofTotalText, scanHeadline, scanPercent, shouldPollScan, showArrSync,
} from "./library-scan.ts";

test("empty library pages say a scan is running while one is", () => {
  assert.equal(SCANNING_TEXT, "Your library is being scanned. Items show up here as they are found.");
  for (const kind of ["movies", "tv", "artists", "albums"] as const) {
    assert.equal(emptyLibraryText(kind, true), SCANNING_TEXT, kind);
  }
});

test("empty library pages keep today's text when no scan is running", () => {
  assert.equal(emptyLibraryText("movies", false), "No movies in the library yet.");
  assert.equal(emptyLibraryText("tv", false), "No TV shows in the library yet.");
  assert.equal(emptyLibraryText("artists", false), "No artists in the library yet.");
  assert.equal(emptyLibraryText("albums", false), "No albums in the library yet.");
});

test("the *arr sync button shows only when Radarr, Sonarr or Lidarr is set up", () => {
  assert.equal(showArrSync(undefined), false);
  assert.equal(showArrSync(null), false);
  assert.equal(showArrSync({ radarr: false, sonarr: false, lidarr: false }), false);
  assert.equal(showArrSync({ radarr: true, sonarr: false, lidarr: false }), true);
  assert.equal(showArrSync({ radarr: false, sonarr: false, lidarr: true }), true);
});

test("the status block polls every 3 seconds while a scan runs and stops when idle", () => {
  assert.equal(SCAN_POLL_MS, 3000);
  assert.equal(shouldPollScan(null), false);
  assert.equal(shouldPollScan({ state: "idle" }), false);
  assert.equal(shouldPollScan({ state: "running" }), true);
});

const NOW = Date.parse("2026-10-08T12:00:00Z");
const base = { started_at: null, finished_at: null, current_library: null, libraries: {}, last_error: null };

test("the headline says which library is scanning, or when the last scan finished", () => {
  assert.equal(scanHeadline({ ...base, state: "running", current_library: "movies" }, NOW), "Scanning Movies");
  assert.equal(scanHeadline({ ...base, state: "running", current_library: "tv" }, NOW), "Scanning TV");
  assert.equal(scanHeadline({ ...base, state: "running" }, NOW), "Scanning");
  assert.equal(
    scanHeadline({ ...base, state: "idle", finished_at: "2026-10-08T11:55:00Z" }, NOW),
    "Last scan finished 5 minutes ago",
  );
  assert.equal(scanHeadline({ ...base, state: "idle" }, NOW), "No scan has run yet");
});

test("counts read as a short sentence", () => {
  assert.equal(
    countsText({ state: "running", seen: 120, added: 118, probed: 118, missing: 2, errors: 1 }),
    "120 files seen, 118 added, 2 missing, 1 error",
  );
  assert.equal(countsText({ state: "done", seen: 1, added: 0, probed: 0, missing: 0, errors: 2 }), "1 file seen, 0 added, 2 errors");
  assert.equal(countsText({ state: "queued" }), "Waiting");
});

test("the progress bar percent is a clamped, rounded count over total", () => {
  assert.equal(scanPercent(0, 0), 0, "no total yet reads empty, not full");
  assert.equal(scanPercent(5, 0), 0);
  assert.equal(scanPercent(undefined, 10), 0);
  assert.equal(scanPercent(5, 10), 50);
  assert.equal(scanPercent(1, 3), 33);
  assert.equal(scanPercent(10, 10), 100);
  assert.equal(scanPercent(11, 10), 100, "a stray count past the total never overflows");
});

test("the x-of-y text shows the total when known, else just the count", () => {
  assert.equal(ofTotalText(12, 240), "12 of 240");
  assert.equal(ofTotalText(0, 240), "0 of 240");
  assert.equal(ofTotalText(12, 0), "12");
  assert.equal(ofTotalText(0, 0), "");
  assert.equal(ofTotalText(undefined, undefined), "");
});

test("the music videos block headline mirrors the folder scan", () => {
  const mvBase = { started_at: null, total: 0, count: 0, added: 0, missing: 0, errors: 0, last_error: null };
  assert.equal(mvScanHeadline({ ...mvBase, state: "running", finished_at: null }, NOW), "Scanning music videos");
  assert.equal(
    mvScanHeadline({ ...mvBase, state: "idle", finished_at: "2026-10-08T11:55:00Z" }, NOW),
    "Last scan finished 5 minutes ago",
  );
  assert.equal(mvScanHeadline({ ...mvBase, state: "idle", finished_at: null }, NOW), "No scan has run yet");
});

test("the music videos counts read as a short sentence", () => {
  const mvBase = { state: "running", started_at: null, finished_at: null, total: 100, count: 40, last_error: null };
  assert.equal(mvCountsText({ ...mvBase, added: 38, missing: 1, errors: 1 }), "38 added, 1 missing, 1 error");
  assert.equal(mvCountsText({ ...mvBase, added: 40, missing: 0, errors: 0 }), "40 added");
});
