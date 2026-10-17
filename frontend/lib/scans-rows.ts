// Admin > Scans: the rows of the one progress list, built from the statuses the
// page polls. Pure, so node:test covers it (scans-rows.test.ts); it imports
// nothing at run time, like admin-sections.ts.
//
// Rows, always in this order: Movies, TV, Music, Music videos, Podcasts, Podcast
// feeds.
//
// - A library whose *arr app is set (Radarr for Movies, Sonarr for TV, Lidarr
//   for Music) is driven by that app's sync. The folder scan must never touch
//   it, so the row does not offer the folder scan then. That row carries the
//   sync's own progress (done of total, and the missing / error / refused
//   counts), so there is no separate "*arr sync" row repeating it.
// - A library with no *arr app is driven by the folder scan.
// - Music videos are always a folder walk of their own.
//
// - Podcasts are a folder scan of the podcasts library (no *arr app owns them).
//   "Podcast feeds" is a different job: it refreshes the feeds of the shows people
//   follow. It has its own button (Refresh feeds) and is not part of Scan all,
//   because it is not a scan of anything on disk.
//
// Music is always startable from the card: through the folder scan when there
// is no Lidarr, through the Lidarr sync when there is. Without a Music folder
// the button stays off and says to add one, because there is nothing to scan.

export type ScanRowId =
  | "movies" | "tv" | "music" | "music_videos" | "podcasts" | "podcast_feeds";
export type ScanRowState = "idle" | "running" | "error" | "never";
export type ArrApp = "radarr" | "sonarr" | "lidarr";
export type ArrApps = Record<ArrApp, boolean>;
export type FolderLibraryId = "movies" | "tv" | "music" | "podcasts";

export type FolderLibraryLike = {
  state: string;
  total?: number;
  seen?: number;
  added?: number;
  missing?: number;
  errors?: number;
};

/** GET /api/admin/library/scan (the folder scan). */
export type FolderScanLike = {
  state: string;
  finished_at: string | null;
  scope?: string[] | null;
  libraries: Record<string, FolderLibraryLike>;
  last_error: string | null;
};

/** GET /api/library/music-videos/scan. */
export type MusicVideosLike = {
  state: string;
  finished_at: string | null;
  total: number;
  count: number;
  added: number;
  missing: number;
  errors: number;
  last_error: string | null;
};

/** One app's entry in GET /api/admin/library/arr-sync. `done` is the items saved
 *  so far out of `total` (known up front); `updated_at` is when the backend last
 *  wrote the entry. The progress fields are missing from an older backend. */
export type ArrAppStatusLike = {
  state: string;
  synced?: number;
  errors?: number;
  done?: number;
  total?: number;
  ready?: number;
  missing?: number;
  refused?: number;
  updated_at?: string;
};

/** GET /api/admin/library/arr-sync. */
export type ArrSyncLike = {
  state: string;
  finished_at: string | null;
  current_app?: string | null;
  apps: Record<string, ArrAppStatusLike>;
  last_error: string | null;
};

/** GET /api/admin/podcasts/refresh. */
export type PodcastRefreshLike = {
  state: string;
  finished_at: string | null;
  total: number;
  count: number;
  added: number;
  errors: number;
  last_error: string | null;
};

export type ScanInputs = {
  /** Which *arr apps have a key. null until known. */
  apps: ArrApps | null;
  /** Folders saved per library (movies, tv, music, music_videos). null until known. */
  folders: Record<string, number> | null;
  folder: FolderScanLike | null;
  musicVideos: MusicVideosLike | null;
  arr: ArrSyncLike | null;
  /** The podcast feed refresh. null / missing until known. */
  podcastRefresh?: PodcastRefreshLike | null;
  now?: number;
};

export type ScanAction =
  | { kind: "folder"; library: FolderLibraryId }
  | { kind: "arr"; apps: ArrApp[] }
  | { kind: "music_videos" }
  | { kind: "podcast_refresh" };

export type ScanRow = {
  id: ScanRowId;
  label: string;
  /** What runs when the button is pressed. */
  source: string;
  state: ScanRowState;
  /** Only while running with a known total. */
  progress: { done: number; total: number; percent: number } | null;
  /** The counts, or what is happening now. */
  result: string;
  /** "Finished 5 minutes ago", or "". */
  when: string;
  canStart: boolean;
  /** Why the button is off; null when it is on. */
  disabledReason: string | null;
  action: ScanAction;
};

const APP_ORDER: ArrApp[] = ["radarr", "sonarr", "lidarr"];
const APP_LABEL: Record<ArrApp, string> = { radarr: "Radarr", sonarr: "Sonarr", lidarr: "Lidarr" };
const APP_NOUN: Record<ArrApp, string> = { radarr: "movies", sonarr: "shows", lidarr: "artists" };

const CHECKING = "Still checking.";

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function percentOf(done: number, total: number): number {
  if (!total || total <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((done / total) * 100)));
}

// Same wording as library-scan.ts; kept here so this file stays a leaf.
function ago(iso: string, now: number): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "a while ago";
  const minutes = Math.floor(Math.max(0, now - t) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return minutes === 1 ? "1 minute ago" : `${minutes} minutes ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

function whenText(finishedAt: string | null, now: number): string {
  return finishedAt ? `Finished ${ago(finishedAt, now)}` : "";
}

function failedState(state: string | undefined): boolean {
  return state === "failed" || state === "interrupted";
}

function countsLine(seen: number, added: number, missing: number, errors: number): string {
  const parts = [`${plural(seen, "file", "files")} seen`, `${added} added`];
  if (missing) parts.push(`${missing} missing`);
  if (errors) parts.push(plural(errors, "error", "errors"));
  return parts.join(", ");
}

// ---------------------------------------------------------------------------
// One folder library (Movies, TV, Music without its *arr app)
// ---------------------------------------------------------------------------
function folderRow(id: FolderLibraryId, label: string, inputs: ScanInputs): ScanRow {
  const { folder, folders, apps } = inputs;
  const now = inputs.now ?? Date.now();
  const lib = folder?.libraries[id];
  const folderRunning = folder?.state === "running";
  const count = folders?.[id] ?? 0;
  const inScope =
    folderRunning && count > 0 && (!folder?.scope || folder.scope.includes(id));

  let state: ScanRowState;
  if (inScope && (!lib || lib.state === "running" || lib.state === "queued")) state = "running";
  else if (lib && (failedState(lib.state) || (lib.errors ?? 0) > 0)) state = "error";
  else if (lib && lib.state === "done") state = "idle";
  else state = "never";

  const total = lib?.total ?? 0;
  const seen = lib?.seen ?? 0;
  const progress =
    state === "running" && total > 0 ? { done: seen, total, percent: percentOf(seen, total) } : null;

  let result: string;
  if (state === "running") {
    if (!lib || lib.state === "queued") result = "Waiting its turn";
    else result = total > 0 ? `${seen} of ${total} files` : `${plural(seen, "file", "files")} seen`;
  } else if (lib) {
    result = failedState(lib.state)
      ? lib.state === "interrupted" ? "Interrupted" : "Failed"
      : countsLine(seen, lib.added ?? 0, lib.missing ?? 0, lib.errors ?? 0);
  } else {
    result = "Not scanned yet";
  }

  let disabledReason: string | null = null;
  if (!apps || !folders || !folder) disabledReason = CHECKING;
  else if (state === "running") disabledReason = "Scanning now.";
  else if (folderRunning) disabledReason = "A folder scan is already running.";
  else if (count === 0) disabledReason = `Add a ${label} folder under Library folders first.`;

  return {
    id, label, source: "folder scan", state, progress, result,
    when: state === "running" || !lib ? "" : whenText(folder?.finished_at ?? null, now),
    canStart: disabledReason === null, disabledReason,
    action: { kind: "folder", library: id },
  };
}

// ---------------------------------------------------------------------------
// One library driven by its *arr app (Movies, TV, Music with a key set)
// ---------------------------------------------------------------------------
/** A running app that has not written its progress for this long is shown as
 *  stuck ("No progress since 10:42") instead of "Syncing". The backend writes at
 *  least every 5 seconds while an app runs. */
export const ARR_STALE_MS = 5 * 60 * 1000;

function isStale(updatedAt: string | undefined, now: number): boolean {
  if (!updatedAt) return false;
  const t = Date.parse(updatedAt);
  return !Number.isNaN(t) && now - t >= ARR_STALE_MS;
}

/** The clock time of an ISO stamp, "10:42 AM". */
export function clockTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "a while ago";
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function count(n: number): string {
  return n.toLocaleString("en-US");
}

/** ", 2,662 missing, 3 errors, 1 refused": only the counts that are not zero. */
function arrCountsTail(entry: ArrAppStatusLike | undefined): string {
  if (!entry) return "";
  const parts: string[] = [];
  if (entry.missing) parts.push(`${count(entry.missing)} missing`);
  if (entry.errors) parts.push(plural(entry.errors, "error", "errors"));
  if (entry.refused) parts.push(`${count(entry.refused)} refused`);
  return parts.length ? `, ${parts.join(", ")}` : "";
}

function arrAppRow(id: FolderLibraryId, label: string, app: ArrApp, inputs: ScanInputs): ScanRow {
  const { arr } = inputs;
  const now = inputs.now ?? Date.now();
  const entry = arr?.apps[app];
  const arrRunning = arr?.state === "running";
  const running = arrRunning && !!entry && (entry.state === "running" || entry.state === "queued");

  let state: ScanRowState;
  if (running) state = "running";
  else if (entry && (failedState(entry.state) || (entry.errors ?? 0) > 0)) state = "error";
  else if (entry && entry.state === "done") state = "idle";
  else state = "never";

  // A run that is moving: items saved so far out of the total the app listed.
  const total = entry?.total ?? 0;
  const done = entry?.done ?? 0;
  const progress =
    running && entry?.state === "running" && total > 0
      ? { done, total, percent: percentOf(done, total) }
      : null;
  const stale = running && entry?.state === "running" && isStale(entry?.updated_at, now);

  let result: string;
  if (running && entry?.state === "queued") result = "Waiting its turn";
  else if (stale && entry?.updated_at) result = `No progress since ${clockTime(entry.updated_at)}`;
  else if (running) {
    result = progress ? `${count(done)} of ${count(total)} ${APP_NOUN[app]}` : "Syncing";
    result += arrCountsTail(entry);
  } else if (entry && failedState(entry.state)) {
    result = entry.state === "interrupted" ? "Interrupted" : "Sync failed";
    if (total > 0) result += ` after ${count(done)} of ${count(total)} ${APP_NOUN[app]}`;
    result += arrCountsTail(entry);
  } else if (entry) {
    result = `${count(entry.synced ?? 0)} ${APP_NOUN[app]} synced${arrCountsTail(entry)}`;
  } else result = "Not synced yet";

  let disabledReason: string | null = null;
  if (!arr) disabledReason = CHECKING;
  else if (running) disabledReason = "Syncing now.";
  else if (arrRunning) disabledReason = "An *arr sync is already running.";

  return {
    id, label, source: `${APP_LABEL[app]} sync`, state, progress, result,
    when: !running && entry ? whenText(arr?.finished_at ?? null, now) : "",
    canStart: disabledReason === null, disabledReason,
    action: { kind: "arr", apps: [app] },
  };
}

// ---------------------------------------------------------------------------
// Music videos
// ---------------------------------------------------------------------------
function musicVideosRow(inputs: ScanInputs): ScanRow {
  const { musicVideos: mv, folders } = inputs;
  const now = inputs.now ?? Date.now();
  const running = mv?.state === "running";

  let state: ScanRowState;
  if (running) state = "running";
  else if (mv && (mv.errors > 0 || !!mv.last_error)) state = "error";
  else if (mv && mv.finished_at) state = "idle";
  else state = "never";

  const progress =
    mv && running && mv.total > 0
      ? { done: mv.count, total: mv.total, percent: percentOf(mv.count, mv.total) }
      : null;

  let result: string;
  if (!mv) result = "";
  else if (running) result = mv.total > 0 ? `${mv.count} of ${mv.total} files` : `${plural(mv.count, "file", "files")} seen`;
  else if (state === "never") result = "Not scanned yet";
  else {
    const parts = [`${mv.added} added`];
    if (mv.missing) parts.push(`${mv.missing} missing`);
    if (mv.errors) parts.push(plural(mv.errors, "error", "errors"));
    result = parts.join(", ");
  }

  let disabledReason: string | null = null;
  if (!mv || !folders) disabledReason = CHECKING;
  else if (running) disabledReason = "Scanning now.";
  else if ((folders.music_videos ?? 0) === 0) disabledReason = "Add a Music videos folder under Library folders first.";

  return {
    id: "music_videos", label: "Music videos", source: "music videos scan", state, progress, result,
    when: !running && mv ? whenText(mv.finished_at, now) : "",
    canStart: disabledReason === null, disabledReason,
    action: { kind: "music_videos" },
  };
}

// ---------------------------------------------------------------------------
// Podcast feeds (refresh the feeds of the shows people follow)
// ---------------------------------------------------------------------------
function podcastFeedsRow(inputs: ScanInputs): ScanRow {
  const pr = inputs.podcastRefresh ?? null;
  const now = inputs.now ?? Date.now();
  const running = pr?.state === "running";

  let state: ScanRowState;
  if (running) state = "running";
  else if (pr && (pr.errors > 0 || !!pr.last_error)) state = "error";
  else if (pr && pr.finished_at) state = "idle";
  else state = "never";

  const progress =
    pr && running && pr.total > 0
      ? { done: pr.count, total: pr.total, percent: percentOf(pr.count, pr.total) }
      : null;

  let result: string;
  if (!pr) result = "";
  else if (running) result = pr.total > 0 ? `${pr.count} of ${pr.total} shows` : "Starting";
  else if (state === "never") result = "Not refreshed yet";
  else {
    const parts = [`${pr.added} new ${pr.added === 1 ? "episode" : "episodes"}`];
    if (pr.errors) parts.push(plural(pr.errors, "error", "errors"));
    result = parts.join(", ");
  }

  let disabledReason: string | null = null;
  if (!pr) disabledReason = CHECKING;
  else if (running) disabledReason = "Refreshing now.";

  return {
    id: "podcast_feeds", label: "Podcast feeds", source: "feed refresh", state, progress, result,
    when: !running && pr ? whenText(pr.finished_at, now) : "",
    canStart: disabledReason === null, disabledReason,
    action: { kind: "podcast_refresh" },
  };
}

/** The ordered rows of the Scans list. */
export function buildScanRows(inputs: ScanInputs): ScanRow[] {
  const rows: ScanRow[] = [];
  const libs: [FolderLibraryId, string, ArrApp][] = [
    ["movies", "Movies", "radarr"],
    ["tv", "TV", "sonarr"],
    ["music", "Music", "lidarr"],
  ];
  for (const [id, label, app] of libs) {
    rows.push(inputs.apps?.[app] ? arrAppRow(id, label, app, inputs) : folderRow(id, label, inputs));
  }
  rows.push(musicVideosRow(inputs));
  rows.push(folderRow("podcasts", "Podcasts", inputs));
  rows.push(podcastFeedsRow(inputs));
  return rows;
}

// ---------------------------------------------------------------------------
// Scan all
// ---------------------------------------------------------------------------
export type ScanAllPlan = {
  /** Every row the button will start. */
  rowIds: ScanRowId[];
  /** One folder-scan request for these libraries (empty: none). */
  libraries: FolderLibraryId[];
  /** One *arr sync request for these apps (empty: none). */
  arrApps: ArrApp[];
  musicVideos: boolean;
};

/** What Scan all starts: exactly the rows whose own button is on, so a row that
 *  is running (or has nothing to scan) is skipped. The folder libraries go in
 *  one request and the apps in one request, because each of those runs one
 *  at a time. */
export function scanAllPlan(rows: ScanRow[]): ScanAllPlan {
  // Refreshing podcast feeds is not a scan of anything on disk: it keeps its own button.
  const startable = rows.filter(
    (r) => r.canStart && r.state !== "running" && r.action.kind !== "podcast_refresh",
  );
  const libraries: FolderLibraryId[] = [];
  const apps = new Set<ArrApp>();
  let musicVideos = false;
  for (const row of startable) {
    if (row.action.kind === "folder") libraries.push(row.action.library);
    else if (row.action.kind === "arr") row.action.apps.forEach((a) => apps.add(a));
    else musicVideos = true;
  }
  return {
    rowIds: startable.map((r) => r.id),
    libraries,
    arrApps: APP_ORDER.filter((a) => apps.has(a)),
    musicVideos,
  };
}

// ---------------------------------------------------------------------------
// Folded summary and errors
// ---------------------------------------------------------------------------
/** The card's folded line: what runs now, what failed, or that it is idle.
 *  A running or failed scan needs attention (the card opens itself). */
export function scansSummary(rows: ScanRow[]): { text: string; attention: boolean } {
  if (rows.length === 0) return { text: "", attention: false };
  const running = rows.filter((r) => r.state === "running");
  if (running.length > 0) {
    const names = running.map((r) => r.label).join(", ");
    const only = running.length === 1 ? running[0] : null;
    const pct = only?.progress ? ` ${only.progress.percent}%` : "";
    return { text: `Running: ${names}${pct}`, attention: true };
  }
  const failed = rows.filter((r) => r.state === "error");
  if (failed.length > 0) {
    return { text: `Needs attention: ${failed.map((r) => r.label).join(", ")}`, attention: true };
  }
  if (rows.every((r) => r.state === "never")) return { text: "Not scanned yet", attention: false };
  return { text: "Up to date", attention: false };
}

/** The last error text of each status, once each, for the red lines under the list. */
export function scanErrors(inputs: ScanInputs): string[] {
  const texts = [
    inputs.folder?.last_error, inputs.musicVideos?.last_error, inputs.podcastRefresh?.last_error,
    inputs.arr?.last_error,
  ];
  const out: string[] = [];
  for (const t of texts) {
    const text = (t ?? "").trim();
    if (text && !out.includes(text)) out.push(text);
  }
  return out;
}
