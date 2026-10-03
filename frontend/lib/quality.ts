// Web player quality choice. Every HLS level is its own ffmpeg on the
// server, so the player pins one level at start instead of letting hls.js
// ABR wander between them (see components/Player.tsx).

// Per-browser quality choice: "auto" or a level height such as "720".
const QUALITY_KEY = "f7five0:video-quality";
// Start ceiling for software (CPU) transcoding. Matches the server's
// playback.CPU_DEFAULT_HEIGHT.
export const CPU_START_HEIGHT = 720;
const SERVER_HEIGHTS = [1080, 720, 480];

/** Saved pick as a height, or null for none / "auto". */
export function prefHeight(pref: string | null): number | null {
  if (!pref || !/^\d+$/.test(pref)) return null;
  const h = Number(pref);
  return SERVER_HEIGHTS.includes(h) ? h : null;
}

/** Quality choices a CPU-only server can encode for a source this tall. */
export function serverQualityHeights(sourceHeight: number | null | undefined): number[] {
  if (!sourceHeight) return SERVER_HEIGHTS;
  const fit = SERVER_HEIGHTS.filter((h) => h <= sourceHeight);
  return fit.length ? fit : [SERVER_HEIGHTS[SERVER_HEIGHTS.length - 1]];
}

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
