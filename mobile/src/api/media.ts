import { getApiBase } from "@/state/config";
import type { ApiClient } from "./client";
import { playWithUrlRecovery, SignedStream } from "./streamUrl";
import type { MediaMarker } from "@/video/transport";
import type {
  Lyrics,
  NextEpisode,
  Loudness,
  Me,
  MediaStreams,
  QueueDTO,
  QueueItemDTO,
  RequestSearchResult,
  StreamStart,
  StreamQuality,
  SubtitleChoice,
  Waveform,
} from "./types";
import type { AutoPlaylistItem } from "./types";

/** Resolve an art path to a loadable URI. Remote (*arr/TMDB) URLs pass through;
 * server-relative art paths are prefixed with the API base. Returns null when
 * there's no art so the UI renders a placeholder instead of a blank/broken box. */
export function resolveArtUri(path?: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${getApiBase()}${path.startsWith("/") ? "" : "/"}${path}`;
}

/** Optional video-picker choices for stream/start (crit 41). */
export interface StreamOptions {
  audioTrackIndex?: number;
  subtitle?: SubtitleChoice;
  quality?: StreamQuality;
}

/** Ask the API for a fresh signed stream URL for a media file. Optional video
 * picker choices (audio track / subtitle / quality) are forwarded and echoed. */
export async function startStream(
  api: ApiClient,
  fileId: string,
  resumeSec?: number,
  opts?: StreamOptions,
): Promise<StreamStart> {
  return api.json<StreamStart>("/api/stream/start", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      file_id: fileId,
      resume_sec: resumeSec,
      audio_track_index: opts?.audioTrackIndex,
      subtitle: opts?.subtitle,
      quality: opts?.quality,
    }),
  });
}

/** GET the EBU R128 loudness (per-track + album gain) for a track (crit 46). */
export async function fetchLoudness(api: ApiClient, trackId: string): Promise<Loudness> {
  return api.json<Loudness>(`/api/tracks/${encodeURIComponent(trackId)}/loudness`);
}

/** GET precomputed waveform peaks for a track (crit 49). */
export async function fetchWaveform(api: ApiClient, trackId: string): Promise<Waveform> {
  return api.json<Waveform>(`/api/tracks/${encodeURIComponent(trackId)}/waveform`);
}

/** GET lyrics (synced or plain) for a track (crit 47). Same-host only. */
export async function fetchLyrics(api: ApiClient, trackId: string): Promise<Lyrics> {
  return api.json<Lyrics>(`/api/tracks/${encodeURIComponent(trackId)}/lyrics`);
}

/** GET the subtitle + audio stream list for a media file (crit 41). */
export async function fetchMediaStreams(api: ApiClient, mediaFileId: string): Promise<MediaStreams> {
  return api.json<MediaStreams>(`/api/media-files/${encodeURIComponent(mediaFileId)}/streams`);
}

/** Build the absolute signed .vtt URL for a subtitle stream (no bearer; the
 * URL is already signed with uid/exp/sig). Used as a react-native-video
 * textTrack uri. The path is returned by the streams endpoint indirectly; we
 * construct it from the media-file id + index against the current server. Callers pass the
 * full signed query string (uid/exp/sig) the backend hands them. */
export function subtitleVttUrl(mediaFileId: string, index: number, signedQuery: string): string {
  const q = signedQuery.startsWith("?") ? signedQuery : `?${signedQuery}`;
  return `${getApiBase()}/api/media-files/${encodeURIComponent(mediaFileId)}/subtitles/${index}.vtt${q}`;
}

/** GET similar tracks for a track (crit 48, sonic radio input). */
export async function fetchSimilar(
  api: ApiClient,
  trackId: string,
  limit = 50,
): Promise<AutoPlaylistItem[]> {
  const res = await api.json<{ items: AutoPlaylistItem[] }>(
    `/api/tracks/${encodeURIComponent(trackId)}/similar?limit=${limit}`,
  );
  return res.items;
}

/** Build the download URL for a media file (crit 42/43). The backend serves a
 * signed URL (uid/exp/sig, no bearer) or 409 {reason:"not_available_offline"}.
 * The client can't compute the signature, so it sends the bearer header via
 * `headers` (the download manager passes these to expo-file-system). ASSUMPTION
 * to reconcile with backend: the download endpoint accepts a bearer, or a signed
 * URL is surfaced elsewhere; documented in docs/library-compat.md. */
export function downloadUrl(mediaFileId: string, quality?: StreamQuality): string {
  const q = quality ? `?quality=${quality}` : "";
  return `${getApiBase()}/api/media-files/${encodeURIComponent(mediaFileId)}/download${q}`;
}

/** Auth headers for the download request (bearer). Empty when signed out. */
export function downloadHeaders(api: ApiClient): Record<string, string> {
  return api.authHeaders();
}

/** GET a full track-radio auto-playlist seeded by a track (crit 48). */
export async function fetchTrackRadio(
  api: ApiClient,
  trackId: string,
  limit = 100,
): Promise<AutoPlaylistItem[]> {
  const res = await api.json<{ items: AutoPlaylistItem[] }>(
    `/api/auto-playlist/track-radio/${encodeURIComponent(trackId)}?limit=${limit}`,
  );
  return res.items;
}

/** Fetch a signed URL right before playback, with one automatic re-sign+retry
 * on a load error (spec Q2, Option A + recovery). */
export async function playFileWithRecovery<T>(
  api: ApiClient,
  fileId: string,
  tryPlay: (stream: SignedStream, meta: StreamStart) => Promise<T>,
  resumeSec?: number,
): Promise<T> {
  let lastMeta: StreamStart | null = null;
  return playWithUrlRecovery(
    async () => {
      const meta = await startStream(api, fileId, resumeSec);
      lastMeta = meta;
      return { url: meta.url, mode: meta.mode };
    },
    (stream) => tryPlay(stream, lastMeta as StreamStart),
  );
}

/** Report playback progress. Fire-and-forget from the sync loop. */
export async function reportProgress(
  api: ApiClient,
  mediaFileId: string,
  positionSec: number,
  durationSec?: number,
): Promise<void> {
  await api.request(`/api/progress/${mediaFileId}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      position_sec: Math.max(0, Math.floor(positionSec)),
      // Backend requires an int >= 1 when present.
      duration_sec: durationSec && durationSec >= 1 ? Math.floor(durationSec) : undefined,
    }),
  });
}

/** Mark a movie/episode watched (stamps completed_at server-side). */
export async function markWatched(api: ApiClient, mediaFileId: string): Promise<void> {
  await api.request(`/api/progress/${mediaFileId}/mark-watched`, { method: "POST" });
}

/** Mark a movie/episode unwatched (clears the progress row). */
export async function markUnwatched(api: ApiClient, mediaFileId: string): Promise<void> {
  await api.request(`/api/progress/${mediaFileId}`, { method: "DELETE" });
}

/** Record one audio play (Recently Played / Most Played inputs), the way the
 * web dock POSTs to /api/track-plays. Best-effort. */
export async function postTrackPlay(
  api: ApiClient,
  trackId: string,
  msPlayed: number,
  completed: boolean,
): Promise<void> {
  try {
    await api.request("/api/track-plays", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ track_id: trackId, ms_played: Math.max(0, Math.floor(msPlayed)), completed }),
    });
  } catch {
    // Non-critical telemetry; never surface.
  }
}

/** Hydrate the cross-device queue from the server (empty default if none). */
export async function fetchServerQueue(api: ApiClient): Promise<QueueDTO> {
  return api.json<QueueDTO>("/api/queue");
}

/** Persist the current queue so it survives an app restart and syncs across
 * devices (PUT /api/queue). */
export async function saveServerQueue(
  api: ApiClient,
  items: QueueItemDTO[],
  currentIndex: number | null,
  repeatMode: "off" | "all" | "one",
  shuffle: boolean,
  writerId?: string,
): Promise<void> {
  await api.request("/api/queue", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      items,
      current_index: items.length > 0 ? currentIndex : null,
      repeat_mode: repeatMode,
      shuffle,
      last_writer_id: writerId,
    }),
  });
}

/** Clear the server queue row (DELETE /api/queue). */
export async function clearServerQueue(api: ApiClient): Promise<void> {
  await api.request("/api/queue", { method: "DELETE" });
}

/** Update the signed-in user's display name (PATCH /api/auth/me). */
export async function updateProfile(api: ApiClient, displayName: string): Promise<Me> {
  return api.json<Me>("/api/auth/me", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
}

/** Change the signed-in user's password (POST /api/auth/me/password). */
export async function changePassword(
  api: ApiClient,
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await api.request("/api/auth/me/password", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

/** Search the acquisition catalogue (Radarr/Sonarr) for a title to request. */
export async function searchRequests(
  api: ApiClient,
  kind: "movie" | "series",
  q: string,
): Promise<RequestSearchResult[]> {
  return api.json<RequestSearchResult[]>(
    `/api/requests/search?kind=${kind}&q=${encodeURIComponent(q)}`,
  );
}

/** File a request for a catalogue hit (POST /api/requests). */
export async function createRequest(
  api: ApiClient,
  kind: string,
  externalId: string,
): Promise<void> {
  await api.request("/api/requests", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ kind, external_id: externalId }),
  });
}

/** Post one client error line (Phase 4 crash reporting). Best-effort. */
export async function reportClientError(
  api: ApiClient,
  payload: {
    message: string;
    stack?: string;
    platform?: string;
    client_version?: string;
    fatal?: boolean;
    context?: string;
  },
): Promise<void> {
  try {
    await api.request("/api/client/errors", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    // Never let error reporting throw into the UI.
  }
}

/** GET intro/credits markers for a media file (crit 8 / 37). */
export async function fetchMarkers(api: ApiClient, mediaFileId: string): Promise<MediaMarker[]> {
  return api.json<MediaMarker[]>(`/api/markers/${encodeURIComponent(mediaFileId)}`);
}

/** GET the episode after this one, or null (Plex "Up Next", crit 37). */
export async function fetchNextEpisode(api: ApiClient, mediaFileId: string): Promise<NextEpisode | null> {
  return api.json<NextEpisode | null>(`/api/media-files/${encodeURIComponent(mediaFileId)}/next-episode`);
}

/** Mint a signed, bearer-free download URL for a media file (crit 42). Throws
 * an ApiError with status 409 for video that can't be offered offline. */
export async function fetchDownloadUrl(
  api: ApiClient,
  mediaFileId: string,
  quality: StreamQuality = "original",
): Promise<{ url: string; container?: string | null; size_bytes?: number | null; kind?: string }> {
  return api.json(`/api/media-files/${encodeURIComponent(mediaFileId)}/download-url?quality=${quality}`);
}
