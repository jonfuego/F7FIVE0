// node:test coverage for the browser capability report sent with
// /api/stream/start.
//
// Run: node --test frontend/lib/playback-caps.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { detectClientCaps } from "./playback-caps.ts";

// canPlayType answers Chrome 154 gave on the dev PC (2026-10-05).
const CHROME: Record<string, string> = {
  'video/mp4; codecs="avc1.640028, mp4a.40.2"': "probably",
  'video/x-matroska; codecs="avc1.640028, mp4a.40.2"': "probably",
  'video/webm; codecs="vp9, opus"': "probably",
  'video/mp4; codecs="avc1.640028"': "probably",
  'video/mp4; codecs="hvc1.1.6.L120.90"': "probably",
  'video/webm; codecs="vp9"': "probably",
  'audio/mp4; codecs="mp4a.40.2"': "probably",
  "audio/mpeg": "probably",
  'audio/webm; codecs="opus"': "probably",
  "audio/flac": "probably",
};

test("Chrome reports H.264 + AAC in MKV", () => {
  const caps = detectClientCaps((t) => CHROME[t] ?? "");
  assert.ok(caps.containers.includes("mkv"));
  assert.ok(caps.containers.includes("mp4"));
  assert.ok(caps.video_codecs.includes("h264"));
  assert.ok(caps.audio_codecs.includes("aac"));
  assert.ok(!caps.audio_codecs.includes("ac3"));
});

test("a codec probe answered 'maybe' does not count", () => {
  const caps = detectClientCaps((t) => (t.startsWith("video/x-matroska") ? "maybe" : ""));
  assert.deepEqual(caps.containers, []);
});

test("a bare audio MIME type answered 'maybe' counts", () => {
  const caps = detectClientCaps((t) => (t === "audio/mpeg" ? "maybe" : ""));
  assert.deepEqual(caps.audio_codecs, ["mp3"]);
});

test("a browser that plays nothing reports nothing", () => {
  assert.deepEqual(detectClientCaps(() => ""), { containers: [], video_codecs: [], audio_codecs: [] });
});

test("a throwing canPlayType is treated as no", () => {
  const caps = detectClientCaps(() => {
    throw new Error("boom");
  });
  assert.deepEqual(caps.containers, []);
});
