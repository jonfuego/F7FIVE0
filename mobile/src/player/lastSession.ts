/** The last thing that played, kept on the phone so playback can be rebuilt
 * after the native player lost it.
 *
 * Why: when the car is switched off the app sits paused in the background, and
 * Android may end its process. The native queue is then empty: a Play from the
 * car or the headset had nothing to play, and a cold start showed no queue at
 * all. The playback service and the car bridge now rebuild the session from
 * this record (the podcast episode at its place, or the music queue at its
 * track and position) instead of calling play() on an empty player.
 *
 * Pure (no native imports), so it unit tests in Node. PlayerProvider stores it
 * in AsyncStorage under LAST_SESSION_KEY. */
import type { QueueDTO, SongRow } from "@/api/types";
import type { QueueMeta } from "./nowPlayingFromTrack";

export const LAST_SESSION_KEY = "lastSession";

/** What playEpisode needs to start an episode again. */
export interface SessionEpisode {
  id: string;
  podcastId?: string | null;
  title: string;
  showTitle: string;
  coverPath?: string | null;
  durationSec?: number | null;
}

export interface PodcastSession {
  kind: "podcast";
  episode: SessionEpisode;
  positionSec: number;
  /** When the position was read from the native player. */
  recordedAtMs: number;
}

export interface MusicSession {
  kind: "music";
  /** The queue as it was (music only), in queue order. */
  items: QueueMeta[];
  /** The track that was playing, an index into `items`. */
  index: number;
  positionSec: number;
  recordedAtMs: number;
}

export type LastSession = PodcastSession | MusicSession;

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function isStr(v: unknown): v is string {
  return typeof v === "string" && v.length > 0;
}

/** Validate a stored record (it comes back from storage as plain JSON, maybe
 * from an older app). Anything unusable is null. */
export function parseLastSession(raw: unknown): LastSession | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (!isNum(o.positionSec) || !isNum(o.recordedAtMs)) return null;
  const positionSec = Math.max(0, o.positionSec);
  if (o.kind === "podcast") {
    const ep = o.episode as Record<string, unknown> | undefined;
    if (!ep || !isStr(ep.id) || typeof ep.title !== "string") return null;
    return {
      kind: "podcast",
      episode: {
        id: ep.id,
        podcastId: typeof ep.podcastId === "string" ? ep.podcastId : null,
        title: ep.title,
        showTitle: typeof ep.showTitle === "string" ? ep.showTitle : "",
        coverPath: typeof ep.coverPath === "string" ? ep.coverPath : null,
        durationSec: isNum(ep.durationSec) ? ep.durationSec : null,
      },
      positionSec,
      recordedAtMs: o.recordedAtMs,
    };
  }
  if (o.kind === "music") {
    if (!Array.isArray(o.items) || !isNum(o.index)) return null;
    const items = (o.items as unknown[]).filter(
      (m): m is QueueMeta =>
        !!m && typeof m === "object" && isStr((m as QueueMeta).mediaFileId) && (m as QueueMeta).kind !== "podcast",
    );
    if (items.length === 0) return null;
    const index = Math.min(Math.max(0, Math.floor(o.index)), items.length - 1);
    return { kind: "music", items, index, positionSec, recordedAtMs: o.recordedAtMs };
  }
  return null;
}

/** Queue items from the server queue (GET /api/queue) as queue metas. */
export function metasFromServerQueue(q: QueueDTO | null | undefined): QueueMeta[] {
  if (!q || !Array.isArray(q.items)) return [];
  return q.items
    .filter((i) => isStr(i.media_file_id))
    .map((i) => ({
      mediaFileId: i.media_file_id,
      trackId: i.track_id ?? null,
      title: i.title,
      artist: i.artist_name ?? null,
      album: i.album_title ?? null,
      albumId: i.album_id ?? null,
      artistId: i.artist_id ?? null,
      artPath: i.cover_path ?? null,
      durationSec: i.duration_sec ?? null,
    }));
}

/** What to rebuild on launch or on a Play with an empty player: the phone's
 * own record, unless the server queue was written later (another device played
 * music since). The server queue has no position, so it starts its track at 0. */
export function chooseSession(local: LastSession | null, server: QueueDTO | null | undefined): LastSession | null {
  const items = metasFromServerQueue(server);
  const serverAt = server?.updated_at ? Date.parse(server.updated_at) : NaN;
  const serverIndex = server?.current_index ?? 0;
  const fromServer: MusicSession | null =
    items.length > 0
      ? {
          kind: "music",
          items,
          index: Math.min(Math.max(0, serverIndex), items.length - 1),
          positionSec: 0,
          recordedAtMs: Number.isFinite(serverAt) ? serverAt : 0,
        }
      : null;
  if (!local) return fromServer;
  if (!fromServer) return local;
  // The phone writes the server queue too, a moment after its own record; a
  // server queue that is only that echo of the same queue is not newer.
  if (local.kind === "music" && sameQueue(local.items, fromServer.items)) return local;
  return fromServer.recordedAtMs > local.recordedAtMs + 60_000 ? fromServer : local;
}

function sameQueue(a: QueueMeta[], b: QueueMeta[]): boolean {
  return a.length === b.length && a.every((m, i) => m.mediaFileId === b[i].mediaFileId);
}

/** A queue meta as the SongRow playSongs-style loading signs and queues. */
export function songFromMeta(m: QueueMeta): SongRow {
  return {
    id: m.trackId ?? m.mediaFileId,
    title: m.title,
    duration_sec: m.durationSec ?? null,
    album_id: m.albumId ?? "",
    album_title: m.album ?? "",
    cover_path: m.artPath ?? null,
    artist_id: m.artistId ?? "",
    artist_name: m.artist ?? "",
    media_files: [{ id: m.mediaFileId, duration_sec: m.durationSec ?? null }],
  };
}

/** A saved position worth seeking to: a few seconds in, and not at (or past)
 * the end of a track whose length is known. */
export function resumePositionFor(positionSec: number, durationSec?: number | null): number {
  if (!isNum(positionSec) || positionSec < 3) return 0;
  if (isNum(durationSec) && durationSec > 0 && positionSec >= durationSec - 2) return 0;
  return Math.floor(positionSec);
}
