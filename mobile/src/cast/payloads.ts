/** Pure Chromecast payload builders.
 *
 * These turn a signed stream (from /api/stream/start with purpose:"cast") or a
 * music queue into the plain-object load request react-native-google-cast's
 * RemoteMediaClient.loadMedia accepts. They import NO native module so the whole
 * module unit-tests in Node, and the receiver-facing shape (content types, start
 * position, queue order, artwork) is asserted directly.
 *
 * The receiver fetches every URL itself, so every URL handed in here must
 * already be absolute, signed, and reachable from the Chromecast.
 */

export const HLS_CONTENT_TYPE = "application/vnd.apple.mpegurl";
export const MP4_CONTENT_TYPE = "video/mp4";

export interface CastImage {
  url: string;
}

export interface CastMetadata {
  type: "generic" | "movie" | "musicTrack";
  title?: string;
  subtitle?: string;
  artist?: string;
  images?: CastImage[];
}

export interface CastMediaInfo {
  contentUrl: string;
  contentType: string;
  // The receiver treats HLS VOD and MP4 direct-play as buffered streams.
  streamType: "buffered";
  metadata: CastMetadata;
}

export interface CastQueueItem {
  mediaInfo: CastMediaInfo;
}

export interface CastQueueData {
  items: CastQueueItem[];
  startIndex: number;
  startTime?: number;
  name?: string;
}

export interface CastLoadRequest {
  autoplay: boolean;
  startTime?: number;
  mediaInfo?: CastMediaInfo;
  queueData?: CastQueueData;
}

/** Content type for a video load: HLS master playlist vs direct MP4. */
export function videoContentType(mode: "direct" | "hls"): string {
  return mode === "hls" ? HLS_CONTENT_TYPE : MP4_CONTENT_TYPE;
}

/** Best-effort audio content type from a container/codec hint. Falls back to
 * audio/mpeg, which the Default Media Receiver always accepts. */
export function audioContentType(hint: { container?: string | null; codec?: string | null }): string {
  const c = `${hint.container ?? ""} ${hint.codec ?? ""}`.toLowerCase();
  if (c.includes("flac")) return "audio/flac";
  if (c.includes("mp3") || c.includes("mpeg")) return "audio/mpeg";
  if (c.includes("m4a") || c.includes("aac") || c.includes("mp4") || c.includes("alac")) {
    return "audio/mp4";
  }
  if (c.includes("opus") || c.includes("ogg") || c.includes("vorbis")) return "audio/ogg";
  if (c.includes("wav")) return "audio/wav";
  return "audio/mpeg";
}

function clampIndex(index: number, length: number): number {
  if (!Number.isFinite(index) || index < 0) return 0;
  if (length > 0 && index > length - 1) return length - 1;
  return Math.floor(index);
}

export interface VideoCastInput {
  url: string;
  mode: "direct" | "hls";
  title?: string | null;
  subtitle?: string | null;
  artUrl?: string | null;
  startPositionSec?: number;
  isMovie?: boolean;
}

/** Build a single-item video load request for the receiver. */
export function buildVideoLoadRequest(input: VideoCastInput): CastLoadRequest {
  const images = input.artUrl ? [{ url: input.artUrl }] : undefined;
  const req: CastLoadRequest = {
    autoplay: true,
    mediaInfo: {
      contentUrl: input.url,
      contentType: videoContentType(input.mode),
      streamType: "buffered",
      metadata: {
        type: input.isMovie ? "movie" : "generic",
        title: input.title ?? undefined,
        subtitle: input.subtitle ?? undefined,
        images,
      },
    },
  };
  if (input.startPositionSec && input.startPositionSec > 0) {
    req.startTime = Math.floor(input.startPositionSec);
  }
  return req;
}

export interface MusicTrackInput {
  url: string;
  title?: string | null;
  artist?: string | null;
  album?: string | null;
  artUrl?: string | null;
  container?: string | null;
  codec?: string | null;
}

export interface MusicQueueInput {
  tracks: MusicTrackInput[];
  startIndex: number;
  startPositionSec?: number;
}

/** Build a cast queue load request from the current music queue. Items keep
 * their order; startIndex selects the currently-playing track and startTime
 * carries its position over. */
export function buildMusicQueueLoadRequest(input: MusicQueueInput): CastLoadRequest {
  const items: CastQueueItem[] = input.tracks.map((t) => ({
    mediaInfo: {
      contentUrl: t.url,
      contentType: audioContentType({ container: t.container, codec: t.codec }),
      streamType: "buffered",
      metadata: {
        type: "musicTrack",
        title: t.title ?? undefined,
        subtitle: t.artist ?? undefined,
        artist: t.artist ?? undefined,
        images: t.artUrl ? [{ url: t.artUrl }] : undefined,
      },
    },
  }));
  const startIndex = clampIndex(input.startIndex, items.length);
  const req: CastLoadRequest = { autoplay: true, queueData: { items, startIndex } };
  if (input.startPositionSec && input.startPositionSec > 0) {
    const pos = Math.floor(input.startPositionSec);
    req.startTime = pos;
    req.queueData!.startTime = pos;
  }
  return req;
}
