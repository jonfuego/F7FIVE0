/** Crossfade / gapless fade scheduling. Pure (no native imports) so it unit
 * tests in Node. The PlayerProvider polls playback position and uses these to
 * decide when to begin fading the outgoing track and to compute the ramped
 * volume, matching Plexamp's crossfade setting (0 = gapless/off, 1..10 s). */

export const MAX_CROSSFADE_SEC = 10;

/** Clamp a user-entered crossfade value into the supported range. */
export function clampCrossfade(sec: number): number {
  if (!Number.isFinite(sec) || sec <= 0) return 0;
  return Math.min(MAX_CROSSFADE_SEC, Math.round(sec));
}

/** Should the outgoing track begin fading now? True once the remaining time is
 * within the crossfade window (and crossfade is enabled and duration known). */
export function shouldStartFade(positionSec: number, durationSec: number, crossfadeSec: number): boolean {
  if (crossfadeSec <= 0 || durationSec <= 0) return false;
  const remaining = durationSec - positionSec;
  return remaining > 0 && remaining <= crossfadeSec;
}

/** Outgoing-track volume (1 -> 0) during the fade window. Linear ramp. Returns
 * 1 before the window and 0 at/after the end. */
export function fadeOutVolume(positionSec: number, durationSec: number, crossfadeSec: number): number {
  if (crossfadeSec <= 0 || durationSec <= 0) return 1;
  const remaining = durationSec - positionSec;
  if (remaining >= crossfadeSec) return 1;
  if (remaining <= 0) return 0;
  return Math.max(0, Math.min(1, remaining / crossfadeSec));
}

/** Incoming-track volume (0 -> 1), the complement of the fade-out ramp. */
export function fadeInVolume(elapsedInFadeSec: number, crossfadeSec: number): number {
  if (crossfadeSec <= 0) return 1;
  return Math.max(0, Math.min(1, elapsedInFadeSec / crossfadeSec));
}
