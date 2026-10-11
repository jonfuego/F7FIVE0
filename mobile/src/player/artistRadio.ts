// Pure pieces of "Artist radio" on the album screen, kept free of React and
// the API client so jest can cover them (artistRadio.test.ts). The screen
// supplies the fetch (fetchAutoPlaylistById with "artist-radio", the same call
// the artist screen and the player menu make) and the player's playSongs.

import type { AlbumDetail, SongRow } from "@/api/types";

/** The artist to start radio for, or null when the album has none (the screen
 * hides the action then). */
export function artistRadioId(detail: Pick<AlbumDetail, "artist_id">): string | null {
  const id = detail.artist_id?.trim();
  return id ? id : null;
}

export type ArtistRadioOutcome = "started" | "empty" | "failed";

/** Load the radio and hand a non-empty result to play. A failed load is
 * reported as an outcome instead of thrown, so the screen can say so. */
export async function startArtistRadio(
  load: () => Promise<SongRow[]>,
  play: (songs: SongRow[]) => void,
): Promise<ArtistRadioOutcome> {
  let songs: SongRow[];
  try {
    songs = await load();
  } catch {
    return "failed";
  }
  if (songs.length === 0) return "empty";
  play(songs);
  return "started";
}

/** Message to show for an outcome, or null when playback started. */
export function artistRadioNotice(outcome: ArtistRadioOutcome): string | null {
  if (outcome === "failed") return "Could not start artist radio.";
  if (outcome === "empty") return "No artist radio is available for this artist yet.";
  return null;
}
