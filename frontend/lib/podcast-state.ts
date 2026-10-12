// An episode's state for the person looking at it, and the words for it.
// The server sends the caller's own state with every episode (progress is per
// user): new, in progress with a position, or played.
//
// Pure, so node:test covers it (podcast-state.test.ts).

import { formatDuration } from "./format.ts";

export type EpisodeState =
  | { kind: "new" }
  | { kind: "in_progress"; position_sec: number }
  | { kind: "played" };

/** "New", "Played", "50 min left", "1 hr 20 min left", or "Resume at 10:00"
 *  when the length is not known. */
export function episodeStateLabel(state: EpisodeState, durationSec?: number | null): string {
  if (state.kind === "new") return "New";
  if (state.kind === "played") return "Played";
  if (durationSec == null || !(durationSec > 0)) {
    return `Resume at ${formatDuration(state.position_sec)}`;
  }
  const leftMin = Math.max(1, Math.ceil(Math.max(0, durationSec - state.position_sec) / 60));
  if (leftMin < 60) return `${leftMin} min left`;
  const hours = Math.floor(leftMin / 60);
  const rest = leftMin % 60;
  return rest ? `${hours} hr ${rest} min left` : `${hours} hr left`;
}

/** 0 to 1: how far through an episode the person is. */
export function progressFraction(state: EpisodeState, durationSec?: number | null): number {
  if (state.kind === "played") return 1;
  if (state.kind === "new") return 0;
  if (durationSec == null || !(durationSec > 0)) return 0;
  return Math.min(1, Math.max(0, state.position_sec / durationSec));
}

export function isFinished(state: EpisodeState): boolean {
  return state.kind === "played";
}
