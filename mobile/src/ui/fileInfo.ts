import type { MediaFile } from "@/api/types";

/** One row of an episode's File info: label and display value. */
export interface FileInfoRow {
  label: string;
  value: string;
}

const DASH = "—";

function channels(n: number | null | undefined): string {
  if (!n) return "";
  if (n >= 8) return " 7.1";
  if (n >= 6) return " 5.1";
  if (n >= 2) return " stereo";
  return " mono";
}

function bytes(n: number | null | undefined): string {
  if (!n || n <= 0) return DASH;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v >= 10 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

/** The seven File info rows for one media file (an episode's own file):
 * codec, bitrate, container, resolution, audio, size, path. Same rows and
 * wording as the web (frontend/lib/file-info.ts). */
export function fileInfoRows(f: MediaFile): FileInfoRow[] {
  return [
    { label: "Codec", value: f.video_codec ? f.video_codec.toUpperCase() : DASH },
    { label: "Bitrate", value: f.bitrate_kbps ? `${(f.bitrate_kbps / 1000).toFixed(1)} Mbps` : DASH },
    { label: "Container", value: f.container ? f.container.toUpperCase() : DASH },
    { label: "Resolution", value: f.width && f.height ? `${f.width}×${f.height}` : DASH },
    { label: "Audio", value: f.audio_codec ? `${f.audio_codec.toUpperCase()}${channels(f.audio_channels)}` : DASH },
    { label: "File size", value: bytes(f.size_bytes) },
    { label: "File path", value: f.path || DASH },
  ];
}
