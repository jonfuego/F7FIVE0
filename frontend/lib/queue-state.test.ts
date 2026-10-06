// node:test coverage for the audio queue reducer's `playing` flag.
//
// Run: node --test frontend/lib/queue-state.test.ts
//
// The dock honors the persisted `playing` flag for the first stream after a
// page load, so a restored queue doesn't start on its own. Starting playback
// by hand (Play on an album, a song, a queue row) must therefore mark the
// queue as playing, or the first track after a page load sits at 0:00.

import { test } from "node:test";
import assert from "node:assert/strict";
import { INITIAL_STATE, reducer, type QueueItem, type State } from "./queue-state.ts";

function item(id: string): QueueItem {
  return {
    media_file_id: id,
    title: `Track ${id}`,
    artist_name: null,
    album_title: null,
    cover_path: null,
    duration_sec: 300,
  };
}

const restoredPaused: State = {
  ...INITIAL_STATE,
  items: [item("a"), item("b"), item("c")],
  currentIndex: 0,
  playing: false,
};

test("playNow on an empty queue marks the queue playing", () => {
  const s = reducer(INITIAL_STATE, { type: "playNow", item: item("a") });
  assert.equal(s.currentIndex, 0);
  assert.equal(s.playing, true);
});

test("playAlbum marks the queue playing", () => {
  const s = reducer(INITIAL_STATE, { type: "playAlbum", items: [item("a"), item("b")], shuffle: false });
  assert.equal(s.playing, true);
});

test("skipTo on a restored, paused queue marks it playing", () => {
  const s = reducer(restoredPaused, { type: "skipTo", index: 2 });
  assert.equal(s.currentIndex, 2);
  assert.equal(s.playing, true);
});

test("playNext / playNextBlock / addToQueue that start an empty queue mark it playing", () => {
  assert.equal(reducer(INITIAL_STATE, { type: "playNext", item: item("a") }).playing, true);
  assert.equal(reducer(INITIAL_STATE, { type: "playNextBlock", items: [item("a")] }).playing, true);
  assert.equal(reducer(INITIAL_STATE, { type: "addToQueue", items: [item("a")] }).playing, true);
});

test("adding to a queue that already has a current track leaves playing alone", () => {
  assert.equal(reducer(restoredPaused, { type: "addToQueue", items: [item("d")] }).playing, false);
  assert.equal(reducer(restoredPaused, { type: "playNext", item: item("d") }).playing, false);
});

test("hydrate keeps the restored flag, so a restored paused queue does not start on its own", () => {
  const s = reducer(INITIAL_STATE, { type: "hydrate", state: restoredPaused });
  assert.equal(s.playing, false);
});

test("clear stops playing", () => {
  const playing = reducer(INITIAL_STATE, { type: "playNow", item: item("a") });
  assert.equal(reducer(playing, { type: "clear" }).playing, false);
});
