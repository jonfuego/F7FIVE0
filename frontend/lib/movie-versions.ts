// Movie versions: the files of one movie (the same film in two folders of a
// library is one movie with two files). The movie page shows a Version picker
// when there are two or more ready files and plays the picked one; without a
// pick it plays `bestVersion`, the same order as the server's
// services/version_pick.py (admin-pinned first, then height, bitrate, codec).
// Pure so node:test can cover it (movie-versions.test.ts).

export type VersionFile = {
  id: string;
  path: string;
  scan_state: string;
  height: number | null;
  bitrate_kbps: number | null;
  video_codec: string | null;
  is_preferred?: boolean | null;
};

function codecScore(c: string | null | undefined): number {
  if (!c) return 0;
  const n = c.toLowerCase().replace(/[-.]/g, "");
  if (n === "hevc" || n === "h265") return 2;
  if (n === "avc" || n === "h264") return 1;
  return 0;
}

/** Ready files only: a missing file can't be played. */
export function readyVersions<T extends VersionFile>(files: T[] | null | undefined): T[] {
  return (files ?? []).filter((f) => f.scan_state === "ready");
}

/** The version to play when the user has not picked one, or null. */
export function bestVersion<T extends VersionFile>(files: T[]): T | null {
  if (!files.length) return null;
  return [...files].sort((a, b) => {
    const pa = Boolean(a.is_preferred);
    const pb = Boolean(b.is_preferred);
    if (pa !== pb) return pa ? -1 : 1;
    if ((b.height ?? 0) !== (a.height ?? 0)) return (b.height ?? 0) - (a.height ?? 0);
    if ((b.bitrate_kbps ?? 0) !== (a.bitrate_kbps ?? 0)) return (b.bitrate_kbps ?? 0) - (a.bitrate_kbps ?? 0);
    return codecScore(b.video_codec) - codecScore(a.video_codec);
  })[0];
}

/** The file to play: the picked one when it is still ready, else the best. */
export function chosenVersion<T extends VersionFile>(files: T[], pickedId: string | null): T | null {
  return files.find((f) => f.id === pickedId) ?? bestVersion(files);
}

function baseLabel(f: VersionFile): string {
  const res = f.height ? `${f.height}p` : null;
  const codec = f.video_codec ? f.video_codec.toUpperCase() : null;
  if (res && codec) return `${res} ${codec}`;
  return res ?? codec ?? "Unknown";
}

function fileName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

/** One label per file, e.g. "1080p H264" or "720p H264 (preferred)". Two
 *  files that would read the same also show their file name. */
export function versionLabels(files: VersionFile[]): Map<string, string> {
  const counts = new Map<string, number>();
  for (const f of files) counts.set(baseLabel(f), (counts.get(baseLabel(f)) ?? 0) + 1);
  const out = new Map<string, string>();
  for (const f of files) {
    let label = baseLabel(f);
    if ((counts.get(label) ?? 0) > 1) label = `${label} - ${fileName(f.path)}`;
    if (f.is_preferred) label = `${label} (preferred)`;
    out.set(f.id, label);
  }
  return out;
}
