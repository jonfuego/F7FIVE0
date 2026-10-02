// Web player quality choice. Every HLS level is its own ffmpeg on the
// server, so the player pins one level at start instead of letting hls.js
// ABR wander between them (see components/Player.tsx).

// Per-browser quality choice: "auto" or a level height such as "720".
const QUALITY_KEY = "f7five0:video-quality";
// Start ceiling for software (CPU) transcoding.
const CPU_START_HEIGHT = 720;

export function readQualityPref(): string | null {
  try {
    return window.localStorage.getItem(QUALITY_KEY);
  } catch {
    return null;
  }
}

export function writeQualityPref(value: string): void {
  try {
    window.localStorage.setItem(QUALITY_KEY, value);
  } catch {
    // Private mode or blocked storage: the pick just isn't remembered.
  }
}

/** Level index to pin at start, or -1 to leave hls.js ABR in charge. */
export function pickStartLevel(
  heights: number[],
  pref: string | null,
  hardware: boolean,
): number {
  if (heights.length === 0) return -1;
  if (pref === "auto") return -1;
  const wanted = pref && /^\d+$/.test(pref) ? Number(pref) : hardware ? Infinity : CPU_START_HEIGHT;
  let best = -1;
  heights.forEach((h, i) => {
    if (h <= wanted && (best === -1 || h > heights[best])) best = i;
  });
  if (best !== -1) return best;
  // Everything is above the ceiling: take the smallest level.
  let lowest = 0;
  heights.forEach((h, i) => {
    if (h < heights[lowest]) lowest = i;
  });
  return lowest;
}
