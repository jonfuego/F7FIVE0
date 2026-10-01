"""Per-stream track options for HLS transcodes (Phase 2, spec section I).

The native player lets the viewer pick an audio track, an image-based subtitle
to burn in, and a quality ceiling. The API folds those choices into a compact
token (`o`) that rides the signed stream URL. The token is part of the HMAC
payload (so it can't be retargeted), part of the transcode registry key, and
part of the cache directory, so two different picks for the same file never
share an ffmpeg process or a segment on disk.

Token grammar (all parts optional, in this order, joined by "-"):
    a<N>   ffmpeg absolute stream index of the audio track to map (-map 0:N)
    s<N>   ffmpeg absolute stream index of an image subtitle to burn in
    q<H>   max output height: 1080, 720 or 480

An empty token means "no options": argv, cache layout and signatures are then
bit-identical to the pre-Phase-2 behavior.

Pure module (no ffmpeg, no DB) so it unit-tests in isolation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


QUALITY_HEIGHTS = {"1080p": 1080, "720p": 720, "480p": 480}
_ALLOWED_HEIGHTS = {1080, 720, 480}
_TOKEN_RE = re.compile(r"^(?:a(\d{1,3}))?(?:-?s(\d{1,3}))?(?:-?q(\d{3,4}))?$")


class TrackOptsError(ValueError):
    """Raised for a malformed or out-of-range token."""


@dataclass(frozen=True)
class TrackOpts:
    audio_index: Optional[int] = None
    burn_sub_index: Optional[int] = None
    max_height: Optional[int] = None

    @property
    def empty(self) -> bool:
        return self.audio_index is None and self.burn_sub_index is None and self.max_height is None

    def to_token(self) -> str:
        parts: list[str] = []
        if self.audio_index is not None:
            parts.append(f"a{self.audio_index}")
        if self.burn_sub_index is not None:
            parts.append(f"s{self.burn_sub_index}")
        if self.max_height is not None:
            parts.append(f"q{self.max_height}")
        return "-".join(parts)


def parse_token(token: Optional[str]) -> TrackOpts:
    """Parse an `o` token. Empty/None -> TrackOpts(). Raises TrackOptsError."""
    if not token:
        return TrackOpts()
    m = _TOKEN_RE.match(token)
    if not m or not any(m.groups()):
        raise TrackOptsError("bad_track_opts")
    a, s, q = m.groups()
    height = int(q) if q is not None else None
    if height is not None and height not in _ALLOWED_HEIGHTS:
        raise TrackOptsError("bad_track_opts_quality")
    opts = TrackOpts(
        audio_index=int(a) if a is not None else None,
        burn_sub_index=int(s) if s is not None else None,
        max_height=height,
    )
    # Canonical form only, so one choice maps to exactly one cache dir/key.
    if opts.to_token() != token:
        raise TrackOptsError("bad_track_opts")
    return opts


def resolve_track_opts(
    *,
    audio_track_index: Optional[int],
    subtitle,
    quality: Optional[str],
    source_height: Optional[int],
    streams: Optional[dict],
) -> TrackOpts:
    """Turn the stream/start request choices into TrackOpts.

    - audio: kept only when it names a real audio stream that is not the
      container's default (first) audio, because that one plays without a remux.
    - subtitle: an int naming an image-based subtitle is burned in; "burn"
      picks the first image-based subtitle. Text subs are side-loaded as
      WebVTT by the client, so they never force a transcode. "off"/None -> none.
    - quality: a ceiling below the source height; "original" or a ceiling at or
      above the source height is a no-op.

    `streams` is the `{subtitles, audio}` shape from media_streams.parse_streams
    (or None when ffprobe is unavailable, in which case audio/subtitle choices
    can't be validated and are dropped rather than guessed).
    """
    from app.services.media_streams import is_image_subtitle

    audio_idx: Optional[int] = None
    burn_idx: Optional[int] = None
    max_h: Optional[int] = None

    audio = (streams or {}).get("audio") or []
    subs = (streams or {}).get("subtitles") or []

    if audio_track_index is not None and audio:
        indices = [a.get("index") for a in audio]
        default = next((a.get("index") for a in audio if a.get("default")), indices[0])
        if audio_track_index in indices and audio_track_index != default:
            audio_idx = audio_track_index

    if isinstance(subtitle, int) and not isinstance(subtitle, bool):
        match = next((s for s in subs if s.get("index") == subtitle), None)
        if match is not None and is_image_subtitle(match.get("codec")):
            burn_idx = subtitle
    elif subtitle == "burn":
        first_image = next((s for s in subs if is_image_subtitle(s.get("codec"))), None)
        if first_image is not None:
            burn_idx = first_image.get("index")

    if quality and quality in QUALITY_HEIGHTS:
        h = QUALITY_HEIGHTS[quality]
        if not source_height or h < source_height:
            max_h = h

    return TrackOpts(audio_index=audio_idx, burn_sub_index=burn_idx, max_height=max_h)
