// Admin > Scans: every scan in one progress list, with Scan all and a button on
// each row. The rows come from lib/scans-rows.ts; this file fetches the three
// statuses, starts scans and draws the list.
//
// What each row runs: Movies, TV and Music use the folder scan when no
// Radarr / Sonarr / Lidarr is set and that app's sync when it is (never both:
// the app owns the library). Music videos always have their own scan. The
// *arr sync row syncs every app that is set. Podcasts is a folder scan of the
// podcasts library, and Podcast feeds (Refresh feeds) refreshes the feeds of the
// shows people follow. Editing the folders themselves stays in Library folders.
//
// The page calls useScanStatuses once, so the folded card can still show a
// running or failed scan (and open itself), and passes the result down.

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, ApiError } from "@/lib/client-api";
import {
  SCAN_POLL_MS, type ArrSyncStatus, type FolderScanStatus, type MusicVideosScanStatus,
  type PodcastRefreshStatus,
} from "@/lib/library-scan";
import {
  buildScanRows, scanAllPlan, scanErrors, type ScanInputs, type ScanRow, type ScanRowState,
} from "@/lib/scans-rows";
import { ScanBar } from "./ScanBar";

const IDLE_POLL_MS = 10_000;

export type ScanStatuses = {
  folder: FolderScanStatus | null;
  musicVideos: MusicVideosScanStatus | null;
  arr: ArrSyncStatus | null;
  podcasts: PodcastRefreshStatus | null;
};

/** Polls the scan statuses: every few seconds while anything runs, every
 *  10 seconds otherwise, so a scan that starts elsewhere still shows up. */
export function useScanStatuses(enabled: boolean): { statuses: ScanStatuses; refresh: () => Promise<void> } {
  const [statuses, setStatuses] = useState<ScanStatuses>({
    folder: null, musicVideos: null, arr: null, podcasts: null,
  });

  const refresh = useCallback(async () => {
    const [f, m, a, p] = await Promise.allSettled([
      apiGet<FolderScanStatus>("/api/admin/library/scan"),
      apiGet<MusicVideosScanStatus>("/api/library/music-videos/scan"),
      apiGet<ArrSyncStatus>("/api/admin/library/arr-sync"),
      apiGet<PodcastRefreshStatus>("/api/admin/podcasts/refresh"),
    ]);
    setStatuses((prev) => ({
      folder: f.status === "fulfilled" ? f.value : prev.folder,
      musicVideos: m.status === "fulfilled" ? m.value : prev.musicVideos,
      arr: a.status === "fulfilled" ? a.value : prev.arr,
      podcasts: p.status === "fulfilled" ? p.value : prev.podcasts,
    }));
  }, []);

  const running =
    statuses.folder?.state === "running" ||
    statuses.musicVideos?.state === "running" ||
    statuses.arr?.state === "running" ||
    statuses.podcasts?.state === "running";

  useEffect(() => {
    if (!enabled) return;
    void refresh();
  }, [enabled, refresh]);

  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(() => void refresh(), running ? SCAN_POLL_MS : IDLE_POLL_MS);
    return () => window.clearInterval(id);
  }, [enabled, running, refresh]);

  return { statuses, refresh };
}

/** What the rows builder needs, from the polled statuses. */
export function scanInputs(statuses: ScanStatuses): ScanInputs {
  return {
    apps: statuses.arr ? statuses.arr.configured : null,
    folders: statuses.folder?.folders ?? null,
    folder: statuses.folder,
    musicVideos: statuses.musicVideos,
    arr: statuses.arr,
    podcastRefresh: statuses.podcasts,
  };
}

const FRIENDLY: Record<string, string> = {
  scan_running: "That is already running.",
  library_not_scanned: "That library has no folder to scan, or an *arr app owns it.",
  app_not_configured: "That *arr app is not set up.",
  scan_not_started: "The scan could not be started.",
  refresh_running: "The feeds are already being refreshed.",
  refresh_not_started: "The refresh could not be started.",
};

function errorOf(err: unknown): string {
  if (err instanceof ApiError && err.detail) return FRIENDLY[String(err.detail)] ?? String(err.detail);
  return err instanceof Error ? err.message : "Something went wrong.";
}

const STATE_TEXT: Record<ScanRowState, string> = {
  running: "running",
  idle: "done",
  error: "needs attention",
  never: "not run yet",
};

const STATE_CLASS: Record<ScanRowState, string> = {
  running: "text-positive",
  idle: "text-ink-3",
  error: "text-hive-text",
  never: "text-ink-3",
};

const buttonCls =
  "shrink-0 rounded-md border border-line-strong px-3 py-1.5 text-xs font-medium text-ink transition hover:border-ink-2 disabled:cursor-not-allowed disabled:opacity-50";

export function ScansSection({
  statuses,
  refresh,
}: {
  statuses: ScanStatuses;
  refresh: () => Promise<void>;
}) {
  const inputs = scanInputs(statuses);
  const rows = buildScanRows(inputs);
  const errors = scanErrors(inputs);
  const plan = scanAllPlan(rows);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // A started scan marks itself running on the server before the request
  // returns; look again right away, then once more after the job has begun.
  async function settle() {
    await refresh();
    window.setTimeout(() => void refresh(), 2000);
  }

  async function startRow(row: ScanRow) {
    if (busy) return;
    setBusy(row.id);
    setMessage(null);
    try {
      if (row.action.kind === "folder") {
        await apiPost(`/api/admin/library/scan?library=${row.action.library}`, {});
      } else if (row.action.kind === "arr") {
        await apiPost(`/api/admin/library/sync?${row.action.apps.map((a) => `app=${a}`).join("&")}`, {});
      } else if (row.action.kind === "podcast_refresh") {
        await apiPost("/api/admin/podcasts/refresh", {});
      } else {
        await apiPost("/api/admin/library/music-videos", {});
      }
    } catch (err) {
      setMessage(`${row.label}: ${errorOf(err)}`);
    } finally {
      await settle();
      setBusy(null);
    }
  }

  async function startAll() {
    if (busy || plan.rowIds.length === 0) return;
    setBusy("all");
    setMessage(null);
    const problems: string[] = [];
    // The folder libraries go in one request and the apps in one request: each
    // of those runs one at a time on the server.
    const steps: Array<[string, () => Promise<unknown>]> = [];
    if (plan.libraries.length > 0) {
      const query = plan.libraries.map((l) => `library=${l}`).join("&");
      steps.push(["Folder scan", () => apiPost(`/api/admin/library/scan?${query}`, {})]);
    }
    if (plan.arrApps.length > 0) {
      const query = plan.arrApps.map((a) => `app=${a}`).join("&");
      steps.push(["*arr sync", () => apiPost(`/api/admin/library/sync?${query}`, {})]);
    }
    if (plan.musicVideos) {
      steps.push(["Music videos", () => apiPost("/api/admin/library/music-videos", {})]);
    }
    for (const [name, run] of steps) {
      try {
        await run();
      } catch (err) {
        problems.push(`${name}: ${errorOf(err)}`);
      }
    }
    if (problems.length > 0) setMessage(problems.join(" "));
    await settle();
    setBusy(null);
  }

  return (
    <div data-testid="scans-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-xl text-xs text-ink-3">
          Every scan in one list. Movies, TV and Music use Radarr, Sonarr or Lidarr when one is
          set up, and scan their folders when not. Add or remove folders under Library folders.
        </p>
        <button
          type="button"
          onClick={() => void startAll()}
          disabled={busy !== null || plan.rowIds.length === 0}
          className={buttonCls}
          title={plan.rowIds.length === 0 ? "Nothing can start right now." : undefined}
        >
          {busy === "all" ? "Starting…" : "Scan all"}
        </button>
      </div>

      <ul className="mt-4 space-y-1.5" data-testid="scans-list">
        {rows.map((row) => (
          <ScanListRow
            key={row.id}
            row={row}
            starting={busy === row.id}
            locked={busy !== null}
            onStart={() => void startRow(row)}
          />
        ))}
      </ul>

      {errors.map((text) => (
        <p key={text} className="mt-3 text-xs text-hive-text" role="alert">
          {text}
        </p>
      ))}
      {message ? <p className="mt-2 text-xs text-hive-text">{message}</p> : null}
    </div>
  );
}

function ScanListRow({
  row,
  starting,
  locked,
  onStart,
}: {
  row: ScanRow;
  starting: boolean;
  locked: boolean;
  onStart: () => void;
}) {
  const running = row.state === "running";
  const showReason = !row.canStart && !running && row.disabledReason;
  return (
    <li
      className="rounded-lg border border-line bg-surface-1 px-3 py-2"
      data-testid={`scan-row-${row.id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4">
            <span className="text-sm text-ink">
              {row.label}
              <span className="ml-2 text-xs text-ink-3">{row.source}</span>
              <span className={`ml-2 text-xs ${STATE_CLASS[row.state]}`}>{STATE_TEXT[row.state]}</span>
            </span>
            <span className="text-xs text-ink-2">
              {row.result}
              {row.when ? <span className="ml-2 text-ink-3">{row.when}</span> : null}
            </span>
          </div>
          {running ? (
            row.progress ? (
              <ScanBar percent={row.progress.percent} />
            ) : (
              <div
                className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-3"
                role="progressbar"
                aria-busy="true"
                aria-label={`${row.label} is running`}
              >
                <div className="h-full w-1/3 animate-pulse rounded-full bg-ink-2" />
              </div>
            )
          ) : null}
          {showReason ? <p className="mt-1 text-xs text-ink-3">{row.disabledReason}</p> : null}
        </div>
        <button
          type="button"
          onClick={onStart}
          disabled={!row.canStart || locked}
          className={buttonCls}
        >
          {starting ? "Starting…" : running ? "Running…" : buttonText(row)}
        </button>
      </div>
    </li>
  );
}

function buttonText(row: ScanRow): string {
  if (row.action.kind === "arr") return "Sync now";
  if (row.action.kind === "podcast_refresh") return "Refresh feeds";
  return "Scan now";
}
