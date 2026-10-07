// Decides what the Home hero "Play" button does for each library kind.
// Pure so node:test can cover it (play-action.test.ts). The hero row only
// carries a kind + entity id; the component resolves the playable media
// file id (movie file, series on-deck / first episode, music video) and
// hands it here. Albums play in the dock and never navigate; every video
// kind resolves to the /watch/<media_file_id> route the detail pages use.

export type HeroKind = "movie" | "series" | "album" | "music_video";

export type PlayAction =
  // Start the album in the audio dock; stay on the page.
  | { type: "album" }
  // Navigate to the player route for a resolved media file.
  | { type: "watch"; href: string }
  // Nothing playable (no file on disk yet); the caller leaves Play inert.
  | { type: "none" };

/** Build the /watch route for a media file id. */
export function watchHref(mediaFileId: string): string {
  return `/watch/${mediaFileId}`;
}

/**
 * Resolve the hero Play action.
 *
 * - album: always a dock action (the component supplies the queue items).
 * - movie / series / music_video: a /watch route when a playable media
 *   file id is known, else "none".
 */
export function resolveHeroPlay(
  kind: HeroKind,
  mediaFileId: string | null | undefined,
): PlayAction {
  if (kind === "album") return { type: "album" };
  if (mediaFileId) return { type: "watch", href: watchHref(mediaFileId) };
  return { type: "none" };
}
