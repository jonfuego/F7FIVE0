/** Audio saved while it plays (podcast episodes and music tracks). Pure (no
 * native imports), so it unit tests in Node; DownloadProvider owns the files.
 *
 * Anything played from the server is also saved to the phone, so playback keeps
 * going when the phone loses service. This is separate from Downloads: the
 * Download button is what keeps a file. An entry saved here is removed by
 * itself: a podcast episode once it counts as played, and anything 7 days
 * after it was last played. Tapping Download on something saved here moves
 * the file to Downloads instead of fetching it again.
 *
 * A music queue saves the playing track and the next two. A podcast episode is
 * saved when it starts; once the file is on the phone, the player switches to
 * it at the current place.
 */
import type { DownloadMeta } from "./queue";

export type CacheKind = "track" | "podcast";
export type CacheStatus = "queued" | "downloading" | "done" | "error";

export interface CacheEntry {
  /** media file id for a track, episode id for a podcast episode. */
  id: string;
  kind: CacheKind;
  title: string;
  status: CacheStatus;
  bytes: number;
  localPath?: string;
  /** When it was last asked for (played or about to play), ms. */
  lastPlayedAt: number;
  /** A podcast episode that counts as played (ms), so it can go. */
  playedAt?: number;
  attempts: number;
  meta?: DownloadMeta;
}

export interface CacheState {
  entries: CacheEntry[];
}

/** Anything not played for this long is removed. */
export const CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
/** A failed save is tried again on a later play, up to this many times. */
export const CACHE_MAX_ATTEMPTS = 3;
/** How many queue tracks are saved: the playing one and the next two. */
export const MUSIC_LOOKAHEAD = 3;
/** Saving stops while the phone has less free space than this. */
export const CACHE_MIN_FREE_BYTES = 1024 * 1024 * 1024;

export type CacheAction =
  | { type: "request"; id: string; kind: CacheKind; title: string; meta?: DownloadMeta; now: number }
  | { type: "start"; id: string }
  | { type: "complete"; id: string; localPath: string; bytes: number }
  | { type: "fail"; id: string }
  | { type: "played"; id: string; now: number }
  | { type: "remove"; id: string }
  | { type: "hydrate"; state: CacheState };

export function emptyCache(): CacheState {
  return { entries: [] };
}

function patch(entries: CacheEntry[], id: string, p: Partial<CacheEntry>): CacheEntry[] {
  return entries.map((e) => (e.id === id ? { ...e, ...p } : e));
}

export function cacheReduce(state: CacheState, action: CacheAction): CacheState {
  switch (action.type) {
    case "request": {
      const existing = state.entries.find((e) => e.id === action.id);
      if (!existing) {
        const entry: CacheEntry = {
          id: action.id,
          kind: action.kind,
          title: action.title,
          status: "queued",
          bytes: 0,
          lastPlayedAt: action.now,
          attempts: 0,
          ...(action.meta ? { meta: action.meta } : {}),
        };
        return { entries: [...state.entries, entry] };
      }
      // Asked again: it was played again, so it stays another 7 days. A failed
      // save gets another try while it has tries left.
      const retry = existing.status === "error" && existing.attempts < CACHE_MAX_ATTEMPTS;
      return {
        entries: patch(state.entries, action.id, {
          lastPlayedAt: action.now,
          playedAt: undefined,
          ...(retry ? { status: "queued" as const } : {}),
        }),
      };
    }
    case "start":
      return {
        entries: state.entries.map((e) =>
          e.id === action.id ? { ...e, status: "downloading" as const, attempts: e.attempts + 1 } : e,
        ),
      };
    case "complete":
      return { entries: patch(state.entries, action.id, { status: "done", localPath: action.localPath, bytes: action.bytes }) };
    case "fail":
      return { entries: patch(state.entries, action.id, { status: "error", localPath: undefined, bytes: 0 }) };
    case "played":
      return { entries: patch(state.entries, action.id, { playedAt: action.now }) };
    case "remove":
      return { entries: state.entries.filter((e) => e.id !== action.id) };
    case "hydrate": {
      const restored = new Set(action.state.entries.map((e) => e.id));
      return { entries: [...action.state.entries, ...state.entries.filter((e) => !restored.has(e.id))] };
    }
    default:
      return state;
  }
}

/** The next save to start: the first queued one, only when none is running. */
export function nextCacheToStart(state: CacheState): CacheEntry | null {
  if (state.entries.some((e) => e.status === "downloading")) return null;
  return state.entries.find((e) => e.status === "queued") ?? null;
}

/** Entries to remove now: a played podcast episode, anything not played for 7
 * days, and a save that failed for good. Never one in `keep` (what is loaded in
 * the player) or one that is downloading. */
export function evictable(state: CacheState, now: number, keep: ReadonlySet<string> = new Set()): CacheEntry[] {
  return state.entries.filter((e) => {
    if (keep.has(e.id) || e.status === "downloading") return false;
    if (e.kind === "podcast" && e.playedAt !== undefined) return true;
    if (now - e.lastPlayedAt >= CACHE_MAX_AGE_MS) return true;
    return e.status === "error" && e.attempts >= CACHE_MAX_ATTEMPTS;
  });
}

/** The local file of a finished save, or undefined. */
export function cachedPath(state: CacheState, id: string): string | undefined {
  const e = state.entries.find((x) => x.id === id && x.status === "done");
  return e?.localPath;
}

/** Bytes of finished saves. */
export function cacheBytes(state: CacheState): number {
  return state.entries.filter((e) => e.status === "done").reduce((n, e) => n + e.bytes, 0);
}

/** On launch: finished saves whose file is still there stay; one that was
 * running goes back in line; others keep their state. */
export function restoreCache(saved: CacheEntry[], fileExists: (e: CacheEntry) => boolean): CacheState {
  const entries: CacheEntry[] = [];
  for (const e of saved) {
    if (e.status === "done") {
      if (e.localPath && fileExists(e)) entries.push(e);
    } else if (e.status === "downloading") {
      entries.push({ ...e, status: "queued" });
    } else {
      entries.push(e);
    }
  }
  return { entries };
}

/** Which queue entries to save for a music queue: the playing one and the
 * next ones, up to MUSIC_LOOKAHEAD, skipping podcast entries. */
export function musicLookahead<T>(queue: readonly T[], activeIndex: number, n = MUSIC_LOOKAHEAD): T[] {
  if (activeIndex < 0) return [];
  return queue.slice(activeIndex, activeIndex + n);
}
