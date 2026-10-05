// Shared response types mirroring backend/app/api/schemas.py.
// Kept hand-written so the frontend doesn't depend on a codegen step.

export type { QueueItem } from "./queue";

export type UserRole = "admin" | "member";

export type Me = {
  id: string;
  username: string;
  display_name: string;
  role: UserRole | string;
  is_active: boolean;
  created_at: string;
};

export type MediaFile = {
  id: string;
  path: string;
  container: string | null;
  size_bytes: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  audio_channels: number | null;
  width: number | null;
  height: number | null;
  duration_sec: number | null;
  bitrate_kbps: number | null;
  scan_state: "pending" | "ready" | "missing" | "error" | string;
};

export type CastMember = {
  name: string | null;
  character: string | null;
  order: number | null;
  profile_path: string | null;
};

export type CrewMember = {
  name: string | null;
  profile_path: string | null;
};

export type Movie = {
  id: string;
  title: string;
  year: number | null;
  overview: string | null;
  runtime_min: number | null;
  poster_path: string | null;
  backdrop_path: string | null;
  tmdb_id: number | null;
  imdb_id: string | null;
  radarr_id: number | null;
  media_files: MediaFile[];
  genres: string[] | null;
  tagline: string | null;
  tmdb_rating: number | null;
  tmdb_vote_count: number | null;
  metadata_synced_at: string | null;
  metadata_status: string | null;
};

export type MovieDetail = Movie & {
  cast: CastMember[];
  directors: CrewMember[];
  // Manual sort override; null when the algorithmic article-strip is in effect.
  sort_title: string | null;
};

export type Series = {
  id: string;
  title: string;
  year: number | null;
  overview: string | null;
  poster_path: string | null;
  backdrop_path: string | null;
  tvdb_id: number | null;
  tmdb_id: number | null;
  sonarr_id: number | null;
};

export type Episode = {
  id: string;
  season_number: number;
  episode_number: number;
  title: string | null;
  overview: string | null;
  media_files: MediaFile[];
};

export type SeriesDetail = Series & {
  episodes: Episode[];
  sort_title: string | null;
};

export type ExternalLink = {
  kind: string;
  url: string;
};

export type Album = {
  id: string;
  artist_id: string;
  artist_name: string | null;
  title: string;
  release_date: string | null;
  cover_path: string | null;
  album_type: string | null;
  metadata_synced_at: string | null;
  metadata_status: string | null;
};

export type Track = {
  id: string;
  title: string;
  track_number: number | null;
  disc_number: number | null;
  duration_sec: number | null;
  media_files: MediaFile[];
};

export type AlbumDetail = Album & {
  tracks: Track[];
  secondary_types: string[];
  label: string | null;
  disambiguation: string | null;
  mb_rating: number | null;
  links: ExternalLink[];
};

export type SongRow = {
  id: string;
  title: string;
  track_number: number | null;
  disc_number: number | null;
  duration_sec: number | null;
  album_id: string;
  album_title: string;
  cover_path: string | null;
  artist_id: string;
  artist_name: string;
  media_files: MediaFile[];
};

export type MusicArtist = {
  id: string;
  name: string;
  image_path: string | null;
  album_count: number;
  country: string | null;
  artist_type: string | null;
  formed_year: number | null;
  disbanded_year: number | null;
  bio_source: string | null;
  metadata_synced_at: string | null;
  metadata_status: string | null;
};

export type MusicArtistDetail = MusicArtist & {
  albums: Album[];
  bio_text: string | null;
  links: ExternalLink[];
  sort_name: string | null;
};

export type MusicVideoArtist = {
  id: string;
  name: string;
  image_path: string | null;
  video_count: number;
};

export type MusicVideo = {
  id: string;
  release_id: string;
  title: string;
  year: number | null;
  disc_number: number;
  track_number: number | null;
  thumb_path: string | null;
  media_file_id: string | null;
  duration_sec: number | null;
};

export type MusicVideoRelease = {
  id: string;
  artist_id: string;
  title: string;
  release_year: number | null;
  release_date: string | null;
  cover_path: string | null;
  video_count: number;
  disc_count: number;
  sort_title: string | null;
  sort_year: number | null;
};

export type MusicVideoArtistDetail = MusicVideoArtist & {
  releases: MusicVideoRelease[];
};

export type MusicVideoReleaseDetail = MusicVideoRelease & {
  artist_name: string;
  videos: MusicVideo[];
};

export type RecentMusicVideo = {
  id: string;
  title: string;
  artist_name: string;
  release_id: string;
  release_title: string;
  thumb_path: string | null;
  media_file_id: string;
  added_at: string;
};

export type RecentItem = {
  kind: "movie" | "series" | "album";
  id: string;
  title: string;
  subtitle: string | null;
  year: number | null;
  poster_path: string | null;
  added_at: string;
};

export type SearchResult = {
  kind: "movie" | "series" | "album";
  id: string;
  title: string;
  subtitle: string | null;
  year: number | null;
  poster_path: string | null;
};

export type Progress = {
  media_file_id: string;
  position_sec: number;
  duration_sec: number | null;
  completed_at: string | null;
  updated_at: string;
};

export type ContinueWatchingItem = {
  kind: "movie" | "series" | "album" | "music_video_release";
  id: string;
  media_file_id: string;
  title: string;
  subtitle: string | null;
  year: number | null;
  poster_path: string | null;
  position_sec: number;
  duration_sec: number | null;
  updated_at: string;
};

export type AdminUser = Me;

export type ActiveTranscode = {
  id: string;
  user_id: string;
  user_display_name: string;
  media_file_id: string;
  title: string;
  variant: string;
  direct_play: boolean;
  started_at: string;
  bytes_served: number;
};

export type WatchHistoryRow = {
  id: string;
  user_id: string;
  user_display_name: string;
  media_file_id: string;
  title: string;
  started_at: string;
  ended_at: string | null;
  last_position_sec: number;
};

export type AdminSession = {
  id: string;
  user_id: string;
  username: string;
  display_name: string;
  device_label: string | null;
  client_type: string;
  created_at: string;
  last_seen_at: string | null;
  expires_at: string;
};

export type AuthEvent = {
  id: string;
  user_id: string | null;
  username: string | null;
  event: string;
  ip: string | null;
  user_agent: string | null;
  at: string;
};

export type ServerHealth = {
  transcode_cache_bytes: number;
  transcode_cache_max_bytes: number;
  cache_disk_free_bytes: number;
  cache_disk_total_bytes: number;
  art_disk_free_bytes: number;
  art_disk_total_bytes: number;
  open_transcode_sessions: number;
  last_sync_at: string | null;
};

// ---- Admin > Remote access --------------------------------------------------
export type RemoteAccessMethod = "tailscale" | "cloudflare" | "portforward" | "token";

export type RemoteAccessRunState =
  | "idle" | "queued" | "running" | "signin" | "restarting"
  | "succeeded" | "failed" | "cancelled";

export type RemoteAccessRun = {
  id: string | null;
  method: RemoteAccessMethod | "off" | null;
  host: string | null;
  state: RemoteAccessRunState;
  step: string | null;
  sign_in_url: string | null;
  sign_in_deadline: string | null;
  sign_in_seconds_left: number | null;
  public_url: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  log: string[];
};

export type RemoteAccessStatus = {
  available: boolean;
  method: RemoteAccessMethod | null;
  public_url: string | null;
  pending_public_url: string | null;
  reachable: boolean | null;
  tunnel_service: string | null;
  proxy_service: string | null;
  web_port: number;
  run: RemoteAccessRun;
};

// ---- Library folders (Admin > Library folders) -----------------------------
export type LibraryFolderKind = "movies" | "tv" | "music" | "music_videos";

export type LibraryFolder = {
  path: string;
  // The server (as the account its services run under) can open it.
  reachable: boolean;
};

export type LibraryFoldersLibrary = {
  kind: LibraryFolderKind;
  label: string;
  folders: LibraryFolder[];
  arr_managed: boolean;
};

export type LibraryFolders = {
  // "env": still read from LIBRARY_ROOT_* in .env; "admin": saved here.
  source: "env" | "admin";
  libraries: LibraryFoldersLibrary[];
};

// ---- Metadata settings (Admin > Metadata) ----------------------------------
export type TmdbKeyStatus = {
  configured: boolean;
  // "admin": saved on the Admin page; "env": from Setup (.env); null: none.
  source: "admin" | "env" | null;
  masked: string | null;
};

export type MetadataSettings = { tmdb: TmdbKeyStatus };

export type TmdbKeyCheck = { ok: boolean; message: string };

// ---- Admin reminders (banner) -----------------------------------------------
export type AdminReminder = {
  id: string;
  title: string;
  body: string;
  action_label: string;
  action_href: string;
};

// ---- Intro/credits markers -------------------------------------------------
export type MediaMarker = {
  kind: "intro" | "credits";
  start_sec: number;
  end_sec: number;
};

// ---- Media requests --------------------------------------------------------
export type RequestKind = "movie" | "series";
export type RequestStatus = "pending" | "approved" | "denied" | "available";

export type RequestSearchResult = {
  kind: RequestKind;
  external_id: string;
  title: string;
  year: number | null;
  poster_url: string | null;
  overview: string | null;
  in_library: boolean;
  requested: boolean;
};

export type MediaRequest = {
  id: string;
  kind: RequestKind;
  title: string;
  year: number | null;
  external_id: string;
  poster_url: string | null;
  status: RequestStatus;
  note: string | null;
  created_at: string;
  resolved_at: string | null;
  requested_by: string | null;
};

// ---- Unified overrides + Fix Match -----------------------------------------
// Wire types that mirror backend/app/api/schemas.py. The PATCH endpoint
// expects a partial body where each field has three states: omitted ->
// untouched, explicit null -> clear the override, non-null value -> set.
// TypeScript can't distinguish "key absent" from "key present with value
// undefined" in JSON.stringify, so always serialize via a helper that
// builds an object from only the dirty fields.

export type OverrideKind =
  | "movie"
  | "series"
  | "artist"
  | "album"
  | "track"
  | "music_video_release";

export type OverrideUpdate = {
  display_name?: string | null;
  sort_title?: string | null;
  tagline?: string | null;
  year?: number | null;
  runtime_min?: number | null;
  rating?: number | null;
};

export type OverrideOut = {
  kind: OverrideKind | string;
  entity_id: string;
  canonical: Record<string, unknown>;
  overrides: Record<string, unknown>;
  sort_title: string | null;
  external_id: { source: string; id: string } | null;
};

export type MatchCandidate = {
  source: string;
  ref: string;
  label: string;
  year: number | null;
  image_url: string | null;
  summary: string | null;
};

export type StreamStartRequest = {
  file_id: string;
  // Optional resume hint in seconds. The backend quantizes to a 10s bucket
  // and bakes it into the signed URL as `t=`. Only honored for HLS streams;
  // direct-play ignores it (the client seeks via byte-range instead).
  resume_sec?: number;
  // Rendition ceiling. On CPU-only servers it picks the one rendition the
  // stream carries (default 720p).
  quality?: "original" | "1080p" | "720p" | "480p";
};

export type StreamStart = {
  media_file_id: string;
  mode: "direct" | "hls";
  url: string;
  expires_at: string;
  variant: string | null;
  title: string | null;
  duration_sec: number | null;
  container: string | null;
  video_codec: string | null;
  audio_codec: string | null;
  width: number | null;
  height: number | null;
  // Track artwork + labels for the audio player. Populated only for
  // `kind == "track"` MediaFiles; null for movies and episodes.
  cover_path: string | null;
  artist_name: string | null;
  album_title: string | null;
  // Where the stream starts in the source (seconds). A resumed HLS stream's
  // timeline starts at 0, so add this to <video>.currentTime.
  offset_sec?: number;
};
