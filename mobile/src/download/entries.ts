/** Bridges between catalogue rows and download records (crit 42/43). Pure, so
 * unit-testable. A download carries enough metadata (kind + meta) to be played
 * offline without any catalogue request. */
import type { SongRow } from "@/api/types";
import type { DownloadItem } from "./queue";
import type { EnqueueOptions } from "./DownloadProvider";

export interface DownloadEntry {
  mediaFileId: string;
  title: string;
  opts: EnqueueOptions;
}

/** Download entry for a song row (single song, album track, mix track). */
export function songEntry(s: SongRow, group?: string | null): DownloadEntry | null {
  const mf = s.media_files[0];
  if (!mf) return null;
  return {
    mediaFileId: mf.id,
    title: s.title,
    opts: {
      kind: "track",
      meta: {
        trackId: s.id,
        artist: s.artist_name,
        album: s.album_title,
        albumId: s.album_id,
        coverPath: s.cover_path ?? null,
        durationSec: s.duration_sec ?? null,
        container: mf.container ?? null,
        group: group ?? null,
      },
    },
  };
}

/** Entries for a list of songs (album, mix), skipping rows without a file. */
export function songEntries(songs: SongRow[], group?: string | null): DownloadEntry[] {
  return songs.map((s) => songEntry(s, group)).filter((e): e is DownloadEntry => e !== null);
}

/** Rebuild a playable SongRow from a finished track download (offline play). */
export function downloadToSong(it: DownloadItem): SongRow {
  const m = it.meta ?? {};
  return {
    id: m.trackId ?? it.id,
    title: it.title,
    duration_sec: m.durationSec ?? null,
    album_id: m.albumId ?? "",
    album_title: m.album ?? "",
    cover_path: m.coverPath ?? null,
    artist_id: "",
    artist_name: m.artist ?? "",
    media_files: [{ id: it.id, container: m.container ?? null }],
  };
}
