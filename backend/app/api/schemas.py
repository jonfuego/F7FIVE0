"""Pydantic request/response schemas for the API."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Usernames: lowercase alphanumerics plus . _ - , 3-64 chars. Enforced at
# the pydantic layer so the DB never sees an email-like or mixed-case
# value. The backend lowercases on input anyway so case-insensitive
# uniqueness is free.
USERNAME_PATTERN = r"^[a-z0-9._-]{3,64}$"


# ---- Auth ------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=1, max_length=256)
    device_label: Optional[str] = Field(default=None, max_length=120)
    # Native 2.0 clients send these in the body. `client_type` accepts
    # "browser" | "pwa" | "native"; anything else (or the legacy
    # x-client-type header) is normalized server-side. `device_name` is the
    # human label shown in the account screen's session list; it falls back
    # to `device_label` when omitted so the browser client keeps working
    # unchanged. `platform` / `client_version` populate the session row and
    # drive the min-version gate.
    client_type: Optional[str] = Field(
        default=None, pattern="^(browser|pwa|native)$",
    )
    device_name: Optional[str] = Field(default=None, max_length=120)
    platform: Optional[str] = Field(default=None, max_length=32)
    client_version: Optional[str] = Field(default=None, max_length=32)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    refresh_expires_in_seconds: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None  # if omitted, revoke all sessions for current user


# ---- Users (admin) ---------------------------------------------------------
class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=USERNAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(default="member", pattern="^(admin|member)$")


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


class UserUpdateRequest(BaseModel):
    """Admin-side partial update. Any field may be omitted."""
    display_name: Optional[str] = Field(default=None, max_length=120)
    role: Optional[str] = Field(default=None, pattern="^(admin|member)$")
    is_active: Optional[bool] = None


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime


# ---- Passkeys (WebAuthn) ---------------------------------------------------
class PasskeyRegisterVerifyRequest(BaseModel):
    """The credential returned by navigator.credentials.create, plus a label.

    `credential` is the raw PublicKeyCredential JSON the browser/app produced;
    it is passed to py_webauthn's verifier unchanged. `name` is the
    user-facing label for the account screen.
    """
    credential: dict
    name: Optional[str] = Field(default=None, max_length=120)


class PasskeyLoginVerifyRequest(BaseModel):
    """The assertion returned by navigator.credentials.get, plus client info.

    Mirrors LoginRequest's client fields so a passkey login yields a session
    with the right refresh-window semantics (native gets the 90-day sliding
    window, pwa the long window, browser the default).
    """
    credential: dict
    client_type: Optional[str] = Field(default=None, pattern="^(browser|pwa|native)$")
    device_name: Optional[str] = Field(default=None, max_length=120)
    platform: Optional[str] = Field(default=None, max_length=32)
    client_version: Optional[str] = Field(default=None, max_length=32)


class PasskeyRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class PasskeyOut(BaseModel):
    """A registered passkey for the account screen. Never exposes the public
    key or the raw credential id (secret-hygiene): only the server-side UUID,
    label, transports, and timestamps."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    transports: Optional[str] = None
    aaguid: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None


# ---- Library ---------------------------------------------------------------
class MediaFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    path: str
    container: Optional[str] = None
    size_bytes: Optional[int] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    audio_channels: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_sec: Optional[int] = None
    bitrate_kbps: Optional[int] = None
    scan_state: str


class MovieOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    year: Optional[int] = None
    overview: Optional[str] = None
    runtime_min: Optional[int] = None
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    radarr_id: Optional[int] = None
    media_files: list[MediaFileOut] = Field(default_factory=list)
    # Radarr-sourced genre list, JSONB on the model. Surfaced on the list
    # so the /movies page can render genre filter chips without a second
    # fetch. Nullable on the model when Radarr never sent any; we keep
    # that null surface here so the frontend can distinguish "no data"
    # from an explicitly-empty list.
    genres: Optional[list[str]] = None
    # TMDB-sourced enrichment surfaced on every list and detail row. Heavy
    # JSONB fields (cast, directors) live on MovieDetailOut so the grid
    # call doesn't lug a 10-thumb cast list per tile.
    tagline: Optional[str] = None
    tmdb_rating: Optional[float] = None
    tmdb_vote_count: Optional[int] = None
    metadata_synced_at: Optional[datetime] = None
    metadata_status: Optional[str] = None
    # When the row entered the library (sort key "Date added" in the app).
    created_at: Optional[datetime] = None


class MovieDetailOut(MovieOut):
    """Detail-view movie with the heavy JSONB columns attached. List
    callers stick with MovieOut so the grid stays slim."""

    cast: list[dict] = Field(default_factory=list)
    directors: list[dict] = Field(default_factory=list)
    # Manual sort override. Null on the vast majority of rows; admins
    # set this from the detail-page editor when the algorithmic
    # article-strip doesn't produce the desired ordering.
    sort_title: Optional[str] = None


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    season_number: int
    episode_number: int
    title: Optional[str] = None
    overview: Optional[str] = None
    media_files: list[MediaFileOut] = Field(default_factory=list)


class SeriesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    # Derived from Series.first_aired.year in the endpoint. Lets list cards
    # render "Title (2019)" without a second call to look up the season
    # premiere date. Nullable for rows that never had a first_aired value.
    year: Optional[int] = None
    overview: Optional[str] = None
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None
    tvdb_id: Optional[int] = None
    tmdb_id: Optional[int] = None
    sonarr_id: Optional[int] = None
    # When the row entered the library (sort key "Date added" in the app).
    created_at: Optional[datetime] = None


class SeriesDetailOut(SeriesOut):
    episodes: list[EpisodeOut] = Field(default_factory=list)
    # Manual sort override; see MovieDetailOut.sort_title.
    sort_title: Optional[str] = None


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    duration_sec: Optional[int] = None
    media_files: list[MediaFileOut] = Field(default_factory=list)


class AlbumOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    artist_id: uuid.UUID
    # Resolved via Album.artist relationship in the endpoint. Lets list cards
    # render "by <artist>" without a second call. Nullable because an album
    # row without a valid artist_id is a data bug, not a render-blocker.
    artist_name: Optional[str] = None
    title: str
    release_date: Optional[date] = None
    cover_path: Optional[str] = None
    # MB-derived fields. `album_type` is on the list shape so the grid
    # can render the type badge without a second call. The remaining
    # heavy columns live on AlbumDetailOut.
    album_type: Optional[str] = None
    metadata_synced_at: Optional[datetime] = None
    metadata_status: Optional[str] = None
    # When the row entered the library (sort key "Date added" in the app).
    created_at: Optional[datetime] = None


class AlbumDetailOut(AlbumOut):
    tracks: list[TrackOut] = Field(default_factory=list)
    secondary_types: list[str] = Field(default_factory=list)
    label: Optional[str] = None
    disambiguation: Optional[str] = None
    mb_rating: Optional[float] = None
    links: list[dict] = Field(default_factory=list)


class SongRowOut(BaseModel):
    """One row in the flat /songs index. Denormalized so the frontend can
    build queue items without a follow-up call per row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    duration_sec: Optional[int] = None
    album_id: uuid.UUID
    album_title: str
    cover_path: Optional[str] = None
    artist_id: uuid.UUID
    artist_name: str
    media_files: list[MediaFileOut] = Field(default_factory=list)


# ---- Music artists ---------------------------------------------------------
class MusicArtistOut(BaseModel):
    """One artist tile on the Music index.

    `image_path` comes through `resolve_art` so a manual art override
    wins over the Lidarr-synced portrait. `album_count` lets the card
    show '12 albums' without a second request per artist.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    image_path: Optional[str] = None
    album_count: int
    # Lightweight MB-derived fields safe to surface on the Music index.
    # `bio_text` and `links` are heavy and live on the detail shape.
    country: Optional[str] = None
    artist_type: Optional[str] = None
    formed_year: Optional[int] = None
    disbanded_year: Optional[int] = None
    bio_source: Optional[str] = None
    metadata_synced_at: Optional[datetime] = None
    metadata_status: Optional[str] = None


class MusicArtistDetailOut(MusicArtistOut):
    """Artist detail plus the full list of their albums, release-date
    ascending with null dates pushed to the end. Reuses AlbumOut so the
    album cards on the artist page render identically to /music search
    results and the Recently Added shelf."""

    albums: list[AlbumOut] = Field(default_factory=list)
    bio_text: Optional[str] = None
    links: list[dict] = Field(default_factory=list)
    # Manual sort override; see MovieDetailOut.sort_title.
    sort_name: Optional[str] = None


# ---- Music videos ----------------------------------------------------------
class MusicVideoArtistOut(BaseModel):
    """One artist tile on the Music Videos index.

    `image_path` comes from the Artist row if Lidarr synced a portrait;
    otherwise null and the UI renders a fallback. `video_count` lets the
    card show '3 videos' without a second request per artist.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    image_path: Optional[str] = None
    video_count: int


class MusicVideoOut(BaseModel):
    """One music video row. Includes the primary MediaFile id so the play
    button can deep-link to /watch/<media_file_id> without another call.

    Lives under a parent `MusicVideoRelease`; the artist is reachable via
    `release.artist_id`. The denormalized `artist_id` column stays on the
    DB row but is no longer surfaced in the API response.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    release_id: uuid.UUID
    title: str
    year: Optional[int] = None
    disc_number: int = 1
    track_number: Optional[int] = None
    thumb_path: Optional[str] = None
    media_file_id: Optional[uuid.UUID] = None
    duration_sec: Optional[int] = None


class MusicVideoReleaseOut(BaseModel):
    """One release tile on the music-video artist detail page.

    Mirrors AlbumOut shape but parent is the artist's filesystem-derived
    release rather than a Lidarr album. `disc_count` is computed from the
    max(disc_number) across child videos so the UI can render an N-disc
    badge without a follow-up call.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    artist_id: uuid.UUID
    title: str
    release_year: Optional[int] = None
    release_date: Optional[date] = None
    cover_path: Optional[str] = None
    video_count: int
    disc_count: int = 1
    sort_title: Optional[str] = None
    sort_year: Optional[int] = None


class MusicVideoArtistDetailOut(MusicVideoArtistOut):
    """Artist detail returns releases (not a flat video list).

    Per-release video tiles ride the release-detail endpoint instead;
    this list is intentionally release-grain.
    """

    releases: list[MusicVideoReleaseOut] = Field(default_factory=list)


class MusicVideoReleaseDetailOut(MusicVideoReleaseOut):
    """Release detail with the full ordered video list.

    `artist_name` is included so the page can render breadcrumbs without
    a second fetch.
    """

    artist_name: str
    videos: list[MusicVideoOut] = Field(default_factory=list)


class RecentMusicVideoOut(BaseModel):
    """One row on the home `Recently Added Music Videos` rail.

    Tiles link straight to `/watch/<media_file_id>` so the home row is
    one-click play, matching the movie home-row behavior. Includes
    `release_id` and `release_title` so the subtitle can render the
    release the video belongs to.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    artist_name: str
    release_id: uuid.UUID
    release_title: str
    thumb_path: Optional[str] = None
    media_file_id: uuid.UUID
    added_at: datetime


# ---- Watch progress --------------------------------------------------------
class ProgressUpsertRequest(BaseModel):
    """Body for PUT /api/library/progress/{media_file_id}.

    `duration_sec` is accepted on heartbeat because the player knows it
    earlier than ffprobe in some edge cases (e.g., a re-encoded file whose
    reported duration disagrees with the muxed track). The server stores the
    latest value so completed-threshold math stays accurate.
    """

    position_sec: int = Field(ge=0)
    duration_sec: Optional[int] = Field(default=None, ge=1)


class ProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    media_file_id: uuid.UUID
    position_sec: int
    duration_sec: Optional[int] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime


class TrackPlayCreateRequest(BaseModel):
    """Body for POST /api/library/track-plays.

    The user is taken from the JWT; clients never pass a user_id. Extra
    fields (including a stray user_id) are rejected so a misbehaving
    client can't write rows for someone else.
    """
    model_config = ConfigDict(extra="forbid")

    track_id: uuid.UUID
    ms_played: int = Field(ge=0)
    completed: bool = False


class TrackPlayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    track_id: uuid.UUID
    played_at: datetime
    ms_played: int
    completed: bool


class ContinueWatchingItemOut(BaseModel):
    """One row on the Continue Watching shelf.

    Same parent collapse as /recent: if multiple episodes of a series are
    in progress the shelf shows only the most recent one. `media_file_id`
    is carried so the card deeplinks straight to /watch/<id> without the
    UI needing another round trip.
    """

    kind: str  # "movie" | "series" | "album" | "music_video_release"
    id: uuid.UUID  # parent id (movie/series/album/music_video_release)
    media_file_id: uuid.UUID
    title: str
    subtitle: Optional[str] = None
    year: Optional[int] = None
    poster_path: Optional[str] = None
    position_sec: int
    duration_sec: Optional[int] = None
    updated_at: datetime


class OnDeckItemOut(BaseModel):
    """One row on the Home "On Deck" shelf (Plex semantics): the next episode
    to watch for each series the viewer has started. `id` is the series id so
    the card can deeplink to the show; `media_file_id` plays the episode."""

    kind: str = "episode"
    id: uuid.UUID  # series id
    episode_id: uuid.UUID
    media_file_id: uuid.UUID
    title: str
    subtitle: Optional[str] = None
    season_number: int
    episode_number: int
    poster_path: Optional[str] = None
    position_sec: int = 0
    duration_sec: Optional[int] = None
    updated_at: datetime


class RecentItemOut(BaseModel):
    """One entry in the Recently Added row.

    `kind` tells the UI which detail page to link to. `id` is the parent id
    (movie_id for movies, series_id for TV episodes, album_id for music
    tracks). `subtitle` is populated for TV and music so episodes/tracks
    can be distinguished within the parent.
    """

    kind: str  # "movie" | "series" | "album"
    id: uuid.UUID
    title: str
    subtitle: Optional[str] = None
    year: Optional[int] = None
    poster_path: Optional[str] = None
    added_at: datetime


class SearchResultOut(BaseModel):
    """One row in a cross-type search response.

    The shape mirrors RecentItemOut so the client can reuse poster cards.
    `subtitle` carries artist name for albums and series title hint for TV.
    We include `year` for movies so the UI can disambiguate remakes.
    """

    kind: str  # "movie" | "series" | "album"
    id: uuid.UUID
    title: str
    subtitle: Optional[str] = None
    year: Optional[int] = None
    poster_path: Optional[str] = None


# ---- Streaming -------------------------------------------------------------
_CapName = Annotated[str, Field(pattern=r"^[a-z0-9.-]{1,16}$")]


class ClientCapsIn(BaseModel):
    """What the client says it plays as-is (web: from `canPlayType`).
    Short lowercase names: containers like mp4 / mkv / webm, video codecs
    like h264 / hevc / vp9 / av1, audio codecs like aac / mp3 / opus."""

    containers: list[_CapName] = Field(default_factory=list, max_length=16)
    video_codecs: list[_CapName] = Field(default_factory=list, max_length=16)
    audio_codecs: list[_CapName] = Field(default_factory=list, max_length=16)


class StreamStartRequest(BaseModel):
    file_id: uuid.UUID
    # Optional resume offset in seconds. The API quantizes this to a bucket
    # (see OFFSET_BUCKET_SEC) before signing so a user can't create a
    # unique cache entry per one-second boundary. Clamped to 24h so a
    # pathological request can't feed ffmpeg an absurd `-ss` value.
    # Ignored for direct-play (the client seeks natively via Range).
    resume_sec: Optional[int] = Field(default=None, ge=0, le=86400)

    # Phase 2 track selection. All optional; omitting them preserves the exact
    # pre-Phase-2 behavior. For video, a non-default audio track or a burned
    # image subtitle forces an HLS remux with that stream mapped, and a quality
    # below the source caps the HLS ladder. The effective choice rides the
    # signed stream URL as the `o` token (services/track_opts.py), which also
    # keys the F7FIVE0-Stream transcode session and its cache dir.
    #   audio_track_index: ffmpeg stream index of the desired audio track.
    #   subtitle: a subtitle stream index, "off", or "burn" (image subs).
    #   quality: requested rendition ceiling.
    audio_track_index: Optional[int] = Field(default=None, ge=0)
    # int (a subtitle stream index), or the strings "off" / "burn".
    subtitle: Optional[Union[int, str]] = Field(default=None)
    quality: Optional[str] = Field(
        default=None, pattern="^(original|1080p|720p|480p)$",
    )

    # Why the stream URL is being minted. "play" is a normal local playback;
    # "cast" means the URL is being handed to a Chromecast receiver (web app or
    # native app). Cast starts are logged (`stream_start purpose=cast`) so the
    # smoke check can count them; no other behavior changes.
    purpose: str = Field(default="play", pattern="^(play|cast)$")

    # Optional client capability report. When present, a file whose
    # container and codecs the client reported direct-plays instead of being
    # transcoded. Omitted (older clients, the app, cast) keeps the built-in
    # direct-play list.
    client_caps: Optional[ClientCapsIn] = None

    @field_validator("subtitle")
    @classmethod
    def _validate_subtitle(cls, v: Optional[Union[int, str]]) -> Optional[Union[int, str]]:
        if v is None or isinstance(v, int):
            return v
        s = str(v).strip().lower()
        if s in ("off", "burn"):
            return s
        # A numeric string is accepted and coerced to an int stream index.
        if s.lstrip("-").isdigit():
            return int(s)
        raise ValueError('subtitle must be an int, "off", or "burn"')


class StreamStartResponse(BaseModel):
    """Returned by /api/stream/start. `url` is a same-origin absolute URL.

    `mode` is 'direct' (MP4 byte-range) or 'hls' (m3u8 master playlist).
    `expires_at` is ISO-8601 and matches the `exp` inside the signed URL.
    """

    media_file_id: uuid.UUID
    mode: str  # "direct" | "hls"
    url: str
    expires_at: datetime
    variant: Optional[str] = None
    # Light metadata so the player can render chrome before the stream
    # actually loads. Keeps the player from needing a second /movies/{id} call.
    title: Optional[str] = None
    duration_sec: Optional[int] = None
    container: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    # Artwork and metadata for the audio player UI. Only populated for
    # track kinds today; movies and episodes still rely on the detail
    # page's own poster. `cover_path` is the remote image URL Lidarr
    # synced (treated as an `<img src>` on the client).
    cover_path: Optional[str] = None
    # Absolute, short-lived HMAC-signed art URL (uid/exp/sig) for header-less
    # loaders such as the Android media notification / lock screen. Null when
    # the item has no local art.
    art_url: Optional[str] = None
    artist_name: Optional[str] = None
    album_title: Optional[str] = None
    # Effective track-options token carried in the signed URL (`o`), e.g.
    # "a2-q720". Null when the stream uses default tracks at source quality.
    track_opts: Optional[str] = None
    # Phase 2 track-selection echo. These reflect the chosen values back to the
    # player so it can confirm what the server accepted. Null when the caller
    # did not request them, preserving the pre-Phase-2 response shape for old
    # clients (the fields are simply absent-as-null).
    audio_track_index: Optional[int] = None
    subtitle: Optional[Union[int, str]] = None
    quality: Optional[str] = None
    # The TRUE source position the caller asked to resume at, in seconds.
    # This is the raw `resume_sec` (clamped), NOT the bucket. The player adds
    # this to the element clock to report the real source position, and uses it
    # with `seek_within_sec` to land on the exact requested second. Always 0 for
    # direct play (the client seeks natively via Range).
    offset_sec: int = 0
    # Where the HLS encode actually starts, in seconds: `_quantize_offset`
    # buckets the requested second down so one movie resumed at 45:12 vs 45:13
    # shares one ffmpeg session. The element's clock reads 0 at this source
    # second. Players add this to <video>.currentTime to map element time to
    # source time. Equals `offset_sec` for direct play (both 0).
    timeline_offset_sec: int = 0
    # Seconds the client must seek forward WITHIN the stream, after it starts,
    # to land on the exact requested second despite the bucketed encode start.
    # It is `offset_sec - timeline_offset_sec` (0..OFFSET_BUCKET_SEC-1). The
    # player sets <video>.currentTime to this once the media is ready. 0 for
    # direct play and for an on-bucket resume.
    seek_within_sec: int = 0


# ---- Admin ----------------------------------------------------------------
class ActiveTranscodeOut(BaseModel):
    """One live streaming session. Includes direct-play (no ffmpeg) too."""

    id: uuid.UUID
    user_id: uuid.UUID
    media_file_id: uuid.UUID
    title: str
    variant: str
    direct_play: bool
    started_at: datetime
    bytes_served: int
    # Latest ffmpeg realtime factor (encoded media time / wall time). Null for
    # direct-play and until the first progress block arrives. A value below
    # 1.0 means the encode is slower than playback; `below_realtime_sec` is how
    # long it has stayed there, so the admin can flag "server can't keep up".
    speed: Optional[float] = None
    below_realtime_sec: int = 0


class WatchHistoryRowOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_display_name: str
    media_file_id: uuid.UUID
    title: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    last_position_sec: int


# ---- Admin: sessions, auth events, server health --------------------------
class AdminSessionOut(BaseModel):
    """One active (unrevoked, unexpired) session, joined to its user."""

    id: uuid.UUID
    user_id: uuid.UUID
    username: str
    display_name: str
    device_label: Optional[str] = None
    client_type: str
    created_at: datetime
    last_seen_at: Optional[datetime] = None
    expires_at: datetime


class AuthEventOut(BaseModel):
    """One auth audit row, newest-first in list responses."""

    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    username: Optional[str] = None
    event: str
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    at: datetime


class ServerHealthOut(BaseModel):
    """Operator health snapshot for the /admin health card.

    Byte counts are raw; the frontend formats. Drive figures come from
    shutil.disk_usage on the cache and art roots resolved at runtime, so the
    card never hardcodes a drive letter. last_sync_at is null when no sync
    bookkeeping exists yet (no table is invented to populate it)."""

    transcode_cache_bytes: int
    transcode_cache_max_bytes: int
    cache_disk_free_bytes: int
    cache_disk_total_bytes: int
    art_disk_free_bytes: int
    art_disk_total_bytes: int
    open_transcode_sessions: int
    last_sync_at: Optional[datetime] = None


class AudioAnalysisProgressOut(BaseModel):
    """Progress of the automatic audio-analysis backfill for the admin panel.

    `analyzed` is the number of tracks with a stamped analysis row; `total` is
    every track in the music library; `pending` is the remainder still waiting
    (total - analyzed). The admin readout shows `analyzed / total`."""

    analyzed: int
    total: int
    pending: int


class AudioAnalysisStartOut(BaseModel):
    """Response to 'Analyze music now': how many tracks are still un-analyzed
    when the walk is (re)armed, so the admin knows how much is left to do."""

    status: str
    pending: int
    total: int


# ---- ux-extras: new-arrivals badge + intro/credits markers ----------------
class NewArrivalsBadgeOut(BaseModel):
    """Count of items added since the caller's last home-page visit."""

    count: int


class MediaMarkerOut(BaseModel):
    kind: str  # intro | credits
    start_sec: int
    end_sec: int

    model_config = {"from_attributes": True}


# ---- Media requests -------------------------------------------------------
class RequestSearchResultOut(BaseModel):
    """One upstream lookup hit, annotated with library/request state."""

    kind: str  # movie | series
    external_id: str  # tmdb id (movie) or tvdb id (series)
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    overview: Optional[str] = None
    in_library: bool = False
    requested: bool = False


class RequestCreate(BaseModel):
    kind: str = Field(pattern="^(movie|series)$")
    external_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    year: Optional[int] = None
    poster_url: Optional[str] = Field(default=None, max_length=1024)


class RequestDeny(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class RequestOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    year: Optional[int] = None
    external_id: str
    poster_url: Optional[str] = None
    status: str
    note: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    # Populated on the admin list so the panel can show who asked. Null on
    # the requester's own /mine view (they already know it's theirs).
    requested_by: Optional[str] = None

    model_config = {"from_attributes": True}


# ---- Sort overrides (admin) -----------------------------------------------
class SortOverrideUpdate(BaseModel):
    """PATCH /api/admin/sort/{kind}/{id} body.

    `value` is the new sort key (e.g. 'Star Wars 4 A New Hope'), or
    null/empty to clear and fall back to the algorithmic article-stripped
    lowercase title. Empty string is normalized to null on the server
    so a user clearing the input field reliably clears the override.
    """
    value: Optional[str] = Field(default=None, max_length=255)


class SortOverrideOut(BaseModel):
    """PATCH /api/admin/sort/{kind}/{id} response. Echoes the saved value."""
    value: Optional[str] = None


# ---- Unified overrides + Fix Match ----------------------------------------
# A single PATCH endpoint per entity kind handles every override field the
# Edit Overrides modal saves. `sort_title` lives on its own column on the
# entity row because _sort_expr in api/library.py needs a real column to
# COALESCE against; the rest of the fields live in entity.overrides JSONB
# and get applied at the response-serializer boundary via merge_overrides.

class OverrideUpdate(BaseModel):
    """PATCH /api/admin/override/{kind}/{id} body.

    Partial: every field is optional. Three states per field:
      - absent              -> leave the existing value untouched
      - explicit None       -> clear the override (delete the JSONB key
                               or null the column)
      - non-null value      -> set the override

    Use `model_fields_set` on the server to distinguish absence from
    explicit None.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: Optional[str] = Field(default=None, max_length=512)
    sort_title: Optional[str] = Field(default=None, max_length=255)
    tagline: Optional[str] = Field(default=None, max_length=2048)
    year: Optional[int] = Field(default=None, ge=1800, le=2200)
    runtime_min: Optional[int] = Field(default=None, ge=1, le=10000)
    rating: Optional[float] = Field(default=None, ge=0, le=10)


class OverrideOut(BaseModel):
    """PATCH /api/admin/override/{kind}/{id} response.

    Returns the full effective view of the entity's editable fields so the
    modal can render both the canonical *arr-synced metadata and the
    operator overrides side by side. `external_id` exposes the source-of-
    truth pointer (TMDB id for movies/series, MBID for music) so the
    modal's Refresh tab knows what to call.
    """

    kind: str
    entity_id: uuid.UUID
    canonical: dict
    overrides: dict
    sort_title: Optional[str] = None
    external_id: Optional[dict] = None


class MatchCandidate(BaseModel):
    """One candidate row in the Fix Match result list.

    The shape is uniform across kinds so the picker UI renders the same
    way for movies, series, artists, albums, and music-video releases.
    `source` is the upstream ("tmdb" / "tvdb" / "musicbrainz") and `ref`
    is the id within that source.
    """

    source: str
    ref: str
    label: str
    year: Optional[int] = None
    image_url: Optional[str] = None
    summary: Optional[str] = None


class MatchApply(BaseModel):
    """POST /api/admin/match/{kind}/{id} body.

    `source` and `ref` are picked verbatim from a MatchCandidate. The
    server validates the candidate exists, writes the new external id,
    and triggers a synchronous canonical-metadata refresh.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=32)
    ref: str = Field(min_length=1, max_length=128)


# ---- Self-service device sessions (native 2.0) -----------------------------
class SessionOut(BaseModel):
    """One of the current user's own sessions, for the account screen.

    `current` flags the session the requesting access token belongs to (via
    the `sid` claim) so the UI can label it "This device" and refuse to let
    the user revoke the one they're using from the revoke-one control. No
    token material is ever exposed.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_label: Optional[str] = None
    client_type: str
    platform: Optional[str] = None
    client_version: Optional[str] = None
    created_at: datetime
    last_seen_at: Optional[datetime] = None
    expires_at: datetime
    current: bool = False


class SessionRevokeResult(BaseModel):
    """Result of a bulk revoke (DELETE /api/sessions)."""

    revoked: int


# ---- Client support endpoints (native 2.0) ---------------------------------
class MinClientVersionOut(BaseModel):
    """Minimum supported app version per platform. Read from .env
    MIN_CLIENT_VERSION_* keys, each defaulting to 0.0.0."""

    android: str
    ios: str
    android_tv: str
    tvos: str


class ClientErrorReport(BaseModel):
    """POST /api/client/errors body. Phase 4 crash reporting with no
    third-party service: the server writes one structured line to the API
    log. The whole payload is capped at 8 KB at the router before this
    validates, so these fields are already length-bounded defensively."""

    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1, max_length=2000)
    stack: Optional[str] = Field(default=None, max_length=6000)
    platform: Optional[str] = Field(default=None, max_length=32)
    client_version: Optional[str] = Field(default=None, max_length=32)
    fatal: bool = False
    context: Optional[str] = Field(default=None, max_length=1000)


# ---- Library folders (Admin > Library folders) -----------------------------
class LibraryFolderOut(BaseModel):
    path: str
    reachable: bool


class LibraryFoldersLibraryOut(BaseModel):
    kind: str
    label: str
    folders: list[LibraryFolderOut]
    # Radarr / Sonarr / Lidarr owns this library (its API key is set), so the
    # folder scanner leaves it alone even when folders are listed.
    arr_managed: bool


class LibraryFoldersOut(BaseModel):
    # "env": read from LIBRARY_ROOT_* in .env (nothing saved here yet).
    # "admin": saved from this page; .env values are no longer used.
    source: str
    libraries: list[LibraryFoldersLibraryOut]


class LibraryFoldersIn(BaseModel):
    folders: dict[str, list[str]]
# ---- Metadata (Admin > Metadata) -------------------------------------------
class TmdbKeyStatusOut(BaseModel):
    configured: bool
    # "admin": saved from the Admin page; "env": TMDB_API_KEY in .env
    # (from Setup); None: no key.
    source: Optional[str] = None
    masked: Optional[str] = None


class MetadataSettingsOut(BaseModel):
    tmdb: TmdbKeyStatusOut


class TmdbKeyIn(BaseModel):
    api_key: str


class TmdbKeyCheckOut(BaseModel):
    ok: bool
    message: str


# ---- Admin reminders (web banner) --------------------------------------------
class ReminderOut(BaseModel):
    id: str
    title: str
    body: str
    action_label: str
    action_href: str


class ReminderSnoozeIn(BaseModel):
    forever: bool = False


# ---- Live channel + server clock ------------------------------------------
class LiveEventOut(BaseModel):
    """The typed live-event envelope as returned over HTTP (the SSE wire form
    is the same JSON object). `ts` is server UNIX seconds; `id` is unique."""

    type: str
    data: Optional[object] = None
    ts: float
    id: str


class LiveCommandRequest(BaseModel):
    """A client -> server command posted to /api/live/command. `type` is a
    dotted event name; `data` is an arbitrary JSON payload."""

    type: str = Field(min_length=1, max_length=128)
    data: Optional[object] = None


class ServerTimeOut(BaseModel):
    """Server clock for client offset / round-trip estimation."""

    unix_ms: int
    unix_sec: float
