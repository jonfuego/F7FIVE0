// Is a library folder scan running? Read from GET /api/library/scan-state
// (any signed-in user). The empty library pages say so instead of "No movies
// in the library yet.", and while a scan runs `ticks` goes up every few
// seconds so the page can reload its list and show items as they are found.

"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/client-api";
import type { ScanState } from "@/lib/library-scan";

const POLL_MS = 5000;

export function useScanState(): { running: boolean; finishedAt: string | null; ticks: number } {
  const [state, setState] = useState<ScanState | null>(null);
  const [ticks, setTicks] = useState(0);
  const wasRunning = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const next = await apiGet<ScanState>("/api/library/scan-state");
        if (cancelled) return;
        setState(next);
        // One more tick when a scan ends, so the list picks up the last items.
        if (next.running || wasRunning.current) setTicks((t) => t + 1);
        wasRunning.current = next.running;
      } catch {
        // The library pages work without it.
      }
    };
    void load();
    const id = window.setInterval(() => {
      if (wasRunning.current) void load();
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return { running: state?.running ?? false, finishedAt: state?.finished_at ?? null, ticks };
}
