// The data behind the /admin overview: one hook, one shared poll.
//
// Every source is an endpoint that already exists. They are fetched in parallel
// (Promise.allSettled), and a source that fails marks only itself, so one dead
// endpoint turns one tile or panel into "Couldn't load" with a Retry and the
// rest of the page still draws.
//
// Two groups:
//   fast  Things that change while you watch: reminders, updates, remote
//         access, health, streams, sessions, sign-in events, plays and the scan
//         statuses. Fetched on load and then every 10 s.
//   slow  Counts for the settings tiles: users, library folders (which checks
//         that each folder can be opened, so it can be slow on a NAS), metadata,
//         *arr and audio analysis. Fetched on load and then every 60 s.
// Both ride one interval, so there is one timer, not one per tile. The poll
// pauses while the tab is hidden and catches up the moment it is shown again.

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/client-api";
import type { ScanStatuses } from "@/app/admin/ScansSection";
import type {
  ActiveTranscode, AdminReminder, AdminSession, AdminUser, ArrSettings, AuthEvent,
  LibraryFolders, MetadataSettings, RemoteAccessStatus, ServerHealth, UpdatesStatus,
  WatchHistoryRow,
} from "@/lib/types";
import type {
  ArrSyncStatus, FolderScanStatus, MusicVideosScanStatus, PodcastRefreshStatus,
} from "@/lib/library-scan";

export const FAST_POLL_MS = 10_000;
/** The slow group runs on every Nth fast tick: 6 x 10 s = 60 s. */
export const SLOW_EVERY_TICKS = 6;

type AudioProgress = { analyzed: number; total: number; pending: number };

export type OverviewData = {
  reminders: AdminReminder[];
  updates: UpdatesStatus;
  remote: RemoteAccessStatus;
  health: ServerHealth;
  transcodes: ActiveTranscode[];
  sessions: AdminSession[];
  authEvents: AuthEvent[];
  history: WatchHistoryRow[];
  scans: ScanStatuses;
  users: AdminUser[];
  folders: LibraryFolders;
  metadata: MetadataSettings;
  arr: ArrSettings;
  audio: AudioProgress;
};

export type SourceKey = keyof OverviewData;

export type Source<T> = {
  /** The last answer, kept across a failed refresh. */
  data: T | null;
  /** The last attempt failed. */
  error: boolean;
  /** At least one attempt has finished. */
  loaded: boolean;
};

export type OverviewState = { [K in SourceKey]: Source<OverviewData[K]> };

const FAST_KEYS: SourceKey[] = [
  "reminders", "updates", "remote", "health", "transcodes", "sessions", "authEvents", "history", "scans",
];
const SLOW_KEYS: SourceKey[] = ["users", "folders", "metadata", "arr", "audio"];
const ALL_KEYS: SourceKey[] = [...FAST_KEYS, ...SLOW_KEYS];

const EMPTY: Source<never> = { data: null, error: false, loaded: false };

function emptyState(): OverviewState {
  const out: Record<string, Source<unknown>> = {};
  for (const key of ALL_KEYS) out[key] = EMPTY;
  return out as unknown as OverviewState;
}

const NO_SCANS: ScanStatuses = { folder: null, musicVideos: null, arr: null, podcasts: null };

// The four scan statuses are one source. If some answer and some do not, the
// ones that answer win and the rest keep their last value (as the Scans page
// does); only when none answer is the source an error.
async function loadScans(prev: ScanStatuses | null): Promise<ScanStatuses> {
  const before = prev ?? NO_SCANS;
  const [f, m, a, p] = await Promise.allSettled([
    apiGet<FolderScanStatus>("/api/admin/library/scan"),
    apiGet<MusicVideosScanStatus>("/api/library/music-videos/scan"),
    apiGet<ArrSyncStatus>("/api/admin/library/arr-sync"),
    apiGet<PodcastRefreshStatus>("/api/admin/podcasts/refresh"),
  ]);
  if ([f, m, a, p].every((r) => r.status === "rejected")) throw (f as PromiseRejectedResult).reason;
  return {
    folder: f.status === "fulfilled" ? f.value : before.folder,
    musicVideos: m.status === "fulfilled" ? m.value : before.musicVideos,
    arr: a.status === "fulfilled" ? a.value : before.arr,
    podcasts: p.status === "fulfilled" ? p.value : before.podcasts,
  };
}

function fetcher(key: SourceKey, prev: OverviewState): Promise<unknown> {
  switch (key) {
    case "reminders": return apiGet("/api/admin/reminders");
    case "updates": return apiGet("/api/admin/updates");
    case "remote": return apiGet("/api/admin/remote-access");
    case "health": return apiGet("/api/admin/health");
    case "transcodes": return apiGet("/api/admin/transcodes/active");
    case "sessions": return apiGet("/api/admin/sessions");
    case "authEvents": return apiGet("/api/admin/auth-events?limit=3");
    case "history": return apiGet("/api/admin/history/recent?limit=4");
    case "scans": return loadScans(prev.scans.data);
    case "users": return apiGet("/api/admin/users");
    case "folders": return apiGet("/api/admin/library-folders");
    case "metadata": return apiGet("/api/admin/metadata");
    case "arr": return apiGet("/api/admin/arr");
    case "audio": return apiGet("/api/admin/audio/progress");
  }
}

export function useAdminOverview(enabled: boolean): {
  state: OverviewState;
  /** Date.now() at the last finished refresh, for "5 minutes ago" text. */
  now: number;
  /** Fetch one source again (the Retry button). */
  retry: (key: SourceKey) => void;
} {
  const [state, setState] = useState<OverviewState>(emptyState);
  const [now, setNow] = useState(() => Date.now());
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const run = useCallback(async (keys: SourceKey[]) => {
    const results = await Promise.allSettled(keys.map((k) => fetcher(k, stateRef.current)));
    setState((prev) => {
      const next = { ...prev } as Record<string, Source<unknown>>;
      keys.forEach((key, i) => {
        const r = results[i];
        next[key] =
          r.status === "fulfilled"
            ? { data: r.value, error: false, loaded: true }
            : { data: (prev as unknown as Record<string, Source<unknown>>)[key].data, error: true, loaded: true };
      });
      return next as unknown as OverviewState;
    });
    setNow(Date.now());
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let tick = 0;
    void run(ALL_KEYS);

    const id = window.setInterval(() => {
      if (document.hidden) return;
      tick += 1;
      void run(tick % SLOW_EVERY_TICKS === 0 ? ALL_KEYS : FAST_KEYS);
    }, FAST_POLL_MS);

    // Back on the tab after a while away: look again at once.
    const onVisible = () => {
      if (!document.hidden) void run(FAST_KEYS);
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, run]);

  const retry = useCallback((key: SourceKey) => void run([key]), [run]);

  return { state, now, retry };
}
