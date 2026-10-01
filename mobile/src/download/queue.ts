/** Download queue state machine (crit 42). Pure (no native/expo imports) so it
 * unit tests in Node. The manager (queueManager.ts) owns the actual expo-file-
 * system downloads and applies transitions from this reducer; the reducer decides
 * *what* should happen next given the current state and an action, so the policy
 * (one active download at a time, storage limits, cancel/delete) is testable in
 * isolation.
 *
 * A download entry moves: queued -> downloading -> done, or -> error, or
 * -> canceled. Only one entry is `downloading` at a time. */

export type DownloadStatus = "queued" | "downloading" | "done" | "error" | "canceled";

/** What a download is, so the Downloads screen and offline mode can play it
 * without the network (no catalogue lookups offline). */
export type DownloadKind = "track" | "movie" | "episode" | "music_video";

export interface DownloadMeta {
  trackId?: string | null;
  artist?: string | null;
  album?: string | null;
  albumId?: string | null;
  coverPath?: string | null;
  durationSec?: number | null;
  /** Container hint ("flac", "mp4") used for the local file extension. */
  container?: string | null;
  /** Grouping label for bulk downloads (album title, mix name, show). */
  group?: string | null;
}

export interface DownloadItem {
  /** media_file_id — the stable key. Files are stored under this id, never a URL. */
  id: string;
  title: string;
  status: DownloadStatus;
  /** 0..1 progress while downloading. */
  progress: number;
  /** Bytes written (known once downloading/done). */
  bytes: number;
  /** Total bytes if the server sent a content-length. */
  totalBytes?: number;
  /** Local file path once done (set by the manager, echoed here for the UI). */
  localPath?: string;
  error?: string;
  kind?: DownloadKind;
  meta?: DownloadMeta;
}

export interface DownloadState {
  items: DownloadItem[];
  /** Soft cap; enqueue is rejected past it. 0 = unlimited. */
  storageLimitBytes: number;
}

export type DownloadAction =
  | { type: "enqueue"; id: string; title: string; kind?: DownloadKind; meta?: DownloadMeta }
  | { type: "start"; id: string }
  | { type: "progress"; id: string; bytes: number; totalBytes?: number }
  | { type: "complete"; id: string; localPath: string; bytes: number }
  | { type: "fail"; id: string; error: string }
  | { type: "cancel"; id: string }
  | { type: "remove"; id: string }
  | { type: "setLimit"; bytes: number }
  | { type: "hydrate"; state: DownloadState };

export function initialState(storageLimitBytes = 0): DownloadState {
  return { items: [], storageLimitBytes };
}

/** Total bytes of finished downloads (what's actually on disk). */
export function usedBytes(state: DownloadState): number {
  return state.items.filter((i) => i.status === "done").reduce((sum, i) => sum + i.bytes, 0);
}

/** The next item the manager should start: the first queued entry, but only when
 * nothing is currently downloading (one at a time). Null otherwise. */
export function nextToStart(state: DownloadState): DownloadItem | null {
  if (state.items.some((i) => i.status === "downloading")) return null;
  return state.items.find((i) => i.status === "queued") ?? null;
}

/** Whether a new enqueue is allowed under the storage limit. Unlimited when the
 * limit is 0. Uses used (done) bytes only, since queued sizes are unknown. */
export function canEnqueue(state: DownloadState): boolean {
  if (state.storageLimitBytes <= 0) return true;
  return usedBytes(state) < state.storageLimitBytes;
}

function upsert(items: DownloadItem[], id: string, patch: Partial<DownloadItem>): DownloadItem[] {
  return items.map((i) => (i.id === id ? { ...i, ...patch } : i));
}

export function reduce(state: DownloadState, action: DownloadAction): DownloadState {
  switch (action.type) {
    case "enqueue": {
      // Idempotent: an existing entry that isn't in a terminal-failure state is
      // kept; a canceled/errored one is re-queued.
      const existing = state.items.find((i) => i.id === action.id);
      if (existing) {
        if (existing.status === "canceled" || existing.status === "error") {
          return { ...state, items: upsert(state.items, action.id, { status: "queued", progress: 0, error: undefined }) };
        }
        return state; // queued/downloading/done — no-op
      }
      const item: DownloadItem = {
        id: action.id,
        title: action.title,
        status: "queued",
        progress: 0,
        bytes: 0,
        ...(action.kind ? { kind: action.kind } : {}),
        ...(action.meta ? { meta: action.meta } : {}),
      };
      return { ...state, items: [...state.items, item] };
    }
    case "start":
      return { ...state, items: upsert(state.items, action.id, { status: "downloading", progress: 0 }) };
    case "progress": {
      const total = action.totalBytes;
      const progress = total && total > 0 ? Math.min(1, action.bytes / total) : 0;
      return { ...state, items: upsert(state.items, action.id, { bytes: action.bytes, totalBytes: total, progress }) };
    }
    case "complete":
      return {
        ...state,
        items: upsert(state.items, action.id, {
          status: "done",
          progress: 1,
          localPath: action.localPath,
          bytes: action.bytes,
        }),
      };
    case "fail":
      return { ...state, items: upsert(state.items, action.id, { status: "error", error: action.error }) };
    case "cancel":
      return { ...state, items: upsert(state.items, action.id, { status: "canceled", progress: 0 }) };
    case "remove":
      return { ...state, items: state.items.filter((i) => i.id !== action.id) };
    case "setLimit":
      return { ...state, storageLimitBytes: Math.max(0, action.bytes) };
    case "hydrate": {
      // Merge: anything enqueued before hydration finished is kept after the
      // restored items (no duplicates).
      const restoredIds = new Set(action.state.items.map((i) => i.id));
      return {
        items: [...action.state.items, ...state.items.filter((i) => !restoredIds.has(i.id))],
        storageLimitBytes: action.state.storageLimitBytes,
      };
    }
    default:
      return state;
  }
}

/** Downloaded (done) items of one kind, in the order they were queued. */
export function doneItems(state: DownloadState, kind?: DownloadKind): DownloadItem[] {
  return state.items.filter((i) => i.status === "done" && (!kind || (i.kind ?? "track") === kind));
}

/** Rebuild state from persisted items on launch: finished downloads whose file
 * still exists are kept as done; anything that was mid-flight is re-queued;
 * failed/canceled entries and done entries whose file vanished are dropped.
 * Pure: the caller supplies `fileExists`. */
export function restoreItems(
  saved: DownloadItem[],
  fileExists: (item: DownloadItem) => boolean,
  storageLimitBytes = 0,
): DownloadState {
  const items: DownloadItem[] = [];
  for (const it of saved) {
    if (it.status === "done") {
      if (it.localPath && fileExists(it)) items.push({ ...it, progress: 1 });
    } else if (it.status === "queued" || it.status === "downloading") {
      items.push({ ...it, status: "queued", progress: 0, bytes: 0 });
    }
  }
  return { items, storageLimitBytes };
}

/** Local file name for a media file: `<id>.<ext>` with a sanitized container
 * extension when known (helps ExoPlayer/MediaPlayer pick an extractor). */
export function localFileName(mediaFileId: string, container?: string | null): string {
  const ext = (container ?? "").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 5);
  return ext ? `${mediaFileId}.${ext}` : mediaFileId;
}
