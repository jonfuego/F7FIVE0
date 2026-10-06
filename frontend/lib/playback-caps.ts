// What this browser plays as-is, reported to /api/stream/start as
// `client_caps` so the server can direct-play a file instead of transcoding
// it. Chrome, for one, plays H.264 + AAC in Matroska; without this report an
// MKV was always re-encoded (and on a CPU-only server scaled to 720p).
//
// Pure: takes a canPlayType-style function so node:test can drive it.

export type ClientCaps = {
  containers: string[];
  video_codecs: string[];
  audio_codecs: string[];
};

type CanPlay = (type: string) => string;

// One probe per name. A container counts only with a codec string that names
// H.264 + AAC, so "maybe" for a bare MIME type never widens the list.
const CONTAINER_PROBES: [string, string][] = [
  ["mp4", 'video/mp4; codecs="avc1.640028, mp4a.40.2"'],
  ["mkv", 'video/x-matroska; codecs="avc1.640028, mp4a.40.2"'],
  ["webm", 'video/webm; codecs="vp9, opus"'],
];
const VIDEO_PROBES: [string, string][] = [
  ["h264", 'video/mp4; codecs="avc1.640028"'],
  ["hevc", 'video/mp4; codecs="hvc1.1.6.L120.90"'],
  ["vp9", 'video/webm; codecs="vp9"'],
  ["av1", 'video/mp4; codecs="av01.0.08M.08"'],
];
const AUDIO_PROBES: [string, string][] = [
  ["aac", 'audio/mp4; codecs="mp4a.40.2"'],
  ["mp3", "audio/mpeg"],
  ["opus", 'audio/webm; codecs="opus"'],
  ["flac", "audio/flac"],
  ["ac3", 'audio/mp4; codecs="ac-3"'],
  ["eac3", 'audio/mp4; codecs="ec-3"'],
];

function supported(canPlay: CanPlay, probes: [string, string][], codecMustBeProbably: boolean): string[] {
  const out: string[] = [];
  for (const [name, type] of probes) {
    let answer = "";
    try {
      answer = canPlay(type);
    } catch {
      answer = "";
    }
    // "probably" is a yes. "maybe" only counts for a bare MIME type with no
    // codecs parameter (audio/mpeg, audio/flac), where browsers never say more.
    if (answer === "probably" || (!codecMustBeProbably && answer === "maybe" && !type.includes("codecs="))) {
      out.push(name);
    }
  }
  return out;
}

export function detectClientCaps(canPlay: CanPlay): ClientCaps {
  return {
    containers: supported(canPlay, CONTAINER_PROBES, true),
    video_codecs: supported(canPlay, VIDEO_PROBES, true),
    audio_codecs: supported(canPlay, AUDIO_PROBES, false),
  };
}

let cached: ClientCaps | null = null;

/** The caps of this browser, probed once per page load. Null outside a browser. */
export function browserClientCaps(): ClientCaps | null {
  if (cached) return cached;
  if (typeof document === "undefined") return null;
  const v = document.createElement("video");
  cached = detectClientCaps((t) => v.canPlayType(t));
  return cached;
}
