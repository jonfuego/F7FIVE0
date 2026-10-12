// node:test coverage for turning an episode into an audio dock queue item.
//
// Run: node --test frontend/lib/podcast-queue.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { episodeToQueueItem, podcastShowHref } from "./podcast-queue.ts";
import { isPodcastItem } from "./podcast-player.ts";

const ep = {
  id: "ep-1", podcast_id: "show-1", podcast_title: "The Fixture Show",
  art_url: "/api/art/podcast/show-1/cover?v=1", title: "Episode Three", duration_sec: 3723,
};

test("an episode becomes a podcast queue item keyed by its own id", () => {
  const item = episodeToQueueItem(ep);
  assert.equal(item.kind, "podcast");
  assert.equal(item.media_file_id, "ep-1");
  assert.equal(item.podcast_id, "show-1");
  assert.equal(item.title, "Episode Three");
  assert.equal(item.artist_name, "The Fixture Show");
  assert.equal(item.album_title, null);
  assert.equal(item.cover_path, "/api/art/podcast/show-1/cover?v=1");
  assert.equal(item.duration_sec, 3723);
  assert.equal(isPodcastItem(item), true);
});

test("the dock links an episode to its show page", () => {
  assert.equal(podcastShowHref(episodeToQueueItem(ep)), "/podcasts/show-1");
  assert.equal(podcastShowHref({}), null);
});
