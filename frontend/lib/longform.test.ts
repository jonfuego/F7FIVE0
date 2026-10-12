// node:test coverage for the shared long-form helpers (skip, played rule,
// chapter at a time, speed). Podcasts use them today; audiobooks can reuse them.
//
// Run: node --test frontend/lib/longform.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PLAYED_FRACTION, PLAYED_TAIL_SEC, SKIP_BACK_SEC, SKIP_FORWARD_SEC, SPEEDS,
  chapterAt, clampSpeed, formatSpeed, isPlayed, skipBack, skipForward,
} from "./longform.ts";

test("skip is back 15 s and forward 30 s", () => {
  assert.equal(SKIP_BACK_SEC, 15);
  assert.equal(SKIP_FORWARD_SEC, 30);
});

test("skip back stops at zero", () => {
  assert.equal(skipBack(50), 35);
  assert.equal(skipBack(10), 0);
  assert.equal(skipBack(0), 0);
});

test("skip forward stops at the end, and runs free when the length is unknown", () => {
  assert.equal(skipForward(10, 100), 40);
  assert.equal(skipForward(80, 100), 100);
  assert.equal(skipForward(100, 100), 100);
  assert.equal(skipForward(10, null), 40);
  assert.equal(skipForward(10, 0), 40);
  assert.equal(skipForward(10, undefined), 40);
});

test("played is within 30 s of the end or past 95 percent, whichever comes first", () => {
  assert.equal(PLAYED_TAIL_SEC, 30);
  assert.equal(PLAYED_FRACTION, 0.95);
  assert.equal(isPlayed(6839, 7200), false);
  assert.equal(isPlayed(6840, 7200), true); // long show: 95 percent first
  assert.equal(isPlayed(269, 300), false);
  assert.equal(isPlayed(270, 300), true); // short show: last 30 s first
  assert.equal(isPlayed(569, 600), false);
  assert.equal(isPlayed(570, 600), true);
  assert.equal(isPlayed(0, 100), false);
});

test("played needs a known length", () => {
  assert.equal(isPlayed(5000, 0), false);
  assert.equal(isPlayed(5000, null), false);
  assert.equal(isPlayed(5000, undefined), false);
});

test("chapter at a time", () => {
  const ch = [
    { start_sec: 0, title: "A" },
    { start_sec: 60, title: "B" },
    { start_sec: 300, title: "C" },
  ];
  assert.equal(chapterAt(ch, 0), 0);
  assert.equal(chapterAt(ch, 59.9), 0);
  assert.equal(chapterAt(ch, 60), 1);
  assert.equal(chapterAt(ch, 10_000), 2);
  assert.equal(chapterAt(ch, -3), 0);
  assert.equal(chapterAt([], 10), -1);
  assert.equal(chapterAt([{ start_sec: 30, title: "late" }], 10), -1);
});

test("speed is held between 0.5 and 3", () => {
  assert.equal(clampSpeed(1), 1);
  assert.equal(clampSpeed(0.25), 0.5);
  assert.equal(clampSpeed(4), 3);
  assert.equal(clampSpeed(Number.NaN), 1);
  assert.equal(SPEEDS[0], 0.5);
  assert.equal(SPEEDS[SPEEDS.length - 1], 3);
  assert.ok(SPEEDS.includes(1));
  assert.equal(formatSpeed(1), "1x");
  assert.equal(formatSpeed(1.25), "1.25x");
  assert.equal(formatSpeed(2), "2x");
});
