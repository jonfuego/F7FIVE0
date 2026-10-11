/** Download state for an album screen: one status per track, a summary for the
 * whole album, and the message shown after Download is tapped. Pure (reads the
 * download store's state, never writes it), so it unit tests in Node. */
import type { DownloadState } from "./queue";

export type TrackDownloadStatus = "none" | "queued" | "downloading" | "done" | "failed";

/** A track's download status by media file id. A canceled entry counts as none. */
export function trackDownloadStatus(state: DownloadState, mediaFileId: string | undefined): TrackDownloadStatus {
  if (!mediaFileId) return "none";
  const item = state.items.find((i) => i.id === mediaFileId);
  if (!item) return "none";
  switch (item.status) {
    case "queued":
      return "queued";
    case "downloading":
      return "downloading";
    case "done":
      return "done";
    case "error":
      return "failed";
    default:
      return "none";
  }
}

export interface AlbumDownloadSummary {
  total: number;
  done: number;
  queued: number;
  downloading: number;
  failed: number;
  /** "none" = nothing of this album is in the store. "partial" = some tracks are
   * done and nothing is running. "active" = something is queued or downloading. */
  state: "none" | "active" | "partial" | "failed" | "done";
  /** Text for the album header, or null when there is nothing to say. */
  label: string | null;
}

/** Roll the per-track statuses of an album into one state and label.
 * `mediaFileIds` is the first media file of every track (tracks with no file
 * are left out by the caller). */
export function albumDownloadSummary(state: DownloadState, mediaFileIds: string[]): AlbumDownloadSummary {
  const total = mediaFileIds.length;
  let done = 0;
  let queued = 0;
  let downloading = 0;
  let failed = 0;
  for (const id of mediaFileIds) {
    const s = trackDownloadStatus(state, id);
    if (s === "done") done += 1;
    else if (s === "queued") queued += 1;
    else if (s === "downloading") downloading += 1;
    else if (s === "failed") failed += 1;
  }
  const active = queued + downloading;
  const counts = { total, done, queued, downloading, failed };
  if (total === 0 || done + active + failed === 0) return { ...counts, state: "none", label: null };
  if (done === total) return { ...counts, state: "done", label: "Downloaded" };
  const failedText = failed > 0 ? `, ${failed} failed` : "";
  if (active > 0) {
    return { ...counts, state: "active", label: `Downloading, ${done} of ${total} done${failedText}` };
  }
  if (done > 0) {
    return { ...counts, state: failed > 0 ? "failed" : "partial", label: `${done} of ${total} downloaded${failedText}` };
  }
  return { ...counts, state: "failed", label: `${failed} of ${total} failed` };
}

/** Short word for a track row's accessibility label, or null for "none". */
export function trackStatusText(status: TrackDownloadStatus): string | null {
  switch (status) {
    case "queued":
      return "queued for download";
    case "downloading":
      return "downloading";
    case "done":
      return "downloaded";
    case "failed":
      return "download failed";
    default:
      return null;
  }
}

function tracksText(n: number): string {
  return `${n} ${n === 1 ? "track" : "tracks"}`;
}

/** The confirmation shown right after Download is tapped on an album. Call it
 * with the store state from BEFORE the tracks are queued, and the number the
 * store actually accepted (`enqueueMany`'s return value). A track is "new" when
 * it is not already queued, downloading or done; a failed or canceled track
 * counts as new because queueing it again retries it. */
export function downloadConfirmation(
  before: DownloadState,
  mediaFileIds: string[],
  accepted: number,
): string {
  if (mediaFileIds.length === 0) return "Nothing to download";
  let done = 0;
  let inFlight = 0;
  for (const id of mediaFileIds) {
    const s = trackDownloadStatus(before, id);
    if (s === "done") done += 1;
    else if (s === "queued" || s === "downloading") inFlight += 1;
  }
  const fresh = mediaFileIds.length - done - inFlight;
  if (fresh === 0) return done === mediaFileIds.length ? "Already downloaded" : "Already downloading";
  // The store refuses new work once the storage limit is reached.
  if (accepted <= 0) return "Storage limit reached";
  const extra = done > 0 ? ` (${done} already downloaded)` : "";
  return `Downloading ${tracksText(fresh)}${extra}`;
}
