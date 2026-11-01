// Admin dashboard: the pure rules behind the /admin overview and the section
// list on every /admin/<area> page. No React and no "@/" imports, so node:test
// covers it (admin-dashboard.test.ts), like admin-sections.ts.
//
// The overview reads a handful of endpoints that already exist. This file turns
// what they return into:
//   - the "Needs attention" items (buildAttentionItems)
//   - the five status tiles (versionTile, remoteTile, streamingTile,
//     storageMeters, libraryTile)
//   - the ten settings tiles (settingsTiles)
//   - the old /admin#<section> links (adminRedirectForHash)
//
// A new admin area needs three things: a subpage under app/admin/<area>, an
// entry in ADMIN_AREAS (its tile and its place in the section list), and a
// hash entry in ADMIN_HASH_MAP so an old link still lands.

import { remoteAccessSummary, updatesSummary } from "./admin-sections.ts";
import { healthViewHref } from "./library-health-view.ts";
import { scanRowHref, type ScanRow } from "./scans-rows.ts";

// ---------------------------------------------------------------------------
// Areas, hashes and the section list
// ---------------------------------------------------------------------------
export type AdminAreaId =
  | "users" | "library-folders" | "scans" | "metadata" | "arr"
  | "audio-analysis" | "remote-access" | "updates" | "activity"
  | "library-health" | "organizer";

export type AdminArea = { id: AdminAreaId; label: string; href: string };

/** The eleven settings areas, in the order of the section list and the tile grid. */
export const ADMIN_AREAS: readonly AdminArea[] = [
  { id: "users", label: "Users", href: "/admin/users" },
  { id: "library-folders", label: "Libraries", href: "/admin/library-folders" },
  { id: "scans", label: "Scans", href: "/admin/scans" },
  { id: "metadata", label: "Metadata", href: "/admin/metadata" },
  { id: "arr", label: "Radarr, Sonarr and Lidarr", href: "/admin/arr" },
  { id: "audio-analysis", label: "Audio analysis", href: "/admin/audio-analysis" },
  { id: "library-health", label: "Library health", href: "/admin/library-health" },
  { id: "organizer", label: "Organizer", href: "/admin/organizer" },
  { id: "remote-access", label: "Remote access", href: "/admin/remote-access" },
  { id: "updates", label: "Updates", href: "/admin/updates" },
  { id: "activity", label: "Activity log", href: "/admin/activity" },
];

export const ADMIN_HOME = "/admin";

/** Old section ids (the collapsible cards used to have them as anchors) and
 *  where each one lives now. Server health and Active streams moved onto the
 *  overview itself, so those two stay on /admin. */
export const ADMIN_HASH_MAP: Readonly<Record<string, string>> = {
  users: "/admin/users",
  updates: "/admin/updates",
  "remote-access": "/admin/remote-access",
  "library-folders": "/admin/library-folders",
  scans: "/admin/scans",
  metadata: "/admin/metadata",
  arr: "/admin/arr",
  "audio-analysis": "/admin/audio-analysis",
  "library-health": "/admin/library-health",
  organizer: "/admin/organizer",
  sessions: "/admin/activity",
  "auth-events": "/admin/activity",
  history: "/admin/activity",
  health: ADMIN_HOME,
  "active-streams": ADMIN_HOME,
};

/** Where an old /admin#<section> link should go, or null when the visitor
 *  should stay on /admin (no hash, an unknown hash, or a section that now
 *  lives on the overview). Takes the hash with or without the "#". */
export function adminRedirectForHash(hash: string | null | undefined): string | null {
  const key = (hash ?? "").replace(/^#/, "");
  if (!key || !Object.prototype.hasOwnProperty.call(ADMIN_HASH_MAP, key)) return null;
  const target = ADMIN_HASH_MAP[key];
  return target === ADMIN_HOME ? null : target;
}

/** An in-app link that may still carry an old anchor ("/admin#metadata", which
 *  the backend's reminders send) comes back as the subpage it lives on now.
 *  Anything else is returned unchanged. */
export function resolveAdminHref(href: string): string {
  const hit = /^\/admin#(.+)$/.exec(href);
  if (!hit) return href;
  return adminRedirectForHash(hit[1]) ?? href;
}

/** Which area a pathname belongs to ("/admin/users" and "/admin/users/x" are
 *  both Users), or null on the overview and anywhere else. */
export function currentAreaId(pathname: string | null | undefined): AdminAreaId | null {
  const path = (pathname ?? "").replace(/\/+$/, "");
  const hit = ADMIN_AREAS.find((a) => path === a.href || path.startsWith(`${a.href}/`));
  return hit ? hit.id : null;
}

// ---------------------------------------------------------------------------
// Shared small helpers
// ---------------------------------------------------------------------------
export function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "just now", "5 minutes ago", "3 hours ago", "2 days ago". Same wording as
 *  scans-rows.ts. A bad date reads "a while ago". */
export function relativeTime(iso: string | null | undefined, now: number): string {
  if (!iso) return "never";
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

export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

/** "1:05" or "1:02:03" from seconds. */
export function formatPosition(sec: number): string {
  if (!sec || sec <= 0) return "0:00";
  const whole = Math.floor(sec);
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

/** The first letter of a name, uppercased, for the avatar disc. */
export function initialOf(name: string | null | undefined): string {
  const trimmed = (name ?? "").trim();
  return trimmed ? trimmed.charAt(0).toUpperCase() : "?";
}

export type Tone = "neutral" | "warning" | "danger" | "positive";

// ---------------------------------------------------------------------------
// Needs attention
// ---------------------------------------------------------------------------
/** Seconds an encode must stay under 1.0x realtime before the overview flags
 *  it. A brief dip is normal; 30 s means the box can't keep up. */
export const SLOW_TRANSCODE_SEC = 30;

export type ReminderLike = {
  id: string;
  title: string;
  body: string;
  action_label: string;
  action_href: string;
};

export type TranscodeLike = {
  id: string;
  user_id: string;
  user_display_name: string;
  title: string;
  variant: string;
  direct_play: boolean;
  started_at: string;
  bytes_served: number;
  speed: number | null;
  below_realtime_sec: number;
};

export type UpdatesLike = {
  installed_version: string;
  phone_app_version: string | null;
  latest_version: string | null;
  update_available: boolean;
  checked_at: string | null;
  run: { active: boolean } | null;
};

export type RemoteLike = {
  public_url: string | null;
  method: string | null;
  reachable: boolean | null;
};

/** One *arr root folder, from GET /api/admin/path-mappings/arr-roots. */
export type ArrRootLike = {
  app: string;
  label: string;
  path: string;
  translated: string;
  mapped: boolean;
  reachable: boolean;
  /** The drive letter the service cannot see, when that is why it is unreachable. */
  drive: string | null;
};

export type AttentionKind = "reminder" | "transcode" | "scan" | "root" | "update" | "remote" | "health";

export type LibraryHealthLike = {
  missing_files_eligible: number;
  unreachable_folders: number;
  duplicate_movie_versions?: number;
  duplicate_episode_versions?: number;
  music_duplicates?: number;
  flipflop_warnings?: string[];
};

export type AttentionItem = {
  /** Stable key for React. */
  id: string;
  kind: AttentionKind;
  /** One line. */
  text: string;
  /** Optional second line (a reminder's body). */
  detail: string | null;
  linkLabel: string;
  href: string;
};

export type AttentionInputs = {
  reminders: ReminderLike[] | null;
  transcodes: TranscodeLike[] | null;
  scanRows: ScanRow[] | null;
  updates: UpdatesLike | null;
  remote: RemoteLike | null;
  /** The *arr apps' root folders; leave out (or null) when not loaded. */
  arrRoots?: ArrRootLike[] | null;
  /** Library health counts; leave out (or null) when not loaded. */
  libraryHealth?: LibraryHealthLike | null;
};

/** The "Streaming now" panel is on the overview, so a slow-stream item links to
 *  its anchor. */
export const STREAMING_NOW_HREF = "/admin#streaming-now";

function slowTranscodeText(t: TranscodeLike): string {
  const sec = Math.round(t.below_realtime_sec);
  const speed = t.speed === null || t.speed === undefined ? null : `${t.speed.toFixed(2)}x`;
  const detail = speed ? `${speed} for ${sec} s` : `for ${sec} s`;
  return `${t.user_display_name}'s stream of ${t.title} is transcoding below realtime (${detail})`;
}

/** The second line of a scan item: the first file that failed and why, else
 *  what the row says about missing files, else null. */
export function scanAttentionDetail(row: ScanRow): string | null {
  const first = row.errorItems[0];
  if (first) {
    const more = row.errorItems.length + row.errorsUnlisted - 1;
    const head = first.path ? `${first.path}: ${first.reason}` : first.reason;
    return more > 0 ? `${head} (and ${more} more)` : head;
  }
  return row.hint ? row.hint.text : null;
}

/** Everything that needs the admin's eye, in this order: reminders, slow
 *  streams, scans that failed, *arr folders the service can't open, an update
 *  ready to install, remote access that can't be reached. Empty when all is well. A source that did not load (null)
 *  adds nothing. */
export function buildAttentionItems(inputs: AttentionInputs): AttentionItem[] {
  const items: AttentionItem[] = [];

  for (const r of inputs.reminders ?? []) {
    items.push({
      id: `reminder:${r.id}`,
      kind: "reminder",
      text: r.title,
      detail: r.body || null,
      linkLabel: r.action_label,
      href: resolveAdminHref(r.action_href),
    });
  }

  for (const t of inputs.transcodes ?? []) {
    if (t.direct_play) continue;
    if (t.below_realtime_sec >= SLOW_TRANSCODE_SEC) {
      items.push({
        id: `transcode:${t.id}`,
        kind: "transcode",
        text: slowTranscodeText(t),
        detail: null,
        linkLabel: "See stream",
        href: STREAMING_NOW_HREF,
      });
    }
  }

  for (const row of inputs.scanRows ?? []) {
    if (row.state === "error") {
      items.push({
        id: `scan:${row.id}`,
        kind: "scan",
        text: `${row.label} scan needs attention: ${row.result || "failed"}`,
        detail: scanAttentionDetail(row),
        linkLabel: "See the errors",
        href: scanRowHref(row.id),
      });
    }
  }

  for (const root of inputs.arrRoots ?? []) {
    if (root.reachable) continue;
    items.push({
      id: `root:${root.app}:${root.path}`,
      kind: "root",
      text: root.drive
        ? `${root.label}'s folder ${root.path} is on drive ${root.drive}, which the F7FIVE0 service can't see`
        : `${root.label}'s folder ${root.path} can't be opened by the F7FIVE0 service`,
      detail: null,
      linkLabel: "Add a path mapping",
      href: "/admin/library-folders",
    });
  }

  const upd = inputs.updates;
  if (upd && upd.update_available && upd.latest_version && !upd.run?.active) {
    items.push({
      id: "update",
      kind: "update",
      text: `F7FIVE0 ${upd.latest_version} is ready to install`,
      detail: null,
      linkLabel: "Open Updates",
      href: "/admin/updates",
    });
  }

  if (inputs.remote && remoteAccessSummary(inputs.remote).attention) {
    items.push({
      id: "remote",
      kind: "remote",
      text: `Remote access is set up but not reachable (${remoteAccessSummary(inputs.remote).text})`,
      detail: null,
      linkLabel: "Open Remote access",
      href: "/admin/remote-access",
    });
  }

  const lh = inputs.libraryHealth;
  if (lh && lh.missing_files_eligible > 0) {
    items.push({
      id: "health:missing",
      kind: "health",
      text: `${plural(lh.missing_files_eligible, "missing file", "missing files")} eligible for cleanup`,
      detail: null,
      linkLabel: "See the files",
      href: healthViewHref("eligible"),
    });
  }
  if (lh && lh.unreachable_folders > 0) {
    items.push({
      id: "health:unreachable",
      kind: "health",
      text: `${plural(lh.unreachable_folders, "library folder", "library folders")} unreachable`,
      detail: null,
      linkLabel: "See the folders",
      href: healthViewHref("unreachable"),
    });
  }
  if (lh && (lh.duplicate_movie_versions ?? 0) > 0) {
    items.push({
      id: "health:dup-movie-versions",
      kind: "health",
      text: `${plural(lh.duplicate_movie_versions!, "movie", "movies")} have duplicate versions`,
      detail: null,
      linkLabel: "Open Library health",
      href: "/admin/library-health",
    });
  }
  if (lh && (lh.duplicate_episode_versions ?? 0) > 0) {
    items.push({
      id: "health:dup-ep-versions",
      kind: "health",
      text: `${plural(lh.duplicate_episode_versions!, "episode", "episodes")} have duplicate versions`,
      detail: null,
      linkLabel: "Open Library health",
      href: "/admin/library-health",
    });
  }
  if (lh && (lh.music_duplicates ?? 0) > 0) {
    items.push({
      id: "health:music-dupes",
      kind: "health",
      text: `${plural(lh.music_duplicates!, "duplicate track", "duplicate tracks")} flagged`,
      detail: null,
      linkLabel: "Open Library health",
      href: "/admin/library-health",
    });
  }
  if (lh && (lh.flipflop_warnings?.length ?? 0) > 0) {
    const n = lh.flipflop_warnings!.length;
    items.push({
      id: "health:flipflop",
      kind: "health",
      text: `Organizer: ${plural(n, "library ownership conflict", "library ownership conflicts")}`,
      detail: null,
      linkLabel: "Open Organizer",
      href: "/admin/organizer",
    });
  }

  return items;
}

// ---------------------------------------------------------------------------
// Meters
// ---------------------------------------------------------------------------
/** A meter at this percent or more turns to warning. */
export const METER_WARN_PERCENT = 90;

export type Meter = {
  /** Whole percent used, 0..100. Floored, so 89.9 reads 89 and is not a warning. */
  percent: number;
  warn: boolean;
  /** "Almost full" when warn, else null. */
  word: string | null;
};

export function meterState(used: number, total: number): Meter {
  if (!total || total <= 0 || !Number.isFinite(used)) return { percent: 0, warn: false, word: null };
  const percent = Math.min(100, Math.max(0, Math.floor((used / total) * 100)));
  const warn = percent >= METER_WARN_PERCENT;
  return { percent, warn, word: warn ? "Almost full" : null };
}

export type HealthLike = {
  transcode_cache_bytes: number;
  transcode_cache_max_bytes: number;
  cache_disk_free_bytes: number;
  cache_disk_total_bytes: number;
  art_disk_free_bytes: number;
  art_disk_total_bytes: number;
  open_transcode_sessions: number;
  last_sync_at: string | null;
};

export type StorageMeter = Meter & {
  id: "cache" | "cache-disk" | "art-disk";
  label: string;
  /** "12 GB of 50 GB". */
  value: string;
};

/** The Storage tile's three meters. The cache fills toward its cap. The two
 *  drives are shown by how much of the drive is used. */
export function storageMeters(health: HealthLike): StorageMeter[] {
  const cacheDiskUsed = health.cache_disk_total_bytes - health.cache_disk_free_bytes;
  const artDiskUsed = health.art_disk_total_bytes - health.art_disk_free_bytes;
  return [
    {
      id: "cache",
      label: "Transcode cache",
      value: `${formatBytes(health.transcode_cache_bytes)} of ${formatBytes(health.transcode_cache_max_bytes)}`,
      ...meterState(health.transcode_cache_bytes, health.transcode_cache_max_bytes),
    },
    {
      id: "cache-disk",
      label: "Cache disk free",
      value: `${formatBytes(health.cache_disk_free_bytes)} of ${formatBytes(health.cache_disk_total_bytes)}`,
      ...meterState(cacheDiskUsed, health.cache_disk_total_bytes),
    },
    {
      id: "art-disk",
      label: "Artwork disk free",
      value: `${formatBytes(health.art_disk_free_bytes)} of ${formatBytes(health.art_disk_total_bytes)}`,
      ...meterState(artDiskUsed, health.art_disk_total_bytes),
    },
  ];
}

// ---------------------------------------------------------------------------
// Status tiles
// ---------------------------------------------------------------------------
export type VersionTile = {
  installed: string;
  phone: string | null;
  /** "current": up to date. "available": an update can be installed. "updating":
   *  an update is running. "unknown": no answer from the update check yet. */
  state: "current" | "available" | "updating" | "unknown";
  latest: string | null;
  /** "Update to 1.0.15", else null. */
  buttonLabel: string | null;
  /** "Checked 5 minutes ago", or "Not checked yet". */
  checked: string;
};

export function versionTile(updates: UpdatesLike, now: number): VersionTile {
  const base = {
    installed: updates.installed_version,
    phone: updates.phone_app_version,
    latest: updates.latest_version,
    checked: updates.checked_at ? `Checked ${relativeTime(updates.checked_at, now)}` : "Not checked yet",
  };
  if (updates.run?.active) return { ...base, state: "updating", buttonLabel: null };
  if (updates.update_available && updates.latest_version) {
    return { ...base, state: "available", buttonLabel: `Update to ${updates.latest_version}` };
  }
  if (!updates.checked_at && !updates.latest_version) return { ...base, state: "unknown", buttonLabel: null };
  return { ...base, state: "current", buttonLabel: null };
}

const METHOD_NAME: Record<string, string> = {
  tailscale: "Tailscale",
  cloudflare: "Cloudflare",
  portforward: "Port forwarding",
  token: "Cloudflare tunnel token",
};

export type RemoteTile = {
  method: string;
  /** "Connected", "Not reachable", "Set up" (on, not checked yet) or "Off". */
  status: "Connected" | "Not reachable" | "Set up" | "Off";
  tone: Tone;
  host: string | null;
};

function hostOf(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).host;
  } catch {
    return url.replace(/^https?:\/\//, "").replace(/\/.*$/, "") || null;
  }
}

export function remoteTile(remote: RemoteLike): RemoteTile {
  if (!remote.public_url) return { method: "Remote access", status: "Off", tone: "neutral", host: null };
  const method = remote.method ? METHOD_NAME[remote.method] ?? remote.method : "On";
  const host = hostOf(remote.public_url);
  if (remote.reachable === false) return { method, status: "Not reachable", tone: "warning", host };
  if (remote.reachable === true) return { method, status: "Connected", tone: "positive", host };
  return { method, status: "Set up", tone: "neutral", host };
}

export type SessionLike = {
  id: string;
  user_id: string;
  username: string;
  display_name: string;
  device_label: string | null;
  client_type: string;
  created_at: string;
  last_seen_at: string | null;
  expires_at: string;
};

export type StreamingTile = {
  count: number;
  direct: number;
  transcode: number;
  /** Distinct people with a session. */
  people: number;
  summary: string;
  peopleText: string;
};

export function streamingTile(transcodes: TranscodeLike[], sessions: SessionLike[]): StreamingTile {
  const direct = transcodes.filter((t) => t.direct_play).length;
  const transcode = transcodes.length - direct;
  const people = new Set(sessions.map((s) => s.user_id)).size;
  return {
    count: transcodes.length,
    direct,
    transcode,
    people,
    summary: `${direct} direct play · ${transcode} transcode`,
    peopleText: `${plural(people, "person", "people")} signed in`,
  };
}

export type LibraryTile = {
  /** "Scanning" (warning), "Failed" (danger), "Idle". */
  state: "Scanning" | "Failed" | "Idle";
  tone: Tone;
  /** Names of the libraries running or failed, e.g. "Movies, TV". */
  detail: string;
  lastSync: string;
};

export function libraryTile(rows: ScanRow[], lastSyncAt: string | null, now: number): LibraryTile {
  const running = rows.filter((r) => r.state === "running");
  const failed = rows.filter((r) => r.state === "error");
  const lastSync = lastSyncAt ? `Last sync ${relativeTime(lastSyncAt, now)}` : "Last sync never";
  if (running.length > 0) {
    return { state: "Scanning", tone: "warning", detail: running.map((r) => r.label).join(", "), lastSync };
  }
  if (failed.length > 0) {
    return { state: "Failed", tone: "danger", detail: failed.map((r) => r.label).join(", "), lastSync };
  }
  return { state: "Idle", tone: "neutral", detail: "", lastSync };
}

// ---------------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------------
export type StreamLine = {
  id: string;
  initial: string;
  title: string;
  user: string;
  started: string;
  bytes: string;
  direct: boolean;
  /** "DIRECT" or "720p · 1.20x". */
  tag: string;
  slow: boolean;
};

export function streamLines(transcodes: TranscodeLike[], now: number): StreamLine[] {
  return transcodes.map((t) => {
    const speed = t.speed === null || t.speed === undefined ? null : `${t.speed.toFixed(2)}x`;
    return {
      id: t.id,
      initial: initialOf(t.user_display_name),
      title: t.title,
      user: t.user_display_name,
      started: `Started ${relativeTime(t.started_at, now)}`,
      bytes: `${formatBytes(t.bytes_served)} served`,
      direct: t.direct_play,
      tag: t.direct_play ? "DIRECT" : speed ? `${t.variant} · ${speed}` : t.variant,
      slow: !t.direct_play && t.below_realtime_sec >= SLOW_TRANSCODE_SEC,
    };
  });
}

/** The newest sessions first, by last seen (else created). */
export function latestSessions(sessions: SessionLike[], limit: number): SessionLike[] {
  const stamp = (s: SessionLike) => Date.parse(s.last_seen_at ?? s.created_at) || 0;
  return [...sessions].sort((a, b) => stamp(b) - stamp(a)).slice(0, limit);
}

export type AuthEventLike = {
  id: string;
  user_id: string | null;
  username: string | null;
  event: string;
  ip: string | null;
  user_agent: string | null;
  at: string;
};

export type EventLine = {
  id: string;
  /** "Failed sign-in for jon" or the event text. */
  text: string;
  failed: boolean;
  when: string;
  ip: string | null;
};

/** Event names the server writes for a sign-in that did not work. Matched on
 *  the lowercase text so "login_failed" and "Failed sign-in" both count. */
export function isFailedEvent(event: string): boolean {
  const e = event.toLowerCase();
  return e.includes("fail") || e.includes("denied") || e.includes("locked") || e.includes("throttle");
}

/** A short name for an auth event. The server writes "login_success",
 *  "passkey_login:pwa", "admin_reset_password:<id>"; anything unknown reads as
 *  its name with spaces. */
export function eventLabel(event: string): string {
  const base = event.split(":")[0].toLowerCase();
  if (base === "login_success") return "Signed in";
  if (base === "passkey_login") return "Signed in with a passkey";
  if (base === "logout" || base === "logout_all") return "Signed out";
  const words = base.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function eventLines(events: AuthEventLike[], now: number): EventLine[] {
  return events.map((e) => {
    const who = e.username ?? "unknown";
    const failed = isFailedEvent(e.event);
    return {
      id: e.id,
      text: failed ? `Failed sign-in for ${who}` : `${eventLabel(e.event)}: ${who}`,
      failed,
      when: relativeTime(e.at, now),
      ip: e.ip,
    };
  });
}

// ---------------------------------------------------------------------------
// Settings tiles
// ---------------------------------------------------------------------------
export type UserLike = { id: string; role: string };
export type MetadataLike = { tmdb: { configured: boolean } };
export type ArrLike = { apps: { app: string; label: string; configured: boolean }[] };
export type AudioProgressLike = { analyzed: number; total: number; pending: number };
export type FoldersLike = { libraries: { folders: unknown[] }[] };

export type SettingsSources = {
  users: UserLike[] | null;
  folders: FoldersLike | null;
  scanSummary: { text: string; attention: boolean } | null;
  metadata: MetadataLike | null;
  arr: ArrLike | null;
  audio: AudioProgressLike | null;
  remote: RemoteLike | null;
  updates: UpdatesLike | null;
  libraryHealth?: LibraryHealthLike | null;
};

export type SettingsTile = {
  id: AdminAreaId;
  label: string;
  href: string;
  /** One line. "" until the source has loaded. */
  status: string;
  tone: Tone;
};

export function arrStatus(arr: ArrLike): string {
  const on = arr.apps.filter((a) => a.configured).map((a) => a.label);
  return on.length > 0 ? `${on.join(", ")} connected` : "Not connected";
}

/** The ten tiles of the settings grid, in ADMIN_AREAS order. A source that has
 *  not loaded gives an empty status; the tile is still a link. */
export function settingsTiles(src: SettingsSources): SettingsTile[] {
  const status: Record<AdminAreaId, { text: string; tone: Tone }> = {
    users: { text: "", tone: "neutral" },
    "library-folders": { text: "", tone: "neutral" },
    scans: { text: "", tone: "neutral" },
    metadata: { text: "", tone: "neutral" },
    arr: { text: "", tone: "neutral" },
    "audio-analysis": { text: "", tone: "neutral" },
    "library-health": { text: "", tone: "neutral" },
    organizer: { text: "Rename and retag library files", tone: "neutral" },
    "remote-access": { text: "", tone: "neutral" },
    updates: { text: "", tone: "neutral" },
    activity: { text: "Sessions, sign-ins, play history", tone: "neutral" },
  };

  if (src.users) {
    const admins = src.users.filter((u) => u.role === "admin").length;
    status.users.text = `${plural(src.users.length, "person", "people")} · ${admins} admin`;
  }
  if (src.folders) {
    const n = src.folders.libraries.reduce((sum, l) => sum + l.folders.length, 0);
    status["library-folders"].text = plural(n, "folder", "folders");
  }
  if (src.scanSummary) {
    status.scans = { text: src.scanSummary.text, tone: src.scanSummary.attention ? "warning" : "neutral" };
  }
  if (src.metadata) {
    status.metadata = src.metadata.tmdb.configured
      ? { text: "TMDB connected", tone: "neutral" }
      : { text: "TMDB key missing", tone: "warning" };
  }
  if (src.arr) status.arr.text = arrStatus(src.arr);
  if (src.audio) {
    status["audio-analysis"].text =
      src.audio.total > 0 ? `${src.audio.analyzed} of ${src.audio.total} tracks done` : "No music to analyze";
  }
  if (src.remote) {
    const s = remoteAccessSummary(src.remote);
    status["remote-access"] = { text: s.text, tone: s.attention ? "warning" : "neutral" };
  }
  if (src.updates) {
    const s = updatesSummary(src.updates);
    status.updates = { text: s.text, tone: s.attention ? "warning" : "neutral" };
  }
  if (src.libraryHealth) {
    const lh = src.libraryHealth;
    const attention = lh.missing_files_eligible > 0 || lh.unreachable_folders > 0;
    status["library-health"] = {
      text: attention
        ? `${lh.missing_files_eligible} eligible for cleanup · ${lh.unreachable_folders} unreachable`
        : "No issues",
      tone: attention ? "warning" : "neutral",
    };
  }

  return ADMIN_AREAS.map((a) => ({
    id: a.id,
    label: a.label,
    href: a.href,
    status: status[a.id].text,
    tone: status[a.id].tone,
  }));
}
