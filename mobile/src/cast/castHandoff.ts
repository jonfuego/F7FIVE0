/** Pure decisions for the video cast hand-off (no native imports, unit tested).
 *
 * While a Cast receiver plays the movie the phone's own Video stays unmounted:
 * a local player that kept fetching, or whose error recovery called loadUrl,
 * started a second stream mid-cast. On disconnect the phone picks up where the
 * receiver left off, not where the phone paused.
 */

/** True from a successful hand-off until the session ends. A connected session
 * whose hand-off failed (or has not finished) is not casting: local playback
 * keeps going, as it always did. */
export function isCasting(connected: boolean, handedOff: boolean): boolean {
  return connected && handedOff;
}

/** Local error recovery (re-sign and reload) runs only while not casting. */
export function shouldRecoverLocally(casting: boolean): boolean {
  return !casting;
}

/** The receiver's start time inside the stream it is handed. An HLS resume
 * encodes from a 10 s bucket, so second 0 of the stream is `timelineOffsetSec`
 * into the source; direct play is absolute. */
export function castStartTime(
  absPositionSec: number,
  mode: "direct" | "hls",
  timelineOffsetSec?: number | null,
): number {
  const base = mode === "hls" && timelineOffsetSec && timelineOffsetSec > 0 ? timelineOffsetSec : 0;
  const rel = Math.floor(absPositionSec - base);
  return rel > 0 ? rel : 0;
}

/** The receiver's place as an absolute source second. Null when the receiver
 * has not reported one. */
export function receiverAbsPosition(
  streamPositionSec: number | null | undefined,
  mode: "direct" | "hls",
  timelineOffsetSec?: number | null,
): number | null {
  if (streamPositionSec == null || !Number.isFinite(streamPositionSec) || streamPositionSec < 0) {
    return null;
  }
  const base = mode === "hls" && timelineOffsetSec && timelineOffsetSec > 0 ? timelineOffsetSec : 0;
  return streamPositionSec + base;
}

/** Where local playback resumes after the cast session ends: the receiver's
 * last absolute position, else the phone's own, kept inside the movie. */
export function localResumePosition(
  receiverAbsSec: number | null | undefined,
  localSec: number,
  durationSec?: number | null,
): number {
  const use =
    receiverAbsSec != null && Number.isFinite(receiverAbsSec) && receiverAbsSec >= 0
      ? receiverAbsSec
      : localSec;
  const pos = Number.isFinite(use) && use > 0 ? use : 0;
  if (durationSec && durationSec > 0 && pos > durationSec) return Math.floor(durationSec);
  return Math.floor(pos);
}

/** The line shown in place of the picture while casting. */
export function castingLabel(deviceName?: string | null): string {
  const name = deviceName?.trim();
  return name ? `Casting to ${name}` : "Casting";
}
