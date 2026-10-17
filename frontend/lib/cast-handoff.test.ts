// node:test guard for the web cast hand-off decisions and wiring.
// Run: node --test frontend/lib/cast-handoff.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  castDurationSec,
  castMintBody,
  castStartTime,
  localResumeSec,
  receiverSourceSec,
  timelineBase,
} from "./cast-handoff.ts";

const direct = { mode: "direct" as const };
const hls0 = { mode: "hls" as const, timeline_offset_sec: 0 };
const hls750 = { mode: "hls" as const, timeline_offset_sec: 750 };

test("timelineBase: direct is absolute, hls uses the bucket, old backend falls back", () => {
  assert.equal(timelineBase(direct), 0);
  assert.equal(timelineBase(hls750), 750);
  assert.equal(timelineBase({ mode: "hls", offset_sec: 300 }), 300);
  assert.equal(timelineBase({ mode: "hls" }), 0);
});

test("castMintBody asks for a cast stream at the current second", () => {
  assert.deepEqual(castMintBody("f1", 754.9), { file_id: "f1", purpose: "cast", resume_sec: 754 });
  assert.deepEqual(castMintBody("f1", 0), { file_id: "f1", purpose: "cast" });
});

test("castStartTime is relative to the cast stream", () => {
  assert.equal(castStartTime(754, hls750), 4);
  assert.equal(castStartTime(750, hls750), undefined);
  assert.equal(castStartTime(120, direct), 120);
  assert.equal(castStartTime(0, direct), undefined);
});

test("castDurationSec drops the bucket", () => {
  assert.equal(castDurationSec(7200, hls750), 6450);
  assert.equal(castDurationSec(7200, direct), 7200);
  assert.equal(castDurationSec(null, hls750), null);
});

test("receiverSourceSec adds the bucket back", () => {
  assert.equal(receiverSourceSec(60, hls750), 810);
  assert.equal(receiverSourceSec(-5, direct), 0);
});

test("localResumeSec maps the receiver's place onto the local clock", () => {
  // Receiver at 60 s of a stream that began at 750 -> source 810; local stream
  // began at 0, so the element resumes at 810.
  assert.equal(localResumeSec(60, hls750, hls0, 30), 810);
  // Local stream also resumed from 600: the element clock is 210.
  assert.equal(localResumeSec(60, hls750, { mode: "hls", timeline_offset_sec: 600 }, 30), 210);
  // Direct local stream is absolute.
  assert.equal(localResumeSec(60, hls750, direct, 30), 810);
});

test("localResumeSec falls back to the local time and never goes negative", () => {
  assert.equal(localResumeSec(null, hls750, hls0, 42), 42);
  assert.equal(localResumeSec(0, hls750, hls0, 42), 42);
  assert.equal(localResumeSec(undefined, hls750, hls0, Number.NaN), 0);
  assert.equal(localResumeSec(10, hls0, { mode: "hls", timeline_offset_sec: 900 }, 5), 0);
});

const player = readFileSync(new URL("../components/Player.tsx", import.meta.url), "utf8");

test("Player mints a cast stream on connect and never hands the receiver the local url", () => {
  assert.match(player, /castMintBody\(/);
  assert.match(player, /apiPost<StreamStart>\(\s*"\/api\/stream\/start"/);
  assert.ok(!/contentUrl: toAbsolute\(stream\.url\)/.test(player), "loadMedia must not use the local stream url");
});

test("Player stops local hls.js loading while casting and restarts it on disconnect", () => {
  assert.match(player, /\.stopLoad\(\)/);
  assert.match(player, /\.startLoad\(/);
});
