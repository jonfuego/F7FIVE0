"""Playback decision logic.

Given a `MediaFile` and an optional client hint, decide whether the client can
direct-play the file or whether we have to spin up an HLS transcode. Also
owns the variant ladder selection for the transcode path.

Kept deliberately simple. We do not negotiate with the client over codecs in
v1. Direct-play is a narrow allow-list; everything else falls back to HLS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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
    return (mf.container or "").lower() in _AUDIO_CONTAINERS


def can_direct_play(mf: MediaFile) -> tuple[bool, str]:
    """Return (ok, reason). Reason populated whether ok or not."""
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

    if container not in _DIRECT_PLAY_CONTAINERS:
        return False, f"container={container or 'unknown'}"
    vcodec = (mf.video_codec or "").lower()
    if vcodec and vcodec not in _DIRECT_PLAY_VIDEO:
        return False, f"video_codec={vcodec}"
    acodec = (mf.audio_codec or "").lower()
    if acodec and acodec not in _DIRECT_PLAY_AUDIO:
        return False, f"audio_codec={acodec}"
    # Music videos with no audio codec still pass here; the browser will
    # render silently if the file genuinely lacks audio.
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


def decide(mf: MediaFile) -> PlaybackDecision:
    ok, reason = can_direct_play(mf)
    if ok:
        return PlaybackDecision(mode="direct", variant="original", reason=reason)
    return PlaybackDecision(mode="hls", variant=None, reason=reason)
