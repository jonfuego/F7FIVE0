// node:test coverage for the collapsed Admin section summaries and the
// "needs attention" rule (a running/failed scan, an update available/running
// must show even when a section is folded).
//
// Run: node --test frontend/lib/admin-sections.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { remoteAccessSummary, scanSummary, updatesSummary, type ScanStatusLike } from "./admin-sections.ts";

test("remote access: off, connected, and not reachable", () => {
  assert.deepEqual(remoteAccessSummary(null), { text: "Off", attention: false });
  assert.deepEqual(
    remoteAccessSummary({ public_url: null, method: null, reachable: null }),
    { text: "Off", attention: false },
  );
  assert.deepEqual(
    remoteAccessSummary({ public_url: "https://x", method: "cloudflare", reachable: true }),
    { text: "Cloudflare, Connected", attention: false },
  );
  // Not reachable needs attention.
  assert.deepEqual(
    remoteAccessSummary({ public_url: "https://x", method: "cloudflare", reachable: false }),
    { text: "Cloudflare, not reachable", attention: true },
  );
});

test("updates: up to date, available, and running", () => {
  assert.deepEqual(
    updatesSummary({ installed_version: "1.0.6", latest_version: "1.0.6", update_available: false, run: null }),
    { text: "1.0.6, up to date", attention: false },
  );
  // An available update needs attention so a folded card still flags it.
  assert.deepEqual(
    updatesSummary({ installed_version: "1.0.6", latest_version: "1.0.7", update_available: true, run: null }),
    { text: "1.0.7 available", attention: true },
  );
  // A running update needs attention and wins over everything else.
  assert.deepEqual(
    updatesSummary({ installed_version: "1.0.6", latest_version: "1.0.7", update_available: true, run: { active: true } }),
    { text: "Updating now", attention: true },
  );
});

function scan(partial: Partial<ScanStatusLike>): ScanStatusLike {
  return { state: "idle", finished_at: null, current_library: null, libraries: {}, ...partial };
}

test("scan: running shows a percent and needs attention", () => {
  const s = scanSummary(scan({
    state: "running",
    current_library: "music",
    libraries: { music: { state: "running", seen: 100, probed: 40, added: 10 } },
  }));
  assert.deepEqual(s, { text: "Scanning Music 40%", attention: true });
});

test("scan: errors and failure need attention; a clean finish does not", () => {
  assert.deepEqual(
    scanSummary(scan({ state: "done", finished_at: "x", libraries: { music: { state: "done", errors: 1 } } })),
    { text: "1 error", attention: true },
  );
  assert.deepEqual(
    scanSummary(scan({ state: "failed", libraries: {} })),
    { text: "Scan failed", attention: true },
  );
  assert.deepEqual(
    scanSummary(scan({ state: "done", finished_at: "x", libraries: { music: { state: "done" } } })),
    { text: "Up to date", attention: false },
  );
});
