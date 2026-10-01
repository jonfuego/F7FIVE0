// Shared hook + helpers for rendering watched / in-progress state.
//
// Load the user's full WatchProgress map once per page mount and surface
// a lookup keyed by media_file_id. The map is cheap for a 5-user instance
// (each user can only have a few hundred rows tops) and avoids N+1 fetches
// when decorating the home rows, library grids, and detail pages.

"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/client-api";
import type { Progress } from "@/lib/types";

export type ProgressMap = Map<string, Progress>;

export function useProgressMap(): ProgressMap | null {
  const [map, setMap] = useState<ProgressMap | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await apiGet<Progress[]>("/api/library/progress");
        if (cancelled) return;
        setMap(new Map(rows.map((r) => [r.media_file_id, r])));
      } catch {
        if (cancelled) return;
        // Treat failure as "no progress known". The rest of the page
        // renders without watched overlays; we don't block the UI on this.
        setMap(new Map());
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return map;
}

export type FileStatus = "watched" | "in_progress" | null;

export function statusForFile(
  progress: Progress | undefined,
): FileStatus {
  if (!progress) return null;
  if (progress.completed_at) return "watched";
  return "in_progress";
}

export function pickProgressFor(
  map: ProgressMap | null,
  fileIds: Iterable<string>,
): Progress | undefined {
  if (!map) return undefined;
  // Prefer an in-progress file over a watched one when a parent has
  // multiple files. Callers generally have only one playable file; this
  // matters for TV where we might pick among episodes.
  let best: Progress | undefined;
  for (const id of fileIds) {
    const row = map.get(id);
    if (!row) continue;
    if (!row.completed_at) return row; // active beats completed
    best = best ?? row;
  }
  return best;
}
