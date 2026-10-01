/** Sleep-timer helpers. Pure so they unit test in Node. The UI offers 15/30/45/
 * 60 minutes and "end of track"; these compute the deadline and remaining time.
 * "End of track" is represented as mode "track" (no wall-clock deadline). */

export type SleepMode = "off" | "track" | "minutes";
export const SLEEP_PRESETS_MIN = [15, 30, 45, 60] as const;

export interface SleepState {
  mode: SleepMode;
  /** Epoch ms deadline for the "minutes" mode; null otherwise. */
  deadlineMs: number | null;
}

export function startMinutes(nowMs: number, minutes: number): SleepState {
  return { mode: "minutes", deadlineMs: nowMs + minutes * 60_000 };
}

export function startEndOfTrack(): SleepState {
  return { mode: "track", deadlineMs: null };
}

export function cleared(): SleepState {
  return { mode: "off", deadlineMs: null };
}

/** Whether a minutes-mode timer has elapsed and playback should pause now. */
export function isElapsed(state: SleepState, nowMs: number): boolean {
  return state.mode === "minutes" && state.deadlineMs != null && nowMs >= state.deadlineMs;
}

/** Seconds remaining for a minutes-mode timer (0 if elapsed / not applicable). */
export function remainingSec(state: SleepState, nowMs: number): number {
  if (state.mode !== "minutes" || state.deadlineMs == null) return 0;
  return Math.max(0, Math.round((state.deadlineMs - nowMs) / 1000));
}
