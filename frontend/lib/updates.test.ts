// node:test coverage for the Admin > Updates helpers (wording, phases, sizes).
//
// Run: node --test frontend/lib/updates.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  UPDATE_STEPS, blockedText, checkedAgo, encodePasswordHeader, formatBytes,
  isActivePhase, phaseLabel, runSummary, stepIndex, updateErrorText,
} from "./updates.ts";

test("active phases are the ones that need polling", () => {
  for (const p of ["queued", "downloading", "verifying", "backup", "installing", "health_check", "rolling_back"]) {
    assert.equal(isActivePhase(p), true, p);
  }
  for (const p of ["idle", "done", "rolled_back", "failed", "nonsense"]) {
    assert.equal(isActivePhase(p), false, p);
  }
});

test("every phase has a plain-language label", () => {
  assert.equal(phaseLabel("health_check"), "Checking that the new version works");
  assert.equal(phaseLabel("rolled_back"), "Went back to the old version");
  assert.equal(phaseLabel("something_new"), "something_new");
});

test("the progress steps run download to health check", () => {
  assert.deepEqual(UPDATE_STEPS, ["downloading", "verifying", "backup", "installing", "health_check"]);
  assert.equal(stepIndex("downloading"), 0);
  assert.equal(stepIndex("installing"), 3);
  assert.equal(stepIndex("done"), UPDATE_STEPS.length);
  assert.equal(stepIndex("rolling_back"), 4);
  assert.equal(stepIndex("queued"), 0);
  assert.equal(stepIndex("idle"), -1);
});

test("refusals from the server read as sentences", () => {
  assert.match(updateErrorText("admin_password_incorrect"), /isn't your admin password/);
  assert.match(updateErrorText("untrusted_setup"), /published release|signature/);
  assert.match(updateErrorText("not_newer"), /never installs the same or an older version/);
  assert.match(updateErrorText("no_checksums"), /no checksums/);
  assert.match(updateErrorText("too_many_attempts"), /15 minutes/);
  assert.equal(updateErrorText("who_knows", "Server said no."), "Server said no.");
  assert.equal(updateErrorText(null, null), "Something went wrong.");
});

test("why Update is unavailable", () => {
  assert.match(blockedText("no_checksums") ?? "", /no checksums/);
  assert.match(blockedText("helper_unavailable") ?? "", /updater/);
  assert.match(blockedText("running") ?? "", /already running/);
  assert.equal(blockedText(null), null);
});

test("byte sizes", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(34 * 1024 * 1024), "34 MB");
  assert.equal(formatBytes(2.5 * 1024 * 1024 * 1024), "2.5 GB");
  assert.equal(formatBytes(null), "");
});

test("last checked, in words", () => {
  const now = Date.parse("2026-10-07T12:00:00Z");
  assert.equal(checkedAgo(null, now), "never");
  assert.equal(checkedAgo("2026-10-07T11:59:40Z", now), "just now");
  assert.equal(checkedAgo("2026-10-07T11:55:00Z", now), "5 minutes ago");
  assert.equal(checkedAgo("2026-10-07T09:00:00Z", now), "3 hours ago");
  assert.equal(checkedAgo("2026-10-05T12:00:00Z", now), "2 days ago");
  assert.equal(checkedAgo("not a date", now), "never");
});

test("the password goes in a header as percent-encoded UTF-8", () => {
  assert.equal(encodePasswordHeader("plain"), "plain");
  assert.equal(encodePasswordHeader("päss wörd"), "p%C3%A4ss%20w%C3%B6rd");
  assert.equal(decodeURIComponent(encodePasswordHeader("a/b?c=d&e")), "a/b?c=d&e");
});

test("run summaries", () => {
  assert.match(runSummary({ phase: "done", from_version: "1.0.0", to_version: "1.1.0" }) ?? "", /Updated from 1\.0\.0 to 1\.1\.0/);
  assert.match(runSummary({ phase: "rolled_back", from_version: "1.0.0", to_version: "1.1.0" }) ?? "", /back to 1\.0\.0/);
  assert.match(runSummary({ phase: "failed", from_version: "1.0.0", to_version: "1.1.0" }) ?? "", /didn't finish/);
  assert.equal(runSummary({ phase: "idle", from_version: null, to_version: null }), null);
  assert.equal(runSummary({ phase: "installing", from_version: "1.0.0", to_version: "1.1.0" }), null);
});
