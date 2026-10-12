// node:test coverage for the audio dock in podcast mode: which controls show,
// the chapter line, and when progress is saved.
//
// Run: node --test frontend/lib/podcast-player.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PROGRESS_SAVE_MS, currentChapterTitle, dockControls, isPodcastItem, shouldSaveProgress,
} from "./podcast-player.ts";

const podcast = { kind: "podcast", media_file_id: "ep-1" };
const track = { media_file_id: "mf-1" };

test("only an item marked as a podcast episode is podcast mode", () => {
  assert.equal(isPodcastItem(podcast), true);
  assert.equal(isPodcastItem(track), false);
  assert.equal(isPodcastItem(null), false);
  assert.equal(isPodcastItem(undefined), false);
});

test("a song keeps previous and next and shows no podcast controls", () => {
  assert.deepEqual(dockControls(track, 0), {
    showPrevNext: true, skipBackSec: null, skipForwardSec: null,
    showSpeed: false, showChapters: false, showMarkPlayed: false,
  });
});

test("an episode swaps previous and next for -15 and +30 and adds speed and mark played", () => {
  assert.deepEqual(dockControls(podcast, 0), {
    showPrevNext: false, skipBackSec: 15, skipForwardSec: 30,
    showSpeed: true, showChapters: false, showMarkPlayed: true,
  });
});

test("the chapter list shows only when the episode has chapters", () => {
  assert.equal(dockControls(podcast, 0).showChapters, false);
  assert.equal(dockControls(podcast, 4).showChapters, true);
});

test("the current chapter title follows the playhead", () => {
  const ch = [{ start_sec: 0, title: "Intro" }, { start_sec: 120, title: "Interview" }];
  assert.equal(currentChapterTitle(ch, 5), "Intro");
  assert.equal(currentChapterTitle(ch, 125), "Interview");
  assert.equal(currentChapterTitle([], 5), null);
  assert.equal(currentChapterTitle(ch, -1), "Intro");
});

test("progress is saved every 15 s while playing, and always on pause and end", () => {
  assert.equal(PROGRESS_SAVE_MS, 15_000);
  assert.equal(shouldSaveProgress("tick", 0, 14_999), false);
  assert.equal(shouldSaveProgress("tick", 0, 15_000), true);
  assert.equal(shouldSaveProgress("pause", 1_000, 2_000), true);
  assert.equal(shouldSaveProgress("ended", 1_000, 1_001), true);
});
