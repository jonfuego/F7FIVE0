// Small formatters shared across detail pages.
//
// These operate on nullable primitives so callers can pass backend fields
// through without a null-check each time. All return strings suitable for
// dropping straight into JSX.

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}:${pad(m)}:${pad(s)}`;
  }
  return `${m}:${pad(s)}`;
}

// "1h 48m" form, handy for movie runtimes where per-second precision is
// noise. Accepts minutes.
export function formatRuntime(minutes: number | null | undefined): string {
  if (minutes == null || !Number.isFinite(minutes) || minutes <= 0) return "";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let n = bytes / 1024;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  const rounded = n >= 100 ? Math.round(n) : Math.round(n * 10) / 10;
  return `${rounded} ${units[i]}`;
}

export function formatResolution(
  width: number | null | undefined,
  height: number | null | undefined,
): string {
  if (!width || !height) return "";
  // Common presets so tiles read as "1080p" instead of "1920x1080".
  if (height >= 2000) return "4K";
  if (height >= 1000) return "1080p";
  if (height >= 700) return "720p";
  if (height >= 400) return "480p";
  return `${width}x${height}`;
}

// Join a meta row with " · " separators, dropping falsy values so items
// without year or genre still render cleanly. Used by Hero, every detail
// page, and the search results subtitle. The separator is the bullet U+2022
// "•" surrounded by hairlines so meta lines read like a film print.
export function joinMeta(
  parts: Array<string | number | null | undefined>,
): string {
  return parts
    .filter(
      (p): p is string | number =>
        p != null && (typeof p !== "string" || p.trim().length > 0),
    )
    .map((p) => String(p))
    .join(" • ");
}

// Poster placeholders, hero backdrops and the now-playing stage used to take a
// per-title ambient tint through the `--pg` custom property. Design system v3
// is flat: those surfaces are a plain surface-2 tile. Kept so callers that
// still set `--pg` resolve to a token instead of a computed color.
export function colorForTitle(
  _title?: string | null,
  _opts: { lightness?: number; chroma?: number } = {},
): string {
  return "var(--surface-2)";
}

export function hueFromString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i += 1) {
    h = (h * 31 + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h) % 360;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}
