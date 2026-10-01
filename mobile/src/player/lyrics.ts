/** Synced-lyrics helpers. Pure (no native imports) so they unit test in Node.
 * The backend serves lyrics from GET /api/tracks/{id}/lyrics as either synced
 * lines ({time_ms,text}[]) or a plain-text fallback. These functions drive the
 * scroll/highlight in the full-screen lyrics view. */

export interface LyricLine {
  time_ms: number;
  text: string;
}

/** Index of the active lyric line for a playback position (ms). Returns the
 * last line whose time_ms is <= positionMs, or -1 before the first line. Assumes
 * lines are sorted ascending by time_ms (the backend guarantees this); we do a
 * linear scan which is fine for song-length line counts. */
export function activeLyricIndex(lines: LyricLine[] | null | undefined, positionMs: number): number {
  if (!lines || lines.length === 0) return -1;
  if (positionMs < lines[0].time_ms) return -1;
  let idx = -1;
  for (let i = 0; i < lines.length; i += 1) {
    if (lines[i].time_ms <= positionMs) idx = i;
    else break;
  }
  return idx;
}

/** Normalize a lyrics payload's plain text into display lines. Used for the
 * unsynced fallback so both paths render the same line list. */
export function plainTextLines(text: string | null | undefined): string[] {
  if (!text) return [];
  return text.replace(/\r\n/g, "\n").split("\n");
}

/** Whether we have anything renderable at all (synced lines or plain text). */
export function hasLyrics(payload: {
  lines?: LyricLine[] | null;
  text?: string | null;
} | null | undefined): boolean {
  if (!payload) return false;
  if (payload.lines && payload.lines.length > 0) return true;
  return !!(payload.text && payload.text.trim().length > 0);
}
