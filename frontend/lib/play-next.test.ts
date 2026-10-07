// node:test coverage for Play next: inserting a block (one track or several)
// directly after the current item without disturbing the track that is playing.
//
// Run: node --test frontend/lib/play-next.test.ts
//
// The track menu's "Play next" and the album page's "Play next" button both
// dispatch playNextBlock. The invariant people rely on is that the current
// track keeps playing and the picked track lands as the very next one up, so
// these tests pin currentIndex and the surrounding order after the splice.

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

const playing: State = {
  ...INITIAL_STATE,
  items: [item("a"), item("b"), item("c")],
  currentIndex: 1,
  playing: true,
};

test("Play next of one track lands directly after the current item and leaves it playing", () => {
  const s = reducer(playing, { type: "playNextBlock", items: [item("x")] });
  // Current track is unchanged and still the one playing.
  assert.equal(s.items[s.currentIndex as number].media_file_id, "b");
  assert.equal(s.currentIndex, 1);
  assert.equal(s.playing, true);
  // The picked track is the very next one up.
  assert.equal(s.items[(s.currentIndex as number) + 1].media_file_id, "x");
  // Nothing else is reordered.
  assert.deepEqual(
    s.items.map((i) => i.media_file_id),
    ["a", "b", "x", "c"],
  );
});

test("Play next of a block inserts the whole block after the current item in order", () => {
  const s = reducer(playing, { type: "playNextBlock", items: [item("x"), item("y")] });
  assert.equal(s.currentIndex, 1);
  assert.deepEqual(
    s.items.map((i) => i.media_file_id),
    ["a", "b", "x", "y", "c"],
  );
});

test("Play next onto an empty queue starts playback from the block", () => {
  const s = reducer(INITIAL_STATE, { type: "playNextBlock", items: [item("x")] });
  assert.equal(s.currentIndex, 0);
  assert.equal(s.playing, true);
  assert.equal(s.items[0].media_file_id, "x");
});
