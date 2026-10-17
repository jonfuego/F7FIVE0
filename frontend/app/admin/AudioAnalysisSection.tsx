// Admin > Audio analysis (smart-audio backfill): analyzed against total, and the
// "Analyze music now" button.

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/client-api";
import { primaryButtonCls } from "./admin-ui";

type AudioAnalysisProgress = { analyzed: number; total: number; pending: number };

export function AudioAnalysisSection() {
  const [progress, setProgress] = useState<AudioAnalysisProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<AudioAnalysisProgress>("/api/admin/audio/progress");
      setProgress(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load progress.");
    }
  }, []);

  useEffect(() => {
    load();
    // Poll while a backfill is running so analyzed / total climbs live.
    const id = window.setInterval(load, 5_000);
    return () => window.clearInterval(id);
  }, [load]);

  async function analyzeNow() {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      await apiPost("/api/admin/audio/analyze", {});
      setStatus(
        progress && progress.total === 0
          ? "No music to analyze."
          : "Analysis queued. It runs one track at a time in the background.",
      );
      load();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Failed to start analysis.");
    } finally {
      setBusy(false);
    }
  }

  const pct =
    progress && progress.total > 0
      ? Math.min(100, Math.round((progress.analyzed / progress.total) * 100))
      : 0;

  return (
    <div>
      <p className="text-xs text-ink-3">
        Loudness leveling, the waveform scrubber, and similar-track radio need
        each track analyzed once. New music is analyzed automatically after a
        folder scan, one track at a time. Use this to kick it off right away.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={analyzeNow}
          disabled={busy}
          className={primaryButtonCls}
        >
          {busy ? "Queuing..." : "Analyze music now"}
        </button>
        {progress ? (
          <span className="text-xs text-ink-2">
            {progress.total > 0 ? (
              <>
                {progress.analyzed} / {progress.total} tracks analyzed
                {progress.pending > 0 ? ` (${progress.pending} pending)` : ""}
              </>
            ) : (
              "No music to analyze."
            )}
          </span>
        ) : error ? (
          <span className="text-xs text-hive-text">{error}</span>
        ) : null}
      </div>
      {progress && progress.total > 0 ? (
        <div className="mt-3 h-1.5 w-full max-w-md overflow-hidden rounded-full bg-surface-3">
          <div className="h-full bg-ink-2" style={{ width: `${pct}%` }} />
        </div>
      ) : null}
      {status ? <p className="mt-3 text-xs text-ink-2">{status}</p> : null}
    </div>
  );
}
