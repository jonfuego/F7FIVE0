/** Waveform peak helpers (crit 49). Pure (no native imports) so they unit test
 * in Node. The backend serves peaks 0..100 from GET /api/tracks/{id}/waveform;
 * the scrubber downsamples them to a fixed bar count for cheap rendering. */

/** Downsample a peaks array (0..100) to `buckets` averaged buckets. Values
 * shorter than or equal to `buckets` pass through unchanged. */
export function bucketPeaks(peaks: number[], buckets: number): number[] {
  if (buckets <= 0) return [];
  if (peaks.length === 0) return [];
  if (peaks.length <= buckets) return peaks.slice();
  const out: number[] = new Array(buckets).fill(0);
  const per = peaks.length / buckets;
  for (let b = 0; b < buckets; b += 1) {
    const start = Math.floor(b * per);
    const end = Math.min(peaks.length, Math.floor((b + 1) * per));
    let sum = 0;
    let n = 0;
    for (let i = start; i < end; i += 1) {
      sum += peaks[i];
      n += 1;
    }
    out[b] = n > 0 ? sum / n : 0;
  }
  return out;
}

/** Whether a bar index (of `total` bars) is within the played fraction. */
export function isBarPlayed(index: number, total: number, playedFraction: number): boolean {
  if (total <= 0) return false;
  return (index + 0.5) / total <= playedFraction;
}

/** Map a peak (0..100) to a bar pixel height between min and max. Clamps input. */
export function peakToHeight(peak: number, minPx: number, maxPx: number): number {
  const p = Math.max(0, Math.min(100, Number.isFinite(peak) ? peak : 0));
  return minPx + (p / 100) * (maxPx - minPx);
}
