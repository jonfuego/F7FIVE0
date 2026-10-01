// Renders a single media file row: container, resolution, codecs, size, and
// a scan-state badge for anything not ready. Detail pages list one of these
// per file (most movies have a single file; some may have multiple quality
// copies and users pick which one to play).

import type { MediaFile } from "@/lib/types";
import { formatBytes, formatResolution } from "@/lib/format";

const READY_STATES = new Set(["ready"]);

export function MediaFileInfo({ file }: { file: MediaFile }) {
  const bits: string[] = [];
  const resolution = formatResolution(file.width, file.height);
  if (resolution) bits.push(resolution);
  if (file.container) bits.push(file.container.toUpperCase());
  if (file.video_codec) bits.push(file.video_codec.toUpperCase());
  if (file.audio_codec) {
    const chans = file.audio_channels ? ` ${channelLabel(file.audio_channels)}` : "";
    bits.push(`${file.audio_codec.toUpperCase()}${chans}`);
  }
  const size = formatBytes(file.size_bytes);
  if (size) bits.push(size);

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-neutral-400">
      {bits.map((b, i) => (
        <span key={i} className="rounded bg-neutral-900 px-2 py-0.5">
          {b}
        </span>
      ))}
      {!READY_STATES.has(file.scan_state) ? (
        <span className="rounded bg-red-950/60 px-2 py-0.5 text-red-300">
          {file.scan_state}
        </span>
      ) : null}
    </div>
  );
}

function channelLabel(channels: number): string {
  if (channels >= 8) return "7.1";
  if (channels >= 6) return "5.1";
  if (channels >= 2) return "stereo";
  return "mono";
}
