/** Loudness leveling (EBU R128, Plexamp-style). Pure (no native imports) so it
 * unit tests in Node. The backend runs an `ebur128` job and serves per-track and
 * per-album gain in dB via GET /api/tracks/{id}/loudness. We convert that gain
 * into a track-player volume multiplier (0..1) and apply it with
 * TrackPlayer.setVolume.
 *
 * Design (matches Plexamp / ReplayGain semantics):
 *  - `track_gain_db` is the correction to reach the target loudness (-16 LUFS).
 *    A negative gain means "turn this loud track DOWN"; a positive gain means
 *    "this quiet track could be turned UP".
 *  - track-player volume is a 0..1 multiplier; it can only attenuate, never
 *    amplify past the source. So by default (allowBoost=false) we apply only the
 *    attenuating part of the gain (gain < 0) and leave quiet tracks at full
 *    volume. That prevents clipping and keeps behaviour predictable, which is
 *    the safe default Plexamp uses when it can't boost.
 *  - With allowBoost=true we also apply positive gain, clamped so the multiplier
 *    never exceeds 1 (a 0..1 device volume can't go above unity anyway) — kept
 *    as a hook for a future pre-amp/soft-limiter but bounded for safety now.
 */

/** dB -> linear amplitude ratio (10 ^ (dB/20)). */
export function dbToLinear(db: number): number {
  return Math.pow(10, db / 20);
}

export interface GainToVolumeOptions {
  /** Allow positive gain to raise volume (bounded to 1). Default false:
   * attenuation only, which is the clip-safe behaviour. */
  allowBoost?: boolean;
}

/** Convert a ReplayGain-style gain (dB) into a track-player volume multiplier in
 * [0, 1]. Attenuation-only by default; never returns > 1. */
export function gainToVolumeMultiplier(gainDb: number | null | undefined, opts: GainToVolumeOptions = {}): number {
  if (gainDb == null || !Number.isFinite(gainDb)) return 1;
  // Attenuation-only unless boosting is explicitly allowed.
  const effective = opts.allowBoost ? gainDb : Math.min(0, gainDb);
  const mult = dbToLinear(effective);
  // Clamp into the device volume range. A 0..1 volume can't exceed unity.
  if (!Number.isFinite(mult) || mult < 0) return 0;
  return Math.min(1, mult);
}

/** Pick the gain to apply given the mode. Album mode uses album_gain_db so all
 * tracks on an album share one correction (preserves intra-album dynamics);
 * track mode uses per-track gain. Falls back gracefully to whichever is present. */
export function pickGain(
  loudness: { track_gain_db?: number | null; album_gain_db?: number | null } | null | undefined,
  albumMode: boolean,
): number | null {
  if (!loudness) return null;
  if (albumMode) {
    return loudness.album_gain_db ?? loudness.track_gain_db ?? null;
  }
  return loudness.track_gain_db ?? loudness.album_gain_db ?? null;
}

/** Resolve the final volume multiplier for a track from its loudness data,
 * whether leveling is enabled, album mode, and boost preference. When leveling
 * is off it always returns 1 (full volume). */
export function resolveVolume(
  loudness: { track_gain_db?: number | null; album_gain_db?: number | null } | null | undefined,
  opts: { enabled: boolean; albumMode: boolean; allowBoost: boolean },
): number {
  if (!opts.enabled) return 1;
  const gain = pickGain(loudness, opts.albumMode);
  return gainToVolumeMultiplier(gain, { allowBoost: opts.allowBoost });
}
