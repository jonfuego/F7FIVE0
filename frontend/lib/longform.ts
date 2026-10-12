// Shared rules for long-form audio: skip, played, chapters, speed. Podcasts use
// them today; there are no podcast-only names here so audiobooks can reuse them
// as they are. The same numbers live in backend/app/services/longform.py and
// mobile/src/player/longform.ts; keep the three in step.
//
// - Skip: back 15 s, forward 30 s.
// - Played: within 30 s of the end, or past 95 percent, whichever comes first.
//   A length that is not known never counts as played.
// - Chapters: { start_sec, title, img?, url? }, sorted by start.
// - Speed: 0.5 to 3, saved per user as the view pref `podcast_speed`.
//
// Pure, so node:test covers it (longform.test.ts).

export const SKIP_BACK_SEC = 15;
export const SKIP_FORWARD_SEC = 30;
export const PLAYED_TAIL_SEC = 30;
export const PLAYED_FRACTION = 0.95;
export const MIN_SPEED = 0.5;
export const MAX_SPEED = 3;
export const DEFAULT_SPEED = 1;

/** The speeds the menu offers. */
export const SPEEDS: readonly number[] = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3];

export type Chapter = { start_sec: number; title: string; img?: string; url?: string };

/** Where a skip back lands: 15 s earlier, never before the start. */
export function skipBack(positionSec: number): number {
  return Math.max(0, positionSec - SKIP_BACK_SEC);
}

/** Where a skip forward lands: 30 s later, never past the end when the length
 *  is known. */
export function skipForward(positionSec: number, durationSec?: number | null): number {
  const target = positionSec + SKIP_FORWARD_SEC;
  if (durationSec != null && durationSec > 0) return Math.min(durationSec, target);
  return target;
}

/** The position from which an episode counts as played, or null when its length
 *  is not known. */
export function playedThreshold(durationSec?: number | null): number | null {
  if (durationSec == null || !(durationSec > 0)) return null;
  return Math.min(durationSec - PLAYED_TAIL_SEC, durationSec * PLAYED_FRACTION);
}

export function isPlayed(positionSec: number, durationSec?: number | null): boolean {
  const threshold = playedThreshold(durationSec);
  return threshold !== null && positionSec >= threshold;
}

/** Index of the chapter playing at `positionSec`, or -1 when there are none or
 *  the position is before the first. */
export function chapterAt(chapters: readonly { start_sec: number }[], positionSec: number): number {
  const at = Math.max(0, positionSec);
  let found = -1;
  for (let i = 0; i < chapters.length; i++) {
    if (chapters[i].start_sec <= at) found = i;
    else break;
  }
  return found;
}

export function clampSpeed(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_SPEED;
  return Math.min(MAX_SPEED, Math.max(MIN_SPEED, value));
}

/** `1x`, `1.25x`, `2x`. */
export function formatSpeed(speed: number): string {
  return `${Number(speed.toFixed(2))}x`;
}
