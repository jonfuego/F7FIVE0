// node:test coverage for the movie Version picker (hand test L-08): the
// default version, keeping the user's pick, and labels.
//
// Run: node --test frontend/lib/movie-versions.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { bestVersion, chosenVersion, readyVersions, versionLabels, type VersionFile } from "./movie-versions.ts";

function f(id: string, over: Partial<VersionFile> = {}): VersionFile {
  return {
    id, path: `C:\\Media\\Movies\\The Kid (1921)\\${id}.mkv`, scan_state: "ready",
    height: 1080, bitrate_kbps: 4000, video_codec: "h264", is_preferred: false, ...over,
  };
}

test("only ready files are versions", () => {
  const files = [f("a"), f("b", { scan_state: "missing" })];
  assert.deepEqual(readyVersions(files).map((x) => x.id), ["a"]);
  assert.deepEqual(readyVersions(null), []);
});

test("the best version plays by default: higher resolution, then bitrate, then codec", () => {
  assert.equal(bestVersion([f("sd", { height: 720 }), f("hd")])?.id, "hd");
  assert.equal(bestVersion([f("lo", { bitrate_kbps: 1000 }), f("hi")])?.id, "hi");
  assert.equal(bestVersion([f("avc"), f("hevc", { video_codec: "hevc" })])?.id, "hevc");
  assert.equal(bestVersion([]), null);
});

test("an admin-pinned version wins (the API field is is_preferred)", () => {
  const files = [f("hd"), f("copy", { height: 720, is_preferred: true })];
  assert.equal(bestVersion(files)?.id, "copy");
});

test("the picked version plays; a pick that is gone falls back to the default", () => {
  const files = [f("hd"), f("copy", { height: 720 })];
  assert.equal(chosenVersion(files, null)?.id, "hd");
  assert.equal(chosenVersion(files, "copy")?.id, "copy");
  assert.equal(chosenVersion(files, "gone")?.id, "hd");
});

test("labels show resolution and codec, the pin, and a file name only when two read the same", () => {
  const labels = versionLabels([
    f("The Kid (1921)"),
    f("The Kid (1921) - 720p copy", { height: 720, is_preferred: true }),
  ]);
  assert.equal(labels.get("The Kid (1921)"), "1080p H264");
  assert.equal(labels.get("The Kid (1921) - 720p copy"), "720p H264 (preferred)");

  const same = versionLabels([f("one"), f("two")]);
  assert.equal(same.get("one"), "1080p H264 - one.mkv");
  assert.equal(same.get("two"), "1080p H264 - two.mkv");
  assert.equal(versionLabels([f("x", { height: null, video_codec: null })]).get("x"), "Unknown");
});
