// Admin > Library folders: start a folder scan now and watch it. The scan runs
// on the server and saves as it goes (every 25 items and at the end of each
// library), so counts here go up while the library pages fill in. This block
// polls every 3 seconds while a scan runs and stops when it is idle.
//
// "Run *arr sync now" (Admin > Library) is a different thing: it syncs
// Radarr / Sonarr / Lidarr and does not read the folders.

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, ApiError } from "@/lib/client-api";
import {
  LIBRARY_LABEL, SCAN_POLL_MS, countsText, scanHeadline, shouldPollScan, type FolderScanStatus,
} from "@/lib/library-scan";

const LIBRARY_ORDER = ["movies", "tv", "music"];

function errorOf(err: unknown): string {
  if (err instanceof ApiError && err.detail) return String(err.detail);
  return err instanceof Error ? err.message : "Something went wrong.";
}

function stateLabel(state: string): string {
  switch (state) {
    case "running": return "scanning";
    case "done": return "done";
    case "failed": return "failed";
    case "interrupted": return "interrupted";
    default: return "waiting";
  }
}

export function ScanStatusBlock({ refreshKey = 0 }: { refreshKey?: number }) {
  const [status, setStatus] = useState<FolderScanStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await apiGet<FolderScanStatus>("/api/admin/library/scan"));
    } catch (err) {
      setMessage(errorOf(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Saving folders starts a scan on the server; look for it right away and
  // again a moment later, once the job has had time to mark itself running.
  useEffect(() => {
    if (refreshKey === 0) return;
    void load();
    const id = window.setTimeout(() => void load(), 2000);
    return () => window.clearTimeout(id);
  }, [refreshKey, load]);

  const polling = shouldPollScan(status);
  useEffect(() => {
    if (!polling) return;
    const id = window.setInterval(() => void load(), SCAN_POLL_MS);
    return () => window.clearInterval(id);
  }, [polling, load]);

  async function scanNow() {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    try {
      setStatus(await apiPost<FolderScanStatus>("/api/admin/library/scan", {}));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setMessage("A scan is already running.");
        await load();
      } else {
        setMessage(errorOf(err));
      }
    } finally {
      setBusy(false);
    }
  }

  const running = status?.state === "running";
  const libraries = status
    ? LIBRARY_ORDER.filter((k) => status.libraries[k]).concat(
        Object.keys(status.libraries).filter((k) => !LIBRARY_ORDER.includes(k)),
      )
    : [];

  return (
    <div className="mt-8 border-t border-neutral-800 pt-5" data-testid="scan-status">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-neutral-100">Folder scan</h3>
          <p className="mt-1 text-xs text-neutral-500" data-testid="scan-headline">
            {status ? scanHeadline(status) : "Checking…"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void scanNow()}
          disabled={busy || running}
          className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-100 transition hover:border-neutral-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Starting…" : running ? "Scanning…" : "Scan folders now"}
        </button>
      </div>

      {libraries.length > 0 && status ? (
        <ul className="mt-3 space-y-1.5">
          {libraries.map((key) => {
            const lib = status.libraries[key];
            return (
              <li
                key={key}
                className="flex flex-wrap items-baseline justify-between gap-x-4 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2"
              >
                <span className="text-sm text-neutral-200">
                  {LIBRARY_LABEL[key] ?? key}
                  <span
                    className={`ml-2 text-xs ${
                      lib.state === "running" ? "text-emerald-400" : lib.state === "failed" ? "text-amber-400" : "text-neutral-500"
                    }`}
                  >
                    {stateLabel(lib.state)}
                  </span>
                </span>
                <span className="text-xs text-neutral-400">{countsText(lib)}</span>
              </li>
            );
          })}
        </ul>
      ) : null}

      {status?.last_error ? (
        <p className="mt-3 rounded-md border border-line bg-hive-tint px-3 py-2 text-xs text-hive-text" role="alert">
          {status.last_error}
        </p>
      ) : null}
      {message ? <p className="mt-2 text-xs text-neutral-400">{message}</p> : null}
    </div>
  );
}
