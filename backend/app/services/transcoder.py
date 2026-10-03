"""HLS transcoder session manager.

Spawns an ffmpeg subprocess per active (user, media_file, variant) and keeps
it alive while the client is fetching segments. Idle sessions are killed by
the janitor after TRANSCODE_IDLE_TIMEOUT_SEC seconds of no segment reads.

Cache layout on disk:
    {transcode_cache_dir}\{media_file_id}\{variant}\t{offset_bucket}\
        index.m3u8
        seg_00000.ts
        seg_00001.ts
        ...

The `t{offset_bucket}` layer always exists, even for the common case of
starting at the beginning (`t0`). Keeping the structure uniform avoids
branching in the cache walker and LRU evictor.

All state lives in-process. The Stream Gateway must therefore run as a
single uvicorn worker so the session registry is consistent across
requests. See install-services.ps1.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings
from app.db import db_session
from app.models.transcode import TranscodeSession
from app.services.playback import VARIANT_LADDER, Variant
from app.services.track_opts import TrackOpts, parse_token


log = logging.getLogger("f7five0.transcoder")


IDLE_TIMEOUT_SEC = 600          # kill session after 600s with no segment reads
JANITOR_INTERVAL_SEC = 30       # how often the background sweeper runs
START_WAIT_SEC = 10             # how long to wait for the first segment on a cold start


# ---------------------------------------------------------------------------
# Variant lookup
# ---------------------------------------------------------------------------
def variant_by_label(label: str) -> Optional[Variant]:
    for v in VARIANT_LADDER:
        if v.label == label:
            return v
    return None


def out_dir_for(
    media_file_id: uuid.UUID, variant_label: str, offset_bucket: int = 0,
    opts: str = "",
) -> Path:
    """Deterministic cache directory for a (media_file, variant, bucket).

    Mirrors the layout `_start` builds (see the module docstring). Exposed so
    the segment handler can locate a cache dir and serve already-complete
    segments straight from disk without holding or spawning a job.

    A non-empty track-options token (`opts`, see services/track_opts.py) gets
    its own variant directory (`high_a2-q720`) so a different audio track,
    burned subtitle or quality ceiling never reuses another pick's segments,
    while the cache janitor's `{mid}/{variant}/t{bucket}` walk (and the
    transcode_cache unique key) keep working unchanged.
    """
    return (
        Path(settings.transcode_cache_dir)
        / str(media_file_id)
        / (f"{variant_label}_{opts}" if opts else variant_label)
        / f"t{offset_bucket}"
    )


# ---------------------------------------------------------------------------
# ffmpeg invocation
# ---------------------------------------------------------------------------
def _build_ffmpeg_args(
    source: Path,
    variant: Variant,
    out_dir: Path,
    nvenc: bool,
    offset_bucket: int = 0,
    start_number: int = 0,
    playlist_name: str = "index.m3u8",
    opts: Optional[TrackOpts] = None,
) -> list[str]:
    """Produce the argv for an on-demand HLS transcode.

    Mirrors the template in f7five0-architecture.md. Uses NVENC when
    `nvenc=True`, falls back to libx264 otherwise. Single-variant HLS; the
    master playlist is generated outside ffmpeg.

    `start_number` numbers the first emitted segment (`seg_%05d.ts`). A
    resume-aware re-spawn passes the index of the segment it must produce so
    already-written earlier segments survive on disk. `playlist_name` lets a
    re-spawn write its muxer index to a side file (`index.part.m3u8`) so the
    canonical `index.m3u8` from the original session is not clobbered. Both
    default to the cold-start values so bucket=0 argv stays bit-identical.

    When `offset_bucket > 0`:
      - `-ss <bucket>` is passed as an **input** option (fast seek to the
        nearest preceding keyframe; may drift up to ~2s before the
        requested point, acceptable for resume UX).
      - Segments come out with PTS starting at 0 representing source
        content starting at `bucket`. The player sees a stream of
        `duration - bucket` length; the UI seeks client-side to land
        the timer on the real source offset. Muxer-side PTS rewriting
        via `-output_ts_offset` used to live here, but hls.js
        normalizes the first loaded segment's PTS to 0 regardless, so
        the flag was a no-op in the browser and only broke the timer
        read on resume. See [[hls-resume-timer-fix]].

    Bucket=0 keeps argv bit-identical to the pre-resume version so the
    default path is unchanged.
    """
    index_path = out_dir / playlist_name
    seg_pattern = out_dir / "seg_%05d.ts"

    args: list[str] = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "warning",
        "-y",
    ]
    opts = opts or TrackOpts()
    burn = opts.burn_sub_index is not None
    if nvenc and not burn:
        args += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]

    if offset_bucket > 0:
        # Input-side seek: demuxer jumps to the nearest preceding keyframe
        # and starts decoding from there. Much cheaper than output-side
        # seek (which would decode and discard the skipped portion).
        args += ["-ss", str(offset_bucket)]

    args += ["-i", str(source)]

    # Track selection (spec section I). With no options, ffmpeg's default
    # stream selection is used and argv stays bit-identical to before.
    if burn:
        # Image subtitle (PGS/VobSub/DVB) burned into the picture: overlay the
        # subtitle stream on the first video stream on the CPU, then scale.
        args += [
            "-filter_complex",
            f"[0:v:0][0:{opts.burn_sub_index}]overlay,scale=-2:{variant.height}[vout]",
            "-map", "[vout]",
        ]
    elif not opts.empty:
        args += ["-map", "0:v:0"]
    if not opts.empty:
        args += ["-map", f"0:{opts.audio_index}" if opts.audio_index is not None else "0:a:0?"]
        args += ["-sn"]

    # Video encoder
    if nvenc:
        args += [
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", "23",
            "-b:v", f"{variant.video_bitrate_kbps}k",
            "-maxrate", f"{variant.max_bitrate_kbps}k",
            "-bufsize", f"{variant.bufsize_kbps}k",
        ]
        if not burn:
            args += ["-vf", f"scale_cuda=-2:{variant.height}"]
        args += [
            "-bf", "0",
            "-forced-idr", "1",
            "-force_key_frames", "expr:gte(t,n_forced*6)",
        ]
    else:
        args += [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-maxrate", f"{variant.max_bitrate_kbps}k",
            "-bufsize", f"{variant.bufsize_kbps}k",
        ]
        if not burn:
            args += ["-vf", f"scale=-2:{variant.height}"]
        args += [
            "-force_key_frames", "expr:gte(t,n_forced*6)",
        ]

    # Audio encoder: always AAC stereo
    args += [
        "-c:a", "aac",
        "-b:a", f"{variant.audio_bitrate_kbps}k",
        "-ac", "2",
    ]

    # HLS muxer
    args += [
        "-f", "hls",
        "-hls_time", "6",
        "-hls_list_size", "0",
        "-hls_playlist_type", "event",
        "-hls_flags", "independent_segments",
    ]
    # Only emit -start_number for a resume-aware re-spawn. Leaving it off for
    # the common cold start keeps the bucket=0 argv bit-identical to before.
    if start_number > 0:
        args += ["-start_number", str(start_number)]
    args += [
        "-hls_segment_filename", str(seg_pattern),
        str(index_path),
    ]
    return args


# ---------------------------------------------------------------------------
# Session objects
# ---------------------------------------------------------------------------
@dataclass
class TranscodeJob:
    """One ffmpeg process, one cache dir, one key.

    The `offset_bucket` (seconds) is part of the key so a single user
    can have two simultaneous ffmpeg sessions against the same media
    file + variant — one started from the beginning, one resumed
    mid-file. The common case is bucket=0.
    """

    user_id: uuid.UUID
    media_file_id: uuid.UUID
    variant: Variant
    source_path: Path
    out_dir: Path
    proc: subprocess.Popen
    offset_bucket: int = 0
    opts: str = ""
    started_at: float = field(default_factory=time.time)
    last_access_at: float = field(default_factory=time.time)
    session_row_id: Optional[uuid.UUID] = None

    @property
    def key(self) -> tuple[uuid.UUID, uuid.UUID, str, int, str]:
        return (self.user_id, self.media_file_id, self.variant.label, self.offset_bucket, self.opts)

    @property
    def index_path(self) -> Path:
        return self.out_dir / "index.m3u8"

    def is_running(self) -> bool:
        return self.proc.poll() is None

    def returncode(self) -> Optional[int]:
        return self.proc.returncode

    def touch(self) -> None:
        self.last_access_at = time.time()

    def kill(self) -> None:
        if self.is_running():
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
            except Exception:
                log.exception("error killing ffmpeg for %s", self.key)


def _opts_without_quality(opts: str) -> str:
    """The track-options token minus its quality ceiling. On CPU-only servers
    a quality change arrives as a new stream with a different `q`, so sibling
    matching must ignore it (audio and subtitle picks still have to match)."""
    try:
        o = parse_token(opts)
    except Exception:
        return opts
    return TrackOpts(audio_index=o.audio_index, burn_sub_index=o.burn_sub_index).to_token()


class TranscodeManager:
    """Thread-safe registry of active jobs.

    Keyed by (user_id, media_file_id, variant_label, offset_bucket). Each
    key has at most one job. Starting the same key twice returns the
    existing job. bucket=0 is the default (playback from the start); a
    positive bucket indicates resume-from-offset.
    """

    def __init__(self) -> None:
        self._jobs: dict[tuple[uuid.UUID, uuid.UUID, str, int, str], TranscodeJob] = {}
        self._lock = threading.RLock()
        self._janitor_stop = threading.Event()
        self._janitor: Optional[threading.Thread] = None

    # -- lifecycle ---------------------------------------------------------
    def start_janitor(self) -> None:
        with self._lock:
            if self._janitor is not None:
                return
            t = threading.Thread(target=self._janitor_loop, name="transcode-janitor", daemon=True)
            self._janitor = t
            t.start()

    def stop(self) -> None:
        self._janitor_stop.set()
        with self._lock:
            jobs = list(self._jobs.values())
            self._jobs.clear()
        for j in jobs:
            j.kill()
            _close_session_row(j.session_row_id)

    # -- entry points ------------------------------------------------------
    def get_or_start(
        self,
        user_id: uuid.UUID,
        media_file_id: uuid.UUID,
        variant: Variant,
        source_path: Path,
        offset_bucket: int = 0,
        opts: str = "",
    ) -> TranscodeJob:
        key = (user_id, media_file_id, variant.label, offset_bucket, opts)
        with self._lock:
            existing = self._jobs.get(key)
            if existing is not None and existing.is_running():
                existing.touch()
                return existing
            if existing is not None:
                log.info("reaping dead ffmpeg for %s (rc=%s)", key, existing.returncode())
                self._jobs.pop(key, None)
                _close_session_row(existing.session_row_id)

            siblings = self._pop_running_siblings(key)
            job = self._start(user_id, media_file_id, variant, source_path, offset_bucket,
                              opts=opts)
            self._jobs[key] = job
        # Kill outside the lock: kill() can wait up to 10 s for ffmpeg to exit.
        for sib in siblings:
            log.info("stopping ffmpeg %s: same viewer switched to variant %s",
                     sib.key, variant.label)
            sib.kill()
            _close_session_row(sib.session_row_id)
        return job

    def _pop_running_siblings(
        self, key: tuple[uuid.UUID, uuid.UUID, str, int, str],
    ) -> list[TranscodeJob]:
        """Remove and return running jobs for the same viewer, file, offset
        bucket and audio/subtitle picks but a different variant or quality
        ceiling. Caller holds the lock.

        A player that changes quality (hls.js level switch, or a manual pick)
        starts a new variant; the old variant's ffmpeg would otherwise keep
        encoding until the idle janitor, competing for the CPU on installs
        without NVENC. Finished jobs stay registered so their cached segments
        keep serving.
        """
        user_id, media_file_id, label, bucket, opts = key
        base = _opts_without_quality(opts)
        out: list[TranscodeJob] = []
        for k, j in list(self._jobs.items()):
            if k == key or not j.is_running():
                continue
            if (k[0] == user_id and k[1] == media_file_id and k[3] == bucket
                    and _opts_without_quality(k[4]) == base
                    and (k[2] != label or k[4] != opts)):
                self._jobs.pop(k, None)
                out.append(j)
        return out

    def get(
        self,
        user_id: uuid.UUID,
        media_file_id: uuid.UUID,
        variant_label: str,
        offset_bucket: int = 0,
        opts: str = "",
    ) -> Optional[TranscodeJob]:
        with self._lock:
            job = self._jobs.get((user_id, media_file_id, variant_label, offset_bucket, opts))
            if job is None:
                return None
            if not job.is_running() and not job.index_path.exists():
                # Never produced output. Treat as gone.
                self._jobs.pop(job.key, None)
                _close_session_row(job.session_row_id)
                return None
            job.touch()
            return job

    def respawn_from_segment(
        self,
        user_id: uuid.UUID,
        media_file_id: uuid.UUID,
        variant: Variant,
        source_path: Path,
        *,
        offset_bucket: int,
        start_number: int,
        seek_offset_sec: int,
        playlist_name: str,
        opts: str = "",
    ) -> TranscodeJob:
        """Resume-aware re-spawn for a mid-playback segment miss.

        Unlike `get_or_start`, this seeks ffmpeg to `seek_offset_sec` and
        numbers its output from `start_number` so already-complete earlier
        segments in the cache dir survive, and writes the muxer index to
        `playlist_name` (a side file) so the canonical `index.m3u8` is not
        clobbered. Registry key stays the original `offset_bucket`, so a
        later segment request finds this job. Idempotent under the lock.
        """
        key = (user_id, media_file_id, variant.label, offset_bucket, opts)
        with self._lock:
            existing = self._jobs.get(key)
            if existing is not None and existing.is_running():
                existing.touch()
                return existing
            if existing is not None:
                self._jobs.pop(key, None)
                _close_session_row(existing.session_row_id)
            job = self._start(
                user_id, media_file_id, variant, source_path, offset_bucket,
                start_number=start_number,
                seek_offset_sec=seek_offset_sec,
                playlist_name=playlist_name,
                wipe=False,
                opts=opts,
            )
            self._jobs[key] = job
            return job

    # -- internals ---------------------------------------------------------
    def _start(
        self,
        user_id: uuid.UUID,
        media_file_id: uuid.UUID,
        variant: Variant,
        source_path: Path,
        offset_bucket: int = 0,
        *,
        start_number: int = 0,
        seek_offset_sec: Optional[int] = None,
        playlist_name: str = "index.m3u8",
        wipe: bool = True,
        opts: str = "",
    ) -> TranscodeJob:
        out_dir = out_dir_for(media_file_id, variant.label, offset_bucket, opts)
        # Cold start wipes the dir: a stale partial transcode would confuse the
        # player's segment count. A resume-aware re-spawn keeps the dir so the
        # segments the fast path already serves from disk are not destroyed.
        if wipe and out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        # The seek fed to ffmpeg (-ss) is the resume point for a re-spawn
        # (bucket + N*6) or plain `offset_bucket` for a cold start.
        seek = seek_offset_sec if seek_offset_sec is not None else offset_bucket
        args = _build_ffmpeg_args(
            source_path, variant, out_dir, settings.nvenc_enabled,
            offset_bucket=seek,
            start_number=start_number,
            playlist_name=playlist_name,
            opts=parse_token(opts),
        )
        log.info(
            "spawning ffmpeg uid=%s mid=%s variant=%s bucket=%s opts=%s out=%s",
            user_id, media_file_id, variant.label, offset_bucket, opts or "-", out_dir,
        )
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=str(out_dir),
        )
        job = TranscodeJob(
            user_id=user_id,
            media_file_id=media_file_id,
            variant=variant,
            source_path=source_path,
            out_dir=out_dir,
            proc=proc,
            offset_bucket=offset_bucket,
            opts=opts,
        )
        job.session_row_id = _open_session_row(
            user_id, media_file_id, variant.label, offset_bucket,
        )

        # Drain stderr in a daemon thread so ffmpeg doesn't block on a full
        # pipe buffer. Warnings land in the Stream service log.
        threading.Thread(
            target=_drain_stderr,
            args=(proc, job.key),
            name=f"ffmpeg-stderr-{media_file_id}",
            daemon=True,
        ).start()
        return job

    def _janitor_loop(self) -> None:
        log.info("transcode janitor started (idle=%ss interval=%ss)",
                 IDLE_TIMEOUT_SEC, JANITOR_INTERVAL_SEC)
        while not self._janitor_stop.wait(JANITOR_INTERVAL_SEC):
            self._sweep()
        log.info("transcode janitor stopped")

    def _sweep(self) -> None:
        now = time.time()
        to_kill: list[TranscodeJob] = []
        to_close: list[Optional[uuid.UUID]] = []
        with self._lock:
            for key, job in list(self._jobs.items()):
                # Dead process: drop from registry but leave cache dir for LRU.
                if not job.is_running():
                    log.info("reaping finished ffmpeg %s (rc=%s)", key, job.returncode())
                    self._jobs.pop(key, None)
                    to_close.append(job.session_row_id)
                    continue
                if (now - job.last_access_at) > IDLE_TIMEOUT_SEC:
                    to_kill.append(job)
                    self._jobs.pop(key, None)
        for job in to_kill:
            log.info("idle-killing ffmpeg %s (idle=%ss)",
                     job.key, int(now - job.last_access_at))
            job.kill()
            to_close.append(job.session_row_id)
        for sid in to_close:
            _close_session_row(sid)


# ---------------------------------------------------------------------------
# Session-row helpers
#
# A TranscodeSession row mirrors one TranscodeJob: written when ffmpeg
# spawns, closed when the process is reaped or idle-killed. DB failures are
# logged and swallowed so a transient outage never breaks playback.
# ---------------------------------------------------------------------------
def _open_session_row(
    user_id: uuid.UUID, media_file_id: uuid.UUID, variant_label: str,
    offset_bucket: int = 0,
) -> Optional[uuid.UUID]:
    try:
        with db_session() as db:
            row = TranscodeSession(
                user_id=user_id,
                media_file_id=media_file_id,
                variant=variant_label,
                offset_bucket=offset_bucket,
                direct_play=False,
                started_at=datetime.now(timezone.utc),
            )
            db.add(row)
            db.flush()
            return row.id
    except Exception:
        log.exception("failed to open transcode_sessions row for %s/%s/%s/t%s",
                      user_id, media_file_id, variant_label, offset_bucket)
        return None


def _close_session_row(row_id: Optional[uuid.UUID]) -> None:
    if row_id is None:
        return
    try:
        with db_session() as db:
            row = db.get(TranscodeSession, row_id)
            if row is None:
                return
            if row.ended_at is None:
                row.ended_at = datetime.now(timezone.utc)
    except Exception:
        log.exception("failed to close transcode_sessions row %s", row_id)


def _drain_stderr(proc: subprocess.Popen, key: tuple) -> None:
    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                log.warning("ffmpeg[%s]: %s", key, text)
    except Exception:
        log.exception("error draining ffmpeg stderr for %s", key)


# ---------------------------------------------------------------------------
# Module-level singleton.
# The Stream Gateway instantiates one and reuses it across requests.
# ---------------------------------------------------------------------------
manager = TranscodeManager()


# ---------------------------------------------------------------------------
# Master playlist generation
# ---------------------------------------------------------------------------
def build_master_playlist(media_file_id: uuid.UUID, variants: tuple[Variant, ...],
                          signed_query: str) -> str:
    """Write a master m3u8 pointing at each variant's playlist.

    Each `URI` line is absolute-path relative and includes the signed query
    string so hls.js (and VLC) forward the params on sub-fetches. Using full
    querystring per URI keeps signature validation trivial: every request
    carries uid/exp/sig and the gateway recomputes the HMAC.
    """
    lines: list[str] = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for v in variants:
        # Bandwidth is bits/sec per the HLS spec. Video + audio, padded 10%.
        total_kbps = int((v.video_bitrate_kbps + v.audio_bitrate_kbps) * 1.1)
        lines.append(
            f"#EXT-X-STREAM-INF:BANDWIDTH={total_kbps * 1000},"
            f"RESOLUTION={int(v.height * 16 / 9)}x{v.height},"
            f"CODECS=\"avc1.4d401f,mp4a.40.2\""
        )
        lines.append(f"/stream/hls/{media_file_id}/{v.label}/index.m3u8?{signed_query}")
    return "\n".join(lines) + "\n"


HLS_SEG_DURATION = 6.0  # matches `-hls_time 6` in _build_ffmpeg_args


# ---------------------------------------------------------------------------
# Offline download transcode (Phase 2) - STUBBED
# ---------------------------------------------------------------------------
# The offline-download route (app/api/media_files.py) offers a server-side MP4
# (H.264/AAC) rendition for video that cannot direct-play. That is a full-file
# ffmpeg pass, so it is gated behind `settings.download_transcode_enabled` and
# the actual invocation below is intentionally a stub: it describes the argv
# it would run and raises NotImplementedError so the route falls through to its
# documented 409 not_available_offline path. Wiring, signing, quality
# validation, and the 409 path are all real; only the encode is deferred so we
# never spawn an unbounded job against the real library during Phase 2.
_DOWNLOAD_HEIGHTS = {"1080p": 1080, "720p": 720, "480p": 480, "original": 0}


def build_download_transcode_args(source: Path, dest: Path, quality: str) -> list[str]:
    """Describe the ffmpeg argv for a download MP4 (H.264/AAC, faststart).

    Pure arg-builder (no process spawn) so it can be unit-tested and reviewed.
    `quality` is one of original|1080p|720p|480p; a height of 0 keeps source
    resolution. Uses NVENC when enabled, libx264 otherwise, mirroring the HLS
    encoder settings. `-movflags +faststart` puts the moov atom up front so the
    file streams / seeks well as a progressive download.
    """
    height = _DOWNLOAD_HEIGHTS.get(quality, 0)
    args: list[str] = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "warning",
        "-y",
        "-i", str(source),
    ]
    if settings.nvenc_enabled:
        args += ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23"]
        if height > 0:
            args += ["-vf", f"scale=-2:{height}"]
    else:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
        if height > 0:
            args += ["-vf", f"scale=-2:{height}"]
    args += [
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(dest),
    ]
    return args


def build_download_mp4(media_file, quality: str) -> str:
    """Produce (or locate) a download MP4 for `media_file` at `quality`.

    STUB: raises NotImplementedError so the download route returns its
    documented 409 not_available_offline. When implemented this would run
    `build_download_transcode_args` into a cache path, wait for completion (or
    return a ready cached rendition), and return the on-disk MP4 path.
    """
    raise NotImplementedError("download MP4 transcode is not implemented in Phase 2")


def rewrite_variant_playlist(body: str, media_file_id: uuid.UUID, variant_label: str,
                             signed_query: str, *, duration_sec: float = 0.0) -> str:
    """Synthesize a complete VOD variant playlist for an ongoing transcode.

    ffmpeg writes its own index as `EXT-X-PLAYLIST-TYPE:EVENT` with no
    `EXT-X-ENDLIST` until the encode finishes. Google Cast's Default Media
    Receiver treats EVENT-without-ENDLIST as a live stream and snaps
    playback to the live edge (the most recently produced segment), which
    is why casting from Chrome on Android starts the movie at "1 to 2
    minutes in" and creeps further on each replay.

    To present a deterministic VOD timeline to any compliant HLS player
    (cast receivers, native HLS, hls.js), we ignore ffmpeg's body and
    emit the full segment list up-front, capped with `EXT-X-ENDLIST`.
    Segments that ffmpeg has not produced yet are served by the segment
    endpoint, which already blocks (with timeout) until the file appears
    on disk. ffmpeg encodes faster than realtime under NVENC, so for
    sequential playback the encoder stays ahead of the receiver.

    `duration_sec` is the duration of the **encoded output**: for an
    `offset_bucket > 0` resume that is `media_file.duration_sec -
    offset_bucket`; for the bucket=0 case it equals the source duration.
    Segments are nominally `HLS_SEG_DURATION` seconds each; the final
    segment carries the remainder so the playlist's summed EXTINF
    matches `duration_sec`.

    `body` is unused by the synthesis path but retained so the call site
    can keep its existing cold-start wait against `index_path` as a
    "ffmpeg actually launched" check. If `duration_sec` is missing (no
    duration on the MediaFile row, or a negative result from a too-large
    offset_bucket), fall back to the legacy passthrough so hls.js still
    works.
    """
    if duration_sec <= 0.0:
        out: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and stripped.endswith(".ts"):
                out.append(
                    f"/stream/hls/{media_file_id}/{variant_label}/{stripped}?{signed_query}"
                )
            else:
                out.append(line)
        tail = "\n" if body.endswith("\n") else ""
        return "\n".join(out) + tail

    seg_len = HLS_SEG_DURATION
    full_seg_count = int(duration_sec // seg_len)
    remainder = duration_sec - full_seg_count * seg_len
    # Treat near-exact multiples as no partial segment; receivers tolerate
    # tiny rounding either way but skipping a 0.000s EXTINF avoids a stray
    # zero-duration tail.
    if remainder < 0.05:
        last_seg_len = 0.0
    else:
        last_seg_len = remainder

    lines: list[str] = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{int(seg_len)}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-INDEPENDENT-SEGMENTS",
    ]
    for i in range(full_seg_count):
        lines.append(f"#EXTINF:{seg_len:.3f},")
        lines.append(
            f"/stream/hls/{media_file_id}/{variant_label}/seg_{i:05d}.ts?{signed_query}"
        )
    if last_seg_len > 0.0:
        lines.append(f"#EXTINF:{last_seg_len:.3f},")
        lines.append(
            f"/stream/hls/{media_file_id}/{variant_label}/seg_{full_seg_count:05d}.ts?{signed_query}"
        )
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"
