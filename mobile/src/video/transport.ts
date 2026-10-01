/** Pure helpers for the video transport (crit 8 / 37): HLS resume offset,
 * skip-intro/credits markers, the Plex-style "Up Next" credits countdown and
 * time formatting. No native imports so they unit test in Node. */

/** GET /api/markers/{media_file_id} row. */
export interface MediaMarker {
  kind: "intro" | "credits" | string;
  start_sec: number;
  end_sec: number;
}

/** Server quantizes HLS resume offsets to 10 s buckets (api/stream.py
 * OFFSET_BUCKET_SEC). The HLS timeline then starts at 0 == bucket, so the
 * player must add the bucket back for display/progress and subtract it for
 * seeks. Direct play is always absolute (Range requests). */
export const OFFSET_BUCKET_SEC = 10;

export function hlsBaseOffset(mode: "direct" | "hls", resumeSec: number): number {
  if (mode !== "hls" || !(resumeSec > 0)) return 0;
  return Math.floor(resumeSec / OFFSET_BUCKET_SEC) * OFFSET_BUCKET_SEC;
}

/** Clamp an absolute seek target into [base, duration]. */
export function clampSeek(targetSec: number, durationSec: number, baseSec = 0): number {
  const hi = durationSec > 0 ? durationSec : Number.POSITIVE_INFINITY;
  return Math.max(baseSec, Math.min(targetSec, hi));
}

/** The marker the playhead is inside, if any (earliest first). */
export function activeMarker(absSec: number, markers: MediaMarker[] | undefined): MediaMarker | null {
  if (!markers) return null;
  return markers.find((m) => absSec >= m.start_sec && absSec < m.end_sec) ?? null;
}

/** Length of the Up Next countdown shown when the credits start (Plex shows a
 * short countdown card over the credits, then plays the next episode). */
export const UP_NEXT_COUNTDOWN_SEC = 10;

export interface UpNextState {
  show: boolean;
  /** Whole seconds left before auto-advance (0 = advance now). */
  secondsLeft: number;
}

/** Up Next state for a playhead, driven by the credits marker. Hidden when
 * there is no credits marker, no next episode, or before the credits start. */
export function upNextState(
  absSec: number,
  markers: MediaMarker[] | undefined,
  hasNext: boolean,
  countdownSec: number = UP_NEXT_COUNTDOWN_SEC,
): UpNextState {
  const credits = markers?.find((m) => m.kind === "credits");
  if (!hasNext || !credits || absSec < credits.start_sec) return { show: false, secondsLeft: countdownSec };
  const left = Math.max(0, Math.ceil(credits.start_sec + countdownSec - absSec));
  return { show: true, secondsLeft: left };
}

/** 1:02:03 / 4:05 style clock. */
export function formatClock(totalSec: number): string {
  const s = Math.max(0, Math.floor(totalSec || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(sec).padStart(2, "0")}`;
}

/** Minimum saved progress before we resume instead of starting over (matches
 * the backend's MIN_PROGRESS_SECONDS for Continue Watching). */
export const MIN_RESUME_SEC = 30;

/** Where to start a video from its saved progress row: resume an unfinished
 * item past the threshold, otherwise start at 0 (watched items restart). */
export function resumePointFor(
  p: { position_sec: number; duration_sec?: number | null; completed_at?: string | null } | null | undefined,
): number {
  if (!p || p.completed_at) return 0;
  if (!(p.position_sec >= MIN_RESUME_SEC)) return 0;
  if (p.duration_sec && p.position_sec >= p.duration_sec - 15) return 0;
  return Math.floor(p.position_sec);
}
