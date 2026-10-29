// node:test coverage for the watch page title source.
//
// Run: node --test frontend/lib/watch-title.test.ts
//
// Hand-test bug: opening a movie's /watch page while a music track was current
// in the dock queue showed the song's title ("Talk About The Passion") in the
// top bar instead of the movie ("The Kid").

import { test } from "node:test";
import assert from "node:assert/strict";
import { watchTitle, WATCH_TITLE_LOADING } from "./watch-title.ts";

const song = { media_file_id: "song-1", title: "Talk About The Passion" };

test("movie page with an unrelated song queued never shows the song (stream loading)", () => {
  assert.equal(
    watchTitle({ mediaFileId: "movie-1", streamTitle: null, queueCurrent: song, useDockAudio: false }),
    WATCH_TITLE_LOADING,
  );
});

test("movie page shows the stream title once loaded, even with a song queued", () => {
  assert.equal(
    watchTitle({ mediaFileId: "movie-1", streamTitle: "The Kid (1921)", queueCurrent: song, useDockAudio: false }),
    "The Kid (1921)",
  );
});

test("a stream with no title does not fall back to an unrelated queue item", () => {
  for (const streamTitle of [null, undefined, "", "   "]) {
    assert.equal(
      watchTitle({ mediaFileId: "movie-1", streamTitle, queueCurrent: song, useDockAudio: false }),
      WATCH_TITLE_LOADING,
    );
  }
});

test("dock-linked audio uses the queue item title (no stream is started)", () => {
  assert.equal(
    watchTitle({ mediaFileId: "song-1", streamTitle: undefined, queueCurrent: song, useDockAudio: true }),
    "Talk About The Passion",
  );
});

test("following the queue to the next track uses the queue title before the route catches up", () => {
  const next = { media_file_id: "song-2", title: "Next Song" };
  assert.equal(
    watchTitle({ mediaFileId: "song-1", streamTitle: undefined, queueCurrent: next, useDockAudio: true }),
    "Next Song",
  );
});

test("queue item for this same file is a valid fallback while its stream loads", () => {
  assert.equal(
    watchTitle({ mediaFileId: "song-1", streamTitle: null, queueCurrent: song, useDockAudio: false }),
    "Talk About The Passion",
  );
});

test("nothing known yet shows the loading label", () => {
  assert.equal(
    watchTitle({ mediaFileId: "movie-1", streamTitle: null, queueCurrent: null, useDockAudio: false }),
    WATCH_TITLE_LOADING,
  );
});
