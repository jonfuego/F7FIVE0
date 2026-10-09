// Library folder scan: wording and small pure helpers for Admin > Library
// folders and the empty library pages (kept apart from the React components so
// node:test can cover them; see library-scan.test.ts).

export const SCAN_POLL_MS = 3000;

export const SCANNING_TEXT = "Your library is being scanned. Items show up here as they are found.";

export type LibraryKind = "movies" | "tv" | "artists" | "albums";

const EMPTY_TEXT: Record<LibraryKind, string> = {
  movies: "No movies in the library yet.",
  tv: "No TV shows in the library yet.",
  artists: "No artists in the library yet.",
  albums: "No albums in the library yet.",
};

/** What an empty library page says: that a scan is running, or today's text. */
export function emptyLibraryText(kind: LibraryKind, scanning: boolean): string {
  return scanning ? SCANNING_TEXT : EMPTY_TEXT[kind];
}

/** GET /api/library/scan-state: what every signed-in user may know. */
export type ScanState = { running: boolean; finished_at: string | null };

export type ArrFeatures = { radarr: boolean; sonarr: boolean; lidarr: boolean };

/** "Run *arr sync now" only makes sense when an *arr app is set up. */
export function showArrSync(arr: ArrFeatures | null | undefined): boolean {
  return !!arr && (arr.radarr || arr.sonarr || arr.lidarr);
}

export type LibraryScanCounts = {
  state: string;
  seen?: number;
  added?: number;
  probed?: number;
  missing?: number;
  errors?: number;
};

/** GET /api/admin/library/scan */
export type FolderScanStatus = {
  state: "idle" | "running" | string;
  started_at: string | null;
  finished_at: string | null;
  current_library: string | null;
  libraries: Record<string, LibraryScanCounts>;
  last_error: string | null;
};

export const LIBRARY_LABEL: Record<string, string> = { movies: "Movies", tv: "TV", music: "Music" };

/** The status block polls while a scan runs and stops when it is idle. */
export function shouldPollScan(status: { state: string } | null | undefined): boolean {
  return !!status && status.state === "running";
}

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

/** "Scanning Movies", or when the last scan finished. */
export function scanHeadline(status: FolderScanStatus, now: number = Date.now()): string {
  if (status.state === "running") {
    const label = status.current_library ? LIBRARY_LABEL[status.current_library] ?? status.current_library : "";
    return label ? `Scanning ${label}` : "Scanning";
  }
  if (status.finished_at) return `Last scan finished ${ago(status.finished_at, now)}`;
  return "No scan has run yet";
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** One library's counts as a short sentence. */
export function countsText(c: LibraryScanCounts): string {
  if (c.seen === undefined) return "Waiting";
  const parts = [`${plural(c.seen, "file", "files")} seen`, `${c.added ?? 0} added`];
  if (c.missing) parts.push(`${c.missing} missing`);
  if (c.errors) parts.push(plural(c.errors, "error", "errors"));
  return parts.join(", ");
}
