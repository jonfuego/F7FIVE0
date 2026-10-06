"""Playback decision logic.

Given a `MediaFile` and an optional client hint, decide whether the client can
direct-play the file or whether we have to spin up an HLS transcode. Also
owns the variant ladder selection for the transcode path.

Kept deliberately simple. We do not negotiate with the client over codecs in
v1. Direct-play is a narrow allow-list; everything else falls back to HLS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from app.models.media_file import MediaFile, ScanState


# Containers that browser + hls.js handle natively when wrapped in MP4.
_DIRECT_PLAY_CONTAINERS = {"mp4", "m4v", "mov"}

# Containers that unambiguously indicate an audio-only file regardless
# of what the scanner wrote into `video_codec`. ID3v2 embedded cover art
# shows up to ffprobe as an mjpeg/png "video" stream, so we cannot trust
# `video_codec == null` alone to identify audio tracks.
_AUDIO_CONTAINERS = {
    "mp3", "m4a", "aac", "wav", "flac", "ogg", "oga", "opus", "wma",
}

# Audio containers all modern browsers and the Chromecast Default Media
# Receiver play natively. A strict subset of _AUDIO_CONTAINERS above.
# WMA, OPUS in Ogg, and raw OGG Vorbis fall outside this list and would
# need an audio-only HLS fork to play on Chromecast; browsers handle
# most of them fine.
_DIRECT_PLAY_AUDIO_CONTAINERS = {"mp3", "m4a", "aac", "wav", "flac", "ogg"}

# Codec allow-lists for direct-play. H.264 + AAC/MP3 is the intersection
# that plays on Safari, Chrome, Firefox, iOS, Android without a transcode.
_DIRECT_PLAY_VIDEO = {"h264", "avc1"}
_DIRECT_PLAY_AUDIO = {"aac", "mp4a", "mp3"}


# Codec names a client may report, mapped onto the names the scanner stores.
_CODEC_ALIASES = {"avc1": "h264", "avc": "h264", "hvc1": "hevc", "hev1": "hevc",
                  "h265": "hevc", "mp4a": "aac", "ac-3": "ac3", "ec-3": "eac3"}
_CONTAINER_ALIASES = {"matroska": "mkv"}


def _norm_codec(name: Optional[str]) -> str:
    n = (name or "").strip().lower()
    return _CODEC_ALIASES.get(n, n)


@dataclass(frozen=True)
class ClientCaps:
    """What a client says it plays as-is: containers and codecs, as the web
    player learns them from `canPlayType`. Only widens the built-in direct-play
    list; a client that reports nothing gets the old decision."""

    containers: frozenset = field(default_factory=frozenset)
    video_codecs: frozenset = field(default_factory=frozenset)
    audio_codecs: frozenset = field(default_factory=frozenset)

    @classmethod
    def from_lists(cls, containers: Iterable[str] = (), video_codecs: Iterable[str] = (),
                   audio_codecs: Iterable[str] = ()) -> "ClientCaps":
        def c(x: str) -> str:
            n = x.strip().lower()
            return _CONTAINER_ALIASES.get(n, n)
        return cls(
            containers=frozenset(c(x) for x in containers),
            video_codecs=frozenset(_norm_codec(x) for x in video_codecs),
            audio_codecs=frozenset(_norm_codec(x) for x in audio_codecs),
        )


@dataclass(frozen=True)
class Variant:
    """A single rung of the HLS variant ladder."""

    label: str
    height: int
    video_bitrate_kbps: int
    audio_bitrate_kbps: int

    @property
    def max_bitrate_kbps(self) -> int:
        # ffmpeg -maxrate. 25% over target is a sane buffer for NVENC VBR.
        return int(self.video_bitrate_kbps * 1.25)

    @property
    def bufsize_kbps(self) -> int:
        return self.video_bitrate_kbps * 2


# Ladder copied from `f7five0-architecture.md`. Ordered high to low so the
# picker walks down until it finds something below source resolution.
VARIANT_LADDER: tuple[Variant, ...] = (
    Variant("high",   1080, 6000, 192),
    Variant("medium",  720, 3000, 128),
    Variant("low",     480, 1200,  96),
)


@dataclass(frozen=True)
class PlaybackDecision:
    mode: str                          # "direct" or "hls"
    variant: Optional[str] = None      # "original" (direct) or label for hls
    reason: str = ""                   # free-form, for logs


def is_audio_only(mf: MediaFile) -> bool:
    """True when the container is an audio container, regardless of what the
    scanner put in `video_codec`. ID3v2 embedded cover art gets reported by
    ffprobe as an mjpeg or png "video" stream, so any heuristic that checks
    `video_codec is null` misclassifies every tagged MP3 / FLAC in the library
    as a silent-video file and routes it into the NVENC transcoder (which then
    fails because the input has no real video).
    """
    return (getattr(mf, "container", None) or "").lower() in _AUDIO_CONTAINERS


def can_direct_play(mf: MediaFile, caps: Optional[ClientCaps] = None) -> tuple[bool, str]:
    """Return (ok, reason). Reason populated whether ok or not.

    `caps` is what the client reported it can play. Without it the narrow
    built-in list applies (H.264 + AAC/MP3 in MP4). With it, a container or
    codec the client reported also direct-plays: Chrome plays H.264 + AAC in
    Matroska, so an MKV no longer gets re-encoded (and on a CPU-only server
    scaled down to 720p) when the browser could have played the file."""
    if mf.scan_state != ScanState.ready:
        return False, f"scan_state={mf.scan_state.value}"
    container = (mf.container or "").lower()

    # Audio-only files. Route the browser + Chromecast-friendly containers
    # (MP3, M4A/AAC, WAV, FLAC, OGG Vorbis) straight to the direct endpoint.
    # OPUS and WMA fall through to the HLS path, which today still runs the
    # video transcoder and will fail on a pure-audio source. An audio-only
    # HLS fork is planned in Phase 5; until then, OPUS/WMA won't play and
    # that's the correct, loud failure.
    if is_audio_only(mf):
        if container in _DIRECT_PLAY_AUDIO_CONTAINERS:
            return True, "direct_ok_audio"
        return False, f"audio_container={container or 'unknown'}"

    reported = caps or ClientCaps()
    if container not in _DIRECT_PLAY_CONTAINERS and container not in reported.containers:
        return False, f"container={container or 'unknown'}"
    vcodec = _norm_codec(mf.video_codec)
    if vcodec and vcodec not in _DIRECT_PLAY_VIDEO and vcodec not in reported.video_codecs:
        return False, f"video_codec={vcodec}"
    acodec = _norm_codec(mf.audio_codec)
    if acodec and acodec not in _DIRECT_PLAY_AUDIO and acodec not in reported.audio_codecs:
        return False, f"audio_codec={acodec}"
    # Music videos with no audio codec still pass here; the browser will
    # render silently if the file genuinely lacks audio.
    if container not in _DIRECT_PLAY_CONTAINERS:
        return True, "direct_ok_client_caps"
    return True, "direct_ok"


def pick_variants(mf: MediaFile) -> tuple[Variant, ...]:
    """Ladder for this source. Drops rungs at or above the source height."""
    source_h = mf.height or 0
    if source_h <= 0:
        # Unknown source resolution. Give the player all rungs and let it
        # choose. ABR will settle on whatever fits.
        return VARIANT_LADDER
    # Keep rungs strictly below source height, plus the highest rung that is
    # at or below source so the user isn't capped below native resolution.
    at_or_below = [v for v in VARIANT_LADDER if v.height <= source_h]
    if not at_or_below:
        # Source is tiny (< 480p). Transcode to the lowest rung anyway so the
        # player gets a stream. The picker should not return an empty ladder.
        return (VARIANT_LADDER[-1],)
    return tuple(at_or_below)


# Without hardware encoding each rung is a full CPU encode, and players that
# switch rungs on their own (Firefox / Chrome native HLS, ExoPlayer, Safari)
# start a second cold encode. So a CPU-only server offers ONE rung per stream:
# the viewer's pick (the `q` ceiling) or this default.
CPU_DEFAULT_HEIGHT = 720


def single_rung_for_cpu(
    variants: tuple[Variant, ...], max_height: Optional[int],
) -> tuple[Variant, ...]:
    """The one rung a CPU-only server offers: the highest at or below the
    viewer's ceiling (or CPU_DEFAULT_HEIGHT), else the smallest rung."""
    if not variants:
        return variants
    ceiling = max_height or CPU_DEFAULT_HEIGHT
    fitting = [v for v in variants if v.height <= ceiling]
    if fitting:
        return (max(fitting, key=lambda v: v.height),)
    return (min(variants, key=lambda v: v.height),)


def decide(mf: MediaFile, caps: Optional[ClientCaps] = None) -> PlaybackDecision:
    ok, reason = can_direct_play(mf, caps)
    if ok:
        return PlaybackDecision(mode="direct", variant="original", reason=reason)
    return PlaybackDecision(mode="hls", variant=None, reason=reason)
