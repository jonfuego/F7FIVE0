// Admin > Scans: the rows of the one progress list, built from the statuses the
// page polls. Pure, so node:test covers it (scans-rows.test.ts); it imports
// nothing at run time, like admin-sections.ts.
//
// Rows, always in this order: Movies, TV, Music, Music videos, *arr sync.
//
// - A library whose *arr app is set (Radarr for Movies, Sonarr for TV, Lidarr
//   for Music) is driven by that app's sync. The folder scan must never touch
//   it, so the row does not offer the folder scan then.
// - A library with no *arr app is driven by the folder scan.
// - Music videos are always a folder walk of their own.
// - The *arr sync row (every app that is set, in one go) appears only when at
//   least one app is set.
//
// Music is always startable from the card: through the folder scan when there
// is no Lidarr, through the Lidarr sync when there is. Without a Music folder
// the button stays off and says to add one, because there is nothing to scan.

export type ScanRowId = "movies" | "tv" | "music" | "music_videos" | "arr";
export type ScanRowState = "idle" | "running" | "error" | "never";
export type ArrApp = "radarr" | "sonarr" | "lidarr";
export type ArrApps = Record<ArrApp, boolean>;
export type FolderLibraryId = "movies" | "tv" | "music";

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

/** GET /api/admin/library/arr-sync. */
export type ArrSyncLike = {
  state: string;
  finished_at: string | null;
  current_app?: string | null;
  apps: Record<string, { state: string; synced?: number; errors?: number }>;
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
  now?: number;
};

export type ScanAction =
  | { kind: "folder"; library: FolderLibraryId }
  | { kind: "arr"; apps: ArrApp[] }
  | { kind: "music_videos" };

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

  let result: string;
  if (running) result = entry?.state === "queued" ? "Waiting its turn" : "Syncing";
  else if (entry && failedState(entry.state)) result = entry.state === "interrupted" ? "Interrupted" : "Sync failed";
  else if (entry) {
    result = `${entry.synced ?? 0} ${APP_NOUN[app]} synced`;
    if (entry.errors) result += `, ${plural(entry.errors, "error", "errors")}`;
  } else result = "Not synced yet";

  let disabledReason: string | null = null;
  if (!arr) disabledReason = CHECKING;
  else if (running) disabledReason = "Syncing now.";
  else if (arrRunning) disabledReason = "An *arr sync is already running.";

  return {
    id, label, source: `${APP_LABEL[app]} sync`, state, progress: null, result,
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
// The *arr sync (every app that is set)
// ---------------------------------------------------------------------------
function arrSyncRow(set: ArrApp[], inputs: ScanInputs): ScanRow {
  const { arr } = inputs;
  const now = inputs.now ?? Date.now();
  const running = arr?.state === "running";
  const entries = set.map((app) => [app, arr?.apps[app]] as const);

  let state: ScanRowState;
  if (running) state = "running";
  else if (entries.some(([, e]) => e && (failedState(e.state) || (e.errors ?? 0) > 0))) state = "error";
  else if (arr?.finished_at) state = "idle";
  else state = "never";

  let result: string;
  if (running) {
    const current = arr?.current_app as ArrApp | null | undefined;
    result = current && APP_LABEL[current] ? `Syncing ${APP_LABEL[current]}` : "Syncing";
  } else {
    const parts = entries
      .filter(([, e]) => !!e)
      .map(([app, e]) => {
        if (e && failedState(e.state)) return `${APP_LABEL[app]} failed`;
        const errors = e?.errors ? `, ${plural(e.errors, "error", "errors")}` : "";
        return `${APP_LABEL[app]} ${e?.synced ?? 0} ${APP_NOUN[app]}${errors}`;
      });
    result = parts.length ? parts.join(", ") : "Not synced yet";
  }

  let disabledReason: string | null = null;
  if (!arr) disabledReason = CHECKING;
  else if (running) disabledReason = "Syncing now.";

  return {
    id: "arr", label: "*arr sync", source: "*arr sync", state, progress: null, result,
    when: !running && arr ? whenText(arr.finished_at, now) : "",
    canStart: disabledReason === null, disabledReason,
    action: { kind: "arr", apps: set },
  };
}

/** The ordered rows of the Scans list. */
export function buildScanRows(inputs: ScanInputs): ScanRow[] {
  const set = APP_ORDER.filter((app) => inputs.apps?.[app]);
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
  if (set.length > 0) rows.push(arrSyncRow(set, inputs));
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
  const startable = rows.filter((r) => r.canStart && r.state !== "running");
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
  const texts = [inputs.folder?.last_error, inputs.musicVideos?.last_error, inputs.arr?.last_error];
  const out: string[] = [];
  for (const t of texts) {
    const text = (t ?? "").trim();
    if (text && !out.includes(text)) out.push(text);
  }
  return out;
}
