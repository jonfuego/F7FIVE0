// Admin > Updates: wording and small pure helpers (kept apart from the React
// component so node:test can cover them; see updates.test.ts).

import type { UpdatePhase, UpdatesStatus } from "@/lib/types";

const ACTIVE = new Set<string>([
  "queued", "downloading", "verifying", "backup", "installing", "health_check", "rolling_back",
]);

export function isActivePhase(phase: string): boolean {
  return ACTIVE.has(phase);
}

const PHASE_LABEL: Record<UpdatePhase, string> = {
  idle: "No update running",
  queued: "Starting the updater",
  downloading: "Downloading the Setup",
  verifying: "Checking the Setup",
  backup: "Backing up the database",
  installing: "Installing the new version",
  health_check: "Checking that the new version works",
  rolling_back: "Going back to the old version",
  done: "Updated",
  rolled_back: "Went back to the old version",
  failed: "The update didn't finish",
};

export function phaseLabel(phase: string): string {
  return (PHASE_LABEL as Record<string, string>)[phase] ?? phase;
}

/** The steps shown as a progress strip, in order. */
export const UPDATE_STEPS = ["downloading", "verifying", "backup", "installing", "health_check"] as const;

// Short labels for the five phase chips, so they fit the strip instead of
// being cut off mid-word ("Downloading the", "Checking the"). Ordered to match
// UPDATE_STEPS.
const PHASE_CHIP_LABEL: Record<(typeof UPDATE_STEPS)[number], string> = {
  downloading: "Download",
  verifying: "Verify",
  backup: "Back up",
  installing: "Install",
  health_check: "Health check",
};

/** The short chip label for a strip phase: Download, Verify, Back up, Install,
 * Health check. Falls back to the long label for anything off the strip. */
export function phaseChipLabel(phase: string): string {
  return (PHASE_CHIP_LABEL as Record<string, string>)[phase] ?? phaseLabel(phase);
}

/** Which step is current: 0 to 4, 5 when finished, -1 when the strip doesn't apply. */
export function stepIndex(phase: string): number {
  if (phase === "queued") return 0;
  if (phase === "rolling_back") return UPDATE_STEPS.length - 1;
  if (phase === "done") return UPDATE_STEPS.length;
  return (UPDATE_STEPS as readonly string[]).indexOf(phase);
}

const ERROR_TEXT: Record<string, string> = {
  admin_password_required: "Enter your admin password to upload a Setup.",
  admin_password_incorrect: "That isn't your admin password.",
  too_many_attempts: "Too many wrong passwords. Wait 15 minutes and try again.",
  untrusted_setup:
    "F7FIVE0 only installs a Setup that matches a published release or carries the F7FIVE0 signature. This file is neither, so it was refused.",
  release_unreachable:
    "Couldn't reach GitHub to check this file against the published release. Check the internet connection and try again.",
  not_newer: "That version isn't newer than the one installed. F7FIVE0 never installs the same or an older version.",
  no_update: "There's no newer version to install. Check for updates first.",
  no_checksums: "This release has no checksums, so F7FIVE0 won't install it.",
  no_setup: "This release has no Setup file to install.",
  update_running: "An update is already running. Wait for it to finish.",
  too_large: "That file is bigger than a F7FIVE0 Setup can be, so it was refused.",
  not_an_exe: "That file isn't a Windows program, so it was refused.",
  no_version: "That file doesn't say which F7FIVE0 version it is, so it was refused.",
  host_not_allowed: "That download address isn't one F7FIVE0 trusts, so nothing was downloaded.",
  hash_mismatch: "The download doesn't match its published checksum, so it was thrown away.",
  no_checksum_line: "The release's checksum list has no entry for this Setup, so it was not installed.",
  download_failed: "The download didn't finish. Try again in a few minutes.",
  helper_unavailable: "The updater isn't installed on this server. Run the new Setup by hand once; it adds the updater.",
  helper_failed: "The server couldn't start the updater. See the F7FIVE0 logs, or run Setup again.",
  bad_origin: "The browser didn't send this from F7FIVE0's own page, so the server refused it.",
};

/** Words for an API error code (the `detail`), else the fallback text. */
export function updateErrorText(code: string | null | undefined, fallback?: string | null): string {
  if (code && ERROR_TEXT[code]) return ERROR_TEXT[code];
  return fallback || "Something went wrong.";
}

/** Why "Update" is unavailable when a newer version exists. */
export function blockedText(reason: UpdatesStatus["install_blocked"]): string | null {
  switch (reason) {
    case "no_checksums":
      return "This release has no checksums, so F7FIVE0 won't install it. Use a Setup from a release that has them.";
    case "no_setup":
      return "This release has no Setup file to install.";
    case "helper_unavailable":
      return "The updater isn't installed on this server. Run the new Setup by hand once; it adds the updater.";
    case "running":
      return "An update is already running.";
    default:
      return null;
  }
}

export function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = n / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  const text = value >= 10 ? String(Math.round(value)) : String(Math.round(value * 10) / 10);
  return `${text} ${units[i]}`;
}

/** "5 minutes ago", "3 hours ago", "2 days ago", or "never". */
export function checkedAgo(iso: string | null | undefined, now: number = Date.now()): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(t)) return "never";
  const seconds = Math.max(0, Math.round((now - t) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes === 1 ? "1 minute ago" : `${minutes} minutes ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

export const UP_TO_DATE = "You're up to date.";

/**
 * The two places that can say "You're up to date." on Admin > Updates: a hint
 * under "Latest version" and the notice after "Check now". Only one of them
 * says it at a time. After a check, the notice wins (it answers the click);
 * otherwise the hint shows once the latest version is known.
 */
export function upToDateMessages(input: {
  latestVersion: string | null;
  updateAvailable: boolean;
  checkError: string | null;
  checkedNow: boolean;
}): { hint: string | undefined; notice: string | null } {
  let notice: string | null = null;
  if (input.checkedNow && !input.checkError) {
    notice = input.updateAvailable ? `Version ${input.latestVersion} is available.` : UP_TO_DATE;
  }
  const hint = input.latestVersion && !input.updateAvailable && notice !== UP_TO_DATE ? UP_TO_DATE : undefined;
  return { hint, notice };
}

/** The admin password rides in a header, so it is percent-encoded UTF-8
 *  (headers carry Latin-1 only). The server decodes it. */
export function encodePasswordHeader(password: string): string {
  return encodeURIComponent(password);
}

/** The result line for a finished run, or null while it runs or when idle. */
export function runSummary(run: { phase: string; from_version: string | null; to_version: string | null }): string | null {
  const from = run.from_version ?? "the old version";
  const to = run.to_version ?? "the new version";
  if (run.phase === "done") return `Updated from ${from} to ${to}. Phones on the old app are offered the new one.`;
  if (run.phase === "rolled_back") return `The update to ${to} didn't work, so F7FIVE0 went back to ${from}. Your data is as it was before.`;
  if (run.phase === "failed") return "The update didn't finish.";
  return null;
}

/** "0:42", "4:05", "1:02:10". */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${ss}`;
  return `${m}:${ss}`;
}

// The updater stops the API and web app right after it checks the Setup (to
// back up the database) and starts them again only when Setup is done. While
// they are down this page can't read the run, so the last phase it saw is
// usually "Starting the updater" even though the work has moved on.
const OFFLINE_FROM = new Set<string>(["queued", "downloading", "verifying", "backup", "installing"]);

/** After this long offline, the card also says where the update log is. */
export const OFFLINE_SLOW_MS = 15 * 60 * 1000;

export type OfflineView = {
  /** Phase to show on the strip and as the title. */
  phase: UpdatePhase;
  /** The line under the strip. */
  message: string;
  /** Extra hint once it has been offline a long time, else null. */
  slowHint: string | null;
};

/**
 * What the run card shows while F7FIVE0 can't be reached during an update, or
 * null when it can (or no update is running). Losing contact means the
 * services are stopped, which only happens from the backup step on, so the
 * strip moves to Install (Setup is by far the longest step) and a timer counts
 * the time offline.
 */
export function offlineView(
  run: { phase: string; active: boolean; id?: string | null },
  lostSince: number | null,
  now: number = Date.now(),
): OfflineView | null {
  if (!run.active || lostSince === null) return null;
  const elapsed = formatElapsed(now - lostSince);
  if (run.phase === "health_check" || run.phase === "rolling_back") {
    return {
      phase: run.phase as UpdatePhase,
      message: `F7FIVE0 is restarting. Offline for ${elapsed}. This page keeps checking by itself.`,
      slowHint: null,
    };
  }
  if (!OFFLINE_FROM.has(run.phase)) return null;
  const slow = now - lostSince >= OFFLINE_SLOW_MS;
  const log = run.id ? `logs\\update-${run.id}.log` : "logs folder";
  return {
    phase: "installing",
    message:
      `F7FIVE0 is offline while Setup installs the new version. This takes a few minutes. ` +
      `Offline for ${elapsed}. This page keeps checking and shows the result when F7FIVE0 is back.`,
    slowHint: slow
      ? `This is taking longer than usual. On the server, the update log is in the F7FIVE0 install folder, ${log}.`
      : null,
  };
}
