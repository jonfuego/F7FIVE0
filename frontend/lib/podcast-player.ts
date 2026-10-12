// The audio dock in podcast mode: which controls it shows, the chapter line
// and when progress is saved. The dock (components/MiniPlayer.tsx) asks these
// pure functions instead of branching inline, so node:test covers the rules
// (podcast-player.test.ts).
//
// An item is a podcast episode when it carries kind "podcast". Its
// `media_file_id` holds the episode id, so the queue keeps one key per item.

import { SKIP_BACK_SEC, SKIP_FORWARD_SEC, chapterAt, type Chapter } from "./longform.ts";
import type { PodcastStreamStart, StreamStart } from "./types.ts";

/** How often progress is saved while an episode plays. */
export const PROGRESS_SAVE_MS = 15_000;

/** A saved position under this many seconds is not worth resuming from. */
export const RESUME_MIN_SEC = 5;

export function isPodcastItem(item: { kind?: string | null } | null | undefined): boolean {
  return item?.kind === "podcast";
}

export type DockControls = {
  /** Previous and next track (songs). */
  showPrevNext: boolean;
  /** Skip back / forward in seconds, or null when the dock has no skip button. */
  skipBackSec: number | null;
  skipForwardSec: number | null;
  showSpeed: boolean;
  showChapters: boolean;
  showMarkPlayed: boolean;
};

/** A song keeps previous and next. An episode swaps them for -15 and +30, and
 *  adds the speed menu, mark played and, when it has chapters, the chapter list. */
export function dockControls(
  item: { kind?: string | null } | null | undefined,
  chapterCount: number,
): DockControls {
  if (!isPodcastItem(item)) {
    return {
      showPrevNext: true, skipBackSec: null, skipForwardSec: null,
      showSpeed: false, showChapters: false, showMarkPlayed: false,
    };
  }
  return {
    showPrevNext: false, skipBackSec: SKIP_BACK_SEC, skipForwardSec: SKIP_FORWARD_SEC,
    showSpeed: true, showChapters: chapterCount > 0, showMarkPlayed: true,
  };
}

/** The title of the chapter playing now, or null when there is none. */
export function currentChapterTitle(chapters: readonly Chapter[], positionSec: number): string | null {
  const i = chapterAt(chapters, positionSec);
  return i >= 0 ? chapters[i].title : null;
}

export type SaveEvent = "tick" | "pause" | "ended";

/** Whether to save progress now: a tick only when 15 s have passed since the
 *  last save; a pause or the end always. */
export function shouldSaveProgress(event: SaveEvent, lastSavedAtMs: number, nowMs: number): boolean {
  if (event !== "tick") return true;
  return nowMs - lastSavedAtMs >= PROGRESS_SAVE_MS;
}

/** Where to start an episode: the saved position, unless it is only a few
 *  seconds in (then from the top). */
export function resumePosition(savedSec: number | null | undefined): number {
  return savedSec != null && savedSec >= RESUME_MIN_SEC ? Math.floor(savedSec) : 0;
}

/** The dock plays everything through one StreamStart shape. An episode is always
 *  a direct stream: the gateway serves the server copy or relays the publisher. */
export function streamFromPodcast(data: PodcastStreamStart): StreamStart {
  return {
    media_file_id: data.episode_id,
    mode: "direct",
    url: data.url,
    expires_at: data.expires_at,
    variant: null,
    title: data.title,
    duration_sec: data.duration_sec,
    container: data.container,
    video_codec: null,
    audio_codec: null,
    width: null,
    height: null,
    cover_path: data.cover_path,
    artist_name: data.podcast_title,
    album_title: null,
  };
}
