import type { QueueItemDTO } from "@/api/types";

/** The per-track metadata the player keeps in memory, parallel to the
 * track-player queue. */
export interface QueueSnapshotItem {
  mediaFileId: string;
  trackId?: string | null;
  title: string;
  artist?: string | null;
  album?: string | null;
  artPath?: string | null;
  durationSec?: number | null;
}

/** Convert the in-memory queue metas into the server queue payload
 * (PUT /api/queue). Pure and side-effect free so it can be unit tested. */
export function buildServerQueueItems(metas: QueueSnapshotItem[]): QueueItemDTO[] {
  return metas.map((m) => ({
    media_file_id: m.mediaFileId,
    title: m.title,
    track_id: m.trackId ?? null,
    artist_name: m.artist ?? null,
    album_title: m.album ?? null,
    cover_path: m.artPath ?? null,
    duration_sec: m.durationSec ?? null,
  }));
}

/** Clamp a current index into a queue of length n, or null when empty/invalid.
 * The backend rejects an out-of-range current_index, so callers must clamp
 * before PUT. */
export function clampCurrentIndex(index: number, n: number): number | null {
  if (n <= 0) return null;
  if (index < 0) return 0;
  if (index >= n) return n - 1;
  return index;
}

/** Whether a server queue snapshot should replace the local one on hydrate:
 * only when the local queue is empty and the server has items. */
export function shouldHydrateFromServer(localCount: number, serverCount: number): boolean {
  return localCount === 0 && serverCount > 0;
}
