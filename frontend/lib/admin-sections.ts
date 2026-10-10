// Pure helpers for the collapsible Admin sections (item 5): the one-line
// summary each section shows when folded, and the "needs attention" rule that
// keeps a running scan, a failed scan, an available update or a running update
// visible even while collapsed. Kept apart from the React page so node:test can
// cover it (admin-sections.test.ts).

// A collapsed section's summary: the text shown on the header, and whether it
// needs attention (so the caller can colour it or force the section open).
export type SectionSummary = { text: string; attention: boolean };

// Mirror of the folder-scan status shape this file reads. Kept local (not
// imported from library-scan) so the pure helper stays leaf and node:test can
// load it without the "@/" alias. The admin page passes the real
// FolderScanStatus, which is structurally compatible.
type ScanLibrary = { state: string; seen?: number; probed?: number; errors?: number };
export type ScanStatusLike = {
  state: string;
  current_library: string | null;
  finished_at: string | null;
  libraries: Record<string, ScanLibrary>;
};

const LIBRARY_LABEL: Record<string, string> = { movies: "Movies", tv: "TV", music: "Music" };

const METHOD_LABEL: Record<string, string> = {
  tailscale: "Tailscale",
  cloudflare: "Cloudflare",
  portforward: "Port forwarding",
  token: "Cloudflare tunnel token",
};

/** Remote access, folded: "Cloudflare, Connected", "Off", or a reachability
 * warning. Not reachable needs attention. */
export function remoteAccessSummary(status: {
  public_url: string | null;
  method: string | null;
  reachable: boolean | null;
} | null): SectionSummary {
  if (!status || !status.public_url) return { text: "Off", attention: false };
  const method = status.method ? METHOD_LABEL[status.method] ?? status.method : "On";
  if (status.reachable === false) return { text: `${method}, not reachable`, attention: true };
  const reach = status.reachable === true ? "Connected" : "Set up";
  return { text: `${method}, ${reach}`, attention: false };
}

/** Updates, folded: "1.0.6, up to date", "1.0.7 available", or "Updating" while
 * a run is active. An available or running update needs attention. */
export function updatesSummary(status: {
  installed_version: string;
  latest_version: string | null;
  update_available: boolean;
  run: { active: boolean } | null;
} | null): SectionSummary {
  if (!status) return { text: "", attention: false };
  if (status.run?.active) return { text: "Updating now", attention: true };
  if (status.update_available && status.latest_version) {
    return { text: `${status.latest_version} available`, attention: true };
  }
  return { text: `${status.installed_version}, up to date`, attention: false };
}

/** Library folders, folded: "Scanning Music 40%", "1 error", or "Last scan
 * finished". A running or failed scan needs attention. */
export function scanSummary(status: ScanStatusLike | null): SectionSummary {
  if (!status) return { text: "", attention: false };
  if (status.state === "running") {
    const key = status.current_library;
    const label = key ? LIBRARY_LABEL[key] ?? key : "";
    const lib = key ? status.libraries[key] : undefined;
    const pct =
      lib && lib.seen && lib.seen > 0 && lib.probed !== undefined
        ? Math.min(100, Math.round((lib.probed / lib.seen) * 100))
        : null;
    const base = label ? `Scanning ${label}` : "Scanning";
    return { text: pct !== null ? `${base} ${pct}%` : base, attention: true };
  }
  const errors = Object.values(status.libraries).reduce((n, l) => n + (l.errors ?? 0), 0);
  if (status.state === "failed" || errors > 0) {
    return { text: errors > 0 ? `${errors} error${errors === 1 ? "" : "s"}` : "Scan failed", attention: true };
  }
  if (status.finished_at) return { text: "Up to date", attention: false };
  return { text: "No scan yet", attention: false };
}
