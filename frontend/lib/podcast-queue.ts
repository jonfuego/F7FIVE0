// A podcast episode as an audio-dock queue item. The dock plays songs and
// episodes from one queue; an episode carries kind "podcast" and puts its own id
// in `media_file_id`, so every item keeps one unique key. The show title stands
// in for the artist and the show's art for the cover.
//
// Pure, so node:test covers it (podcast-queue.test.ts).

import type { QueueItem } from "./queue-state.ts";

type EpisodeLike = {
  id: string;
  podcast_id: string;
  podcast_title: string;
  art_url: string | null;
  title: string;
  duration_sec: number | null;
};

export function episodeToQueueItem(ep: EpisodeLike): QueueItem {
  return {
    kind: "podcast",
    media_file_id: ep.id,
    podcast_id: ep.podcast_id,
    title: ep.title,
    artist_name: ep.podcast_title,
    album_title: null,
    cover_path: ep.art_url,
    duration_sec: ep.duration_sec,
  };
}

/** Where the dock's title and cover link to: the show page for an episode. */
export function podcastShowHref(item: { podcast_id?: string | null }): string | null {
  return item.podcast_id ? `/podcasts/${item.podcast_id}` : null;
}
