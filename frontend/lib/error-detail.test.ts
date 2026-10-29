// node:test coverage for the API error text helper.
//
// Run: node --test frontend/lib/error-detail.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { detailText, errorText } from "./error-detail.ts";

test("drops the machine code in front of a sentence (Fix Match refusal)", () => {
  const raw =
    "already_matched: Queen (music library) already uses this MusicBrainz artist. " +
    "Merge the two artists instead (Merge into... on the artist page).";
  assert.equal(
    detailText(raw),
    "Queen (music library) already uses this MusicBrainz artist. " +
      "Merge the two artists instead (Merge into... on the artist page).",
  );
});

test("keeps a bare code and plain sentences as they are", () => {
  assert.equal(detailText("override_not_found"), "override_not_found");
  assert.equal(detailText("image exceeds 10 MB cap"), "image exceeds 10 MB cap");
  // A colon later in a sentence is not a code prefix.
  assert.equal(detailText("Bad URL: https://x.test"), "Bad URL: https://x.test");
  assert.equal(detailText("C:\\Media is outside"), "C:\\Media is outside");
});

test("errorText reads an ApiError-shaped value, an Error, or falls back", () => {
  assert.equal(
    errorText({ status: 409, detail: "already_matched: X already uses this.", message: "HTTP 409" }, "f"),
    "X already uses this.",
  );
  assert.match(
    errorText({ status: 503, detail: "session_refresh_unavailable" }, "f"),
    /still signed in/,
  );
  assert.equal(errorText({ status: 500, detail: null, message: "HTTP 500" }, "f"), "HTTP 500");
  assert.equal(errorText(new Error("Failed to fetch"), "f"), "Failed to fetch");
  assert.equal(errorText(null, "Upload failed."), "Upload failed.");
});

// A-12: the File info sheet on the movie page sits inside the uppercase
// kicker, so the file path rendered as C:\MEDIA\MOVIES\... The sheet's root
// must reset the inherited text transform.
test("File info sheet resets the kicker's uppercase", () => {
  const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
  const block = /\.detail \.ep-info-scrim \{([^}]*)\}/.exec(css);
  assert.ok(block, "the .ep-info-scrim rule exists");
  assert.match(block[1], /text-transform:\s*none/);
  assert.match(block[1], /letter-spacing:\s*normal/);
});
