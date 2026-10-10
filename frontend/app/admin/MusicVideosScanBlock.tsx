// Admin > Library: start a music videos scan now and watch it. Built on the
// same status mechanism and look as the folder scan block (ScanStatusBlock):
// the scan runs on the server, counts the files first, then imports with a
// running count, so this block shows a progress bar, "x of y", a last-finished
// time and the last error. It polls every 3 seconds while a scan runs and
// stops when it is idle.
//
// The music videos scan is filesystem-only (not *arr). One scan at a time: a
// second start while one runs answers 409.

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, ApiError } from "@/lib/client-api";
import {
  SCAN_POLL_MS, mvCountsText, mvScanHeadline, ofTotalText, scanPercent,
  shouldPollScan, type MusicVideosScanStatus,
} from "@/lib/library-scan";
import { ScanBar } from "./ScanBar";

function errorOf(err: unknown): string {
  if (err instanceof ApiError && err.detail) return String(err.detail);
  return err instanceof Error ? err.message : "Something went wrong.";
}

export function MusicVideosScanBlock() {
  const [status, setStatus] = useState<MusicVideosScanStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await apiGet<MusicVideosScanStatus>("/api/library/music-videos/scan"));
    } catch (err) {
      setMessage(errorOf(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
      // The trigger lives on the admin proxy (it is admin-only and filesystem,
      // not *arr); the status endpoint lives on the library proxy.
      setStatus(await apiPost<MusicVideosScanStatus>("/api/admin/library/music-videos", {}));
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
  const ofTotal = status ? ofTotalText(status.count, status.total) : "";

  return (
    <div className="mt-6 border-t border-neutral-800 pt-5" data-testid="mv-scan-status">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-neutral-100">Music videos scan</h3>
          <p className="mt-1 text-xs text-neutral-500" data-testid="mv-scan-headline">
            {status ? mvScanHeadline(status) : "Checking…"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void scanNow()}
          disabled={busy || running}
          className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-100 transition hover:border-neutral-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Starting…" : running ? "Scanning…" : "Scan music videos"}
        </button>
      </div>

      {status && (running || (!!status.total && status.total > 0)) ? (
        <div className="mt-3 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4">
            <span className="text-sm text-neutral-200">
              Music videos
              <span className={`ml-2 text-xs ${running ? "text-emerald-400" : "text-neutral-500"}`}>
                {running ? "scanning" : "done"}
              </span>
            </span>
            <span className="text-xs text-neutral-400">
              {ofTotal ? <span className="mr-2 text-neutral-300">{ofTotal}</span> : null}
              {mvCountsText(status)}
            </span>
          </div>
          <ScanBar percent={scanPercent(status.count, status.total)} />
        </div>
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
