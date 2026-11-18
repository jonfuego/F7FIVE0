import type { ContinueWatchingItem } from "@/api/types";
import type { PlayableEpisode } from "@/player/PlayerProvider";

/** What tapping a Continue rail tile does. Pure, so it is unit tested.
 *
 * A podcast episode plays in the audio player by its episode id (the server
 * relays the publisher's file when it has none of its own) and resumes where
 * the person left off, so `resumeSec` is left out and the player asks. Every
 * other kind opens the video or track player on its media file. */
export type ContinueTarget =
  | { type: "episode"; episode: PlayableEpisode }
  | { type: "watch"; href: string }
  | { type: "none" };

export function continueTarget(it: ContinueWatchingItem): ContinueTarget {
  if (it.kind === "podcast_episode") {
    return {
      type: "episode",
      episode: {
        id: it.id,
        podcastId: it.podcast_id ?? null,
        title: it.title,
        showTitle: it.subtitle ?? "",
        coverPath: it.poster_path ?? null,
        durationSec: it.duration_sec ?? null,
      },
    };
  }
  if (it.media_file_id) return { type: "watch", href: `/watch/${it.media_file_id}` };
  return { type: "none" };
}

/** Podcast covers are square; the rail's 16:9 frame shows them whole. */
export function continueArtFit(it: ContinueWatchingItem): "cover" | "contain" {
  return it.kind === "podcast_episode" ? "contain" : "cover";
}
