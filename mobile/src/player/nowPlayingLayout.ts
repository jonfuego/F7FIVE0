/** Now Playing sizing. Pure, so it unit-tests with no React Native.
 *
 * The artwork fills the width inside the screen padding, but never so tall that
 * the title, scrubber, times and transport row fall off the bottom (the screen
 * does not scroll). The transport controls scale with the width so they are easy
 * to hit at a glance. Music and podcasts share these values.
 */

/** Horizontal and vertical padding of the screen (`spacing.lg`). */
export const SCREEN_PADDING = 16;

/** Height of everything on the screen except the artwork and the play button,
 * in dp: screen padding top and bottom (32), top bar (44), gap above the art
 * (24), gap and title, artist and chapter lines (104), scrubber (40), times
 * (20), the smallest gap above the transport row (24), and 72 held back for the
 * status and navigation bars the safe area takes out of the window. */
export const FIXED_ROWS_HEIGHT = 360;

const MIN_ARTWORK = 120;

export interface NowPlayingLayout {
  artwork: number;
  playDiameter: number;
  playIcon: number;
  /** Previous and next on music, back and forward 15 / 30 s on a podcast. */
  skipIcon: number;
  /** Shuffle and repeat. */
  secondaryIcon: number;
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

export function nowPlayingLayout(width: number, height: number): NowPlayingLayout {
  const playDiameter = clamp(Math.round(width * 0.2), 64, 96);
  const byWidth = Math.floor(width - 2 * SCREEN_PADDING);
  const byHeight = Math.floor(height - FIXED_ROWS_HEIGHT - playDiameter);
  return {
    artwork: Math.max(MIN_ARTWORK, Math.min(byWidth, byHeight)),
    playDiameter,
    playIcon: Math.round(playDiameter * 0.45),
    skipIcon: clamp(Math.round(width * 0.11), 36, 52),
    secondaryIcon: clamp(Math.round(width * 0.07), 24, 32),
  };
}
