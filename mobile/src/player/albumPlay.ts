// Pure helper that maps an album detail to the player's SongRow queue, so an
// album can be played from a tile (Home, Albums) the same way the album
// screen does. Kept free of React / the API client so jest can cover it
// (albumPlay.test.ts). The screens fetch the detail, call this, then hand the
// rows to player.playSongs(rows, 0).

import type { AlbumDetail, SongRow } from "@/api/types";

/** Album tracks as player song rows, in track order as the detail returns
 * them. Mirrors the mapping used by the album screen and Android Auto. */
export function albumToSongs(detail: AlbumDetail): SongRow[] {
  return detail.tracks.map((t) => ({
    id: t.id,
    title: t.title,
    track_number: t.track_number,
    disc_number: t.disc_number,
    duration_sec: t.duration_sec,
    album_id: detail.id,
    album_title: detail.title,
    cover_path: detail.cover_path,
    artist_id: detail.artist_id,
    artist_name: detail.artist_name ?? "",
    media_files: t.media_files,
  }));
}

/** True when the album has at least one track with a playable media file. */
export function albumIsPlayable(detail: AlbumDetail): boolean {
  return albumToSongs(detail).some((s) => s.media_files.length > 0);
}
