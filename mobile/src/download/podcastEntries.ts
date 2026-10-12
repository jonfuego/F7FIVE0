/** Bridges between podcast episodes and download records. Pure, so it unit
 * tests in Node. An episode download is keyed by the episode id (never a URL),
 * sources from the signed /stream/podcast URL (so it works whether or not the
 * server has the file) and carries enough metadata to play offline with no
 * catalogue request. */
import type { PodcastEpisodeRow, PodcastShowRef } from "@/api/types";
import type { DownloadEntry } from "./entries";
import type { DownloadItem, DownloadKind } from "./queue";

/** API path that mints the signed /stream/podcast URL for an episode. */
export function podcastDownloadPath(episodeId: string): string {
  return `/api/podcasts/episodes/${encodeURIComponent(episodeId)}/stream`;
}

/** Where a download of this kind gets its signed URL: a podcast episode from the
 * podcast stream endpoint, everything else from the media file download endpoint. */
export function downloadSource(kind?: DownloadKind): "podcast" | "media" {
  return kind === "podcast" ? "podcast" : "media";
}

/** Download entry for an episode of a show. */
export function episodeEntry(ep: PodcastEpisodeRow, show: PodcastShowRef): DownloadEntry {
  if (!ep.id) throw new Error("episode has no id");
  return {
    mediaFileId: ep.id,
    title: ep.title,
    opts: {
      kind: "podcast",
      meta: {
        episodeId: ep.id,
        podcastId: ep.podcast_id || show.id,
        artist: show.title,
        album: show.title,
        coverPath: show.art_url ?? null,
        durationSec: ep.duration_sec ?? null,
        container: ep.container ?? null,
        group: show.title,
      },
    },
  };
}

/** An episode that was downloaded to the device, ready to play offline. */
export interface LocalEpisode {
  id: string;
  title: string;
  showTitle: string;
  podcastId: string | null;
  coverPath: string | null;
  durationSec: number | null;
  localPath: string;
}

/** Rebuild a playable episode from a finished download. */
export function downloadToEpisode(it: DownloadItem): LocalEpisode {
  const m = it.meta ?? {};
  return {
    id: m.episodeId ?? it.id,
    title: it.title,
    showTitle: m.album ?? m.artist ?? "",
    podcastId: m.podcastId ?? null,
    coverPath: m.coverPath ?? null,
    durationSec: m.durationSec ?? null,
    localPath: it.localPath ?? "",
  };
}
