/** Response shapes from the F7FIVE0 API (subset the app uses). Mirrors
 * backend/app/api/schemas.py. */

export interface MediaFile {
  id: string;
  container?: string | null;
  duration_sec?: number | null;
  video_codec?: string | null;
  audio_codec?: string | null;
}

export interface SongRow {
  id: string;
  title: string;
  track_number?: number | null;
  disc_number?: number | null;
  duration_sec?: number | null;
  album_id: string;
  album_title: string;
  cover_path?: string | null;
  artist_id: string;
  artist_name: string;
  media_files: MediaFile[];
}

export interface Album {
  id: string;
  artist_id: string;
  artist_name?: string | null;
  title: string;
  release_date?: string | null;
  cover_path?: string | null;
  album_type?: string | null;
  /** When the album entered the library ("Date added" sort). */
  created_at?: string | null;
}

export interface Track {
  id: string;
  title: string;
  track_number?: number | null;
  disc_number?: number | null;
  duration_sec?: number | null;
  media_files: MediaFile[];
}

export interface AlbumDetail extends Album {
  tracks: Track[];
}

export interface Artist {
  id: string;
  name: string;
  image_path?: string | null;
  album_count: number;
}

export interface ArtistDetail extends Artist {
  albums: Album[];
  bio_text?: string | null;
}

export interface Movie {
  id: string;
  title: string;
  year?: number | null;
  overview?: string | null;
  poster_path?: string | null;
  backdrop_path?: string | null;
  runtime_min?: number | null;
  tagline?: string | null;
  genres?: string[] | null;
  tmdb_rating?: number | null;
  /** When the movie entered the library ("Date added" sort). */
  created_at?: string | null;
  // The API returns cast/crew as objects ({name, character, ...}); older/other
  // shapes may send plain strings, so accept both and normalize in the UI.
  cast?: (CastMember | string)[] | null;
  directors?: (CastMember | string)[] | null;
  media_files?: MediaFile[];
}

export interface CastMember {
  name: string;
  character?: string | null;
  order?: number | null;
  profile_path?: string | null;
}

/** Normalize a cast/crew entry (object or string) to its display name. */
export function personName(p: CastMember | string): string {
  return typeof p === "string" ? p : p?.name ?? "";
}

/** One item from GET /api/recent (Recent Arrivals rail). */
export interface RecentItem {
  kind: string;
  id: string;
  title: string;
  subtitle?: string | null;
  year?: number | null;
  poster_path?: string | null;
  media_file_id?: string | null;
}

/** GET /api/progress/{media_file_id}; null when nothing is recorded. */
export interface Progress {
  media_file_id: string;
  position_sec: number;
  duration_sec?: number | null;
  completed_at?: string | null;
}

export interface Series {
  id: string;
  title: string;
  year?: number | null;
  overview?: string | null;
  poster_path?: string | null;
  /** When the show entered the library ("Date added" sort). */
  created_at?: string | null;
}

export interface MusicVideo {
  id: string;
  release_id?: string | null;
  title: string;
  year?: number | null;
  track_number?: number | null;
  thumb_path?: string | null;
  media_file_id?: string | null;
  duration_sec?: number | null;
}

export interface MusicVideoArtist {
  id: string;
  name: string;
  image_path?: string | null;
  video_count: number;
}

export interface Episode {
  id: string;
  season_number: number;
  episode_number: number;
  title?: string | null;
  overview?: string | null;
  media_files: MediaFile[];
}

/** GET /api/series/{id} */
export interface SeriesDetail extends Series {
  episodes: Episode[];
}

export interface MusicVideoRelease {
  id: string;
  artist_id: string;
  title: string;
  release_year?: number | null;
  cover_path?: string | null;
  video_count: number;
}

/** GET /api/music-videos/artists/{id} */
export interface MusicVideoArtistDetail extends MusicVideoArtist {
  releases: MusicVideoRelease[];
}

/** GET /api/music-videos/releases/{id} */
export interface MusicVideoReleaseDetail extends MusicVideoRelease {
  artist_name: string;
  videos: MusicVideo[];
}

export interface Mix {
  id: string;
  title: string;
  subtitle?: string | null;
  cover_path?: string | null;
}

/** One item from GET /api/auto-playlist/<kind> (backend QueueItem shape). */
export interface AutoPlaylistItem {
  media_file_id: string;
  track_id: string;
  title: string;
  artist_id: string;
  artist_name: string;
  album_id: string;
  album_title: string;
  cover_path?: string | null;
  duration_sec?: number | null;
}

export interface ContinueWatchingItem {
  kind: string;
  id: string;
  media_file_id: string;
  title: string;
  subtitle?: string | null;
  year?: number | null;
  poster_path?: string | null;
  position_sec: number;
  duration_sec?: number | null;
}

export interface SearchResult {
  kind: string;
  id: string;
  title: string;
  subtitle?: string | null;
  year?: number | null;
  poster_path?: string | null;
}

export interface DeviceSession {
  id: string;
  device_label?: string | null;
  client_type: string;
  platform?: string | null;
  client_version?: string | null;
  created_at: string;
  last_seen_at?: string | null;
  expires_at: string;
  current: boolean;
}

export interface MediaRequest {
  id: string;
  kind: string;
  title: string;
  year?: number | null;
  poster_url?: string | null;
  status: string;
  created_at: string;
}

/** One catalogue hit from GET /api/requests/search (Radarr/Sonarr lookup). */
export interface RequestSearchResult {
  kind: string;
  external_id: string;
  title: string;
  year?: number | null;
  poster_url?: string | null;
}

/** GET /api/auth/me */
export interface Me {
  id: string;
  username: string;
  display_name?: string | null;
  role: string;
}

export interface StreamStart {
  media_file_id: string;
  mode: "direct" | "hls";
  url: string;
  expires_at: string;
  title?: string | null;
  duration_sec?: number | null;
  cover_path?: string | null;
  /** Short-lived HMAC-signed absolute art URL for the lock screen (serves with
   * no bearer). Present when the backend can sign the cover. */
  art_url?: string | null;
  artist_name?: string | null;
  album_title?: string | null;
  /** Echoed video picker choices (crit 41). */
  audio_track_index?: number | null;
  subtitle?: number | "off" | "burn" | null;
  quality?: StreamQuality | null;
  /** Effective track-options token the server signed into the URL
   * (e.g. "a2-q720"); null when default tracks at source quality. */
  track_opts?: string | null;
}

/** One entry in the cross-device queue (PUT/GET /api/queue). Extra UI fields
 * are allowed by the backend; media_file_id + title are required. */
export interface QueueItemDTO {
  media_file_id: string;
  title: string;
  track_id?: string | null;
  artist_name?: string | null;
  album_title?: string | null;
  cover_path?: string | null;
  duration_sec?: number | null;
}

/** GET /api/queue response. */
export interface QueueDTO {
  items: QueueItemDTO[];
  current_index: number | null;
  repeat_mode: "off" | "all" | "one";
  shuffle: boolean;
  last_writer_id?: string | null;
  updated_at: string;
}

export interface MinVersions {
  android: string;
  ios: string;
  android_tv: string;
  tvos: string;
}

/** GET /api/tracks/{track_id}/loudness (EBU R128 per-track gain). */
export interface Loudness {
  integrated_lufs: number;
  track_gain_db: number;
  album_gain_db: number;
}

/** GET /api/tracks/{track_id}/waveform (precomputed peaks 0..100). */
export interface Waveform {
  peaks: number[];
  version: number;
}

/** One synced lyric line. */
export interface LyricLine {
  time_ms: number;
  text: string;
}

/** GET /api/tracks/{track_id}/lyrics. `synced` true => `lines` present; else
 * `text` is the plain fallback. Never a third-party host. */
export interface Lyrics {
  synced: boolean;
  lines: LyricLine[] | null;
  text: string | null;
  source?: string | null;
}

/** One selectable subtitle stream from GET /api/media-files/{id}/streams. */
export interface SubtitleStream {
  index: number;
  codec: string;
  language?: string | null;
  title?: string | null;
  forced?: boolean;
  default?: boolean;
  /** Optional pre-signed absolute .vtt URL (uid/exp/sig). When present the
   * client loads it directly as a react-native-video textTrack; when absent the
   * client builds one from the media-file id + index (needs the backend to
   * accept the constructed signed path). ASSUMPTION to reconcile with backend. */
  vtt_url?: string | null;
}

/** One selectable audio stream from GET /api/media-files/{id}/streams. */
export interface AudioStream {
  index: number;
  codec: string;
  language?: string | null;
  channels?: number | null;
  title?: string | null;
  default?: boolean;
}

/** GET /api/media-files/{media_file_id}/streams. */
export interface MediaStreams {
  subtitles: SubtitleStream[];
  audio: AudioStream[];
}

/** Video quality options for the stream/start quality picker. */
export type StreamQuality = "original" | "1080p" | "720p" | "480p";

/** Subtitle choice passed to stream/start: an index, "off", or "burn". */
export type SubtitleChoice = number | "off" | "burn";

/** GET /api/media-files/{id}/next-episode (Plex "Up Next"); null at the end. */
export interface NextEpisode {
  series_id: string;
  episode_id: string;
  media_file_id: string;
  season_number: number;
  episode_number: number;
  title: string;
}

/** One row of GET /api/on-deck: the next episode per started series. */
export interface OnDeckItem {
  kind: "episode";
  id: string; // series id
  episode_id: string;
  media_file_id: string;
  title: string;
  subtitle?: string | null;
  season_number: number;
  episode_number: number;
  poster_path?: string | null;
  position_sec: number;
  duration_sec?: number | null;
  updated_at: string;
}
