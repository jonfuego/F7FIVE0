/** What the phone shows as "now playing", built from one track only.
 *
 * Every Track handed to react-native-track-player carries its own meta as
 * custom fields (mediaFileId, trackId, albumId, artistId, artPath, kind,
 * episodeId, podcastId, durationSec). The track that useActiveTrack() returns
 * is the track that is playing, so title, art, album id and the highlighted row
 * can never disagree. Never look these up by queue index: the index changes in
 * an async event and used to lag one track behind.
 *
 * Pure (no native imports) so the unit tests run in Node. */

/** Per-track meta kept for the queue list and the server queue sync. */
export interface QueueMeta {
  mediaFileId: string;
  trackId?: string | null;
  title: string;
  artist?: string | null;
  album?: string | null;
  albumId?: string | null;
  artistId?: string | null;
  artPath?: string | null;
  durationSec?: number | null;
  /** A podcast episode: mediaFileId holds the episode id too. */
  kind?: "podcast";
  episodeId?: string;
  podcastId?: string | null;
}

export interface NowPlaying {
  title: string;
  artist?: string;
  artPath?: string | null;
  mediaFileId?: string;
  trackId?: string | null;
  albumId?: string | null;
  artistId?: string | null;
  kind?: "podcast";
  episodeId?: string;
  podcastId?: string | null;
}

/** The part of a react-native-track-player Track this module reads. */
export interface TrackLike {
  id?: string;
  title?: string;
  artist?: string;
  album?: string;
  artwork?: unknown;
  duration?: number;
  [key: string]: unknown;
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

function num(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

/** The queue meta a track carries, or null when it has no media file id. */
export function metaFromTrack(track: TrackLike | null | undefined): QueueMeta | null {
  if (!track) return null;
  const mediaFileId = str(track.mediaFileId);
  if (!mediaFileId) return null;
  return {
    mediaFileId,
    trackId: str(track.trackId) ?? null,
    title: track.title ?? "Unknown",
    artist: track.artist ?? null,
    album: track.album ?? null,
    albumId: str(track.albumId) ?? null,
    artistId: str(track.artistId) ?? null,
    artPath: str(track.artPath) ?? null,
    durationSec: num(track.durationSec) ?? num(track.duration) ?? null,
    kind: track.kind === "podcast" ? "podcast" : undefined,
    episodeId: str(track.episodeId),
    podcastId: str(track.podcastId) ?? null,
  };
}

export function nowPlayingFromTrack(track: TrackLike | null | undefined): NowPlaying | null {
  if (!track) return null;
  return {
    title: track.title ?? "Unknown",
    artist: track.artist,
    artPath: str(track.artPath) ?? (typeof track.artwork === "string" ? track.artwork : null),
    mediaFileId: str(track.mediaFileId),
    trackId: str(track.trackId) ?? null,
    albumId: str(track.albumId) ?? null,
    artistId: str(track.artistId) ?? null,
    kind: track.kind === "podcast" ? "podcast" : undefined,
    episodeId: str(track.episodeId),
    podcastId: str(track.podcastId) ?? null,
  };
}
