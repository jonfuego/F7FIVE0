// node:test coverage for the episode File info rows.
//
// Run: node --test frontend/lib/file-info.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { fileInfoRows } from "./file-info.ts";

const s02e01 = {
  path: "C:\\TV\\Test Show (2020)\\Season 02\\Test Show S02E01.mkv",
  container: "mkv",
  size_bytes: 9_437_184,
  video_codec: "hevc",
  audio_codec: "ac3",
  audio_channels: 6,
  width: 1920,
  height: 1080,
  bitrate_kbps: 2900,
};

test("seven rows in order, from the file itself", () => {
  const rows = fileInfoRows(s02e01);
  assert.deepEqual(rows.map((r) => r.label), [
    "Codec", "Bitrate", "Container", "Resolution", "Audio", "File size", "File path",
  ]);
  assert.deepEqual(rows.map((r) => r.value), [
    "HEVC", "2.9 Mbps", "MKV", "1920×1080", "AC3 5.1", "9.0 MB", s02e01.path,
  ]);
});

test("missing fields show a dash", () => {
  const rows = fileInfoRows({
    path: null, container: null, size_bytes: null, video_codec: null, audio_codec: null,
    audio_channels: null, width: null, height: null, bitrate_kbps: null,
  });
  assert.ok(rows.every((r) => r.value === "—"));
});

test("two episodes with different files give different rows", () => {
  const other = { ...s02e01, video_codec: "h264", width: 1280, height: 720, container: "mp4" };
  assert.notDeepEqual(fileInfoRows(s02e01), fileInfoRows(other));
});
