// VideoTransport. The real custom control bar for the /watch video path.
//
// The old bottom bar was a decorative gradient strip pinned over the native
// control bar: it swallowed pointer events while its scrub div had no handler,
// so play, pause, volume and fullscreen were all unreachable. This drives the
// <video> element directly instead. The element is handed down from <Player>
// via its onVideoEl prop; this component owns no source attachment, only the
// transport.
//
// It renders into the existing .np .controls markup (.scrub + .keys) so the
// styling in globals.css applies, and the play button uses the .keys .k.play
// classes so that CSS is finally exercised. The pointer-drag seek mirrors the
// dock's MiniPlayer.seekToClientX / onScrubPointerDown shape verbatim so there
// is one seek pattern in the app, not two.
//
// Volume and mute persist to the same mh:volume / mh:muted localStorage keys
// the dock uses, so the device-local level is shared across audio and video.
//
// Resumed transcodes: an HLS stream started with resume_sec is encoded from
// `offsetSec` into the file, so the element's clock reads 0 there and its
// duration is only what remains. The transport shows source time (element
// time + offsetSec) against the full `durationSec`, and a seek to before the
// offset is handed to `onSeekBeforeStart`, which re-requests the stream from
// that point (the element has nothing earlier to seek to).

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { formatDuration } from "@/lib/format";
import { Icon } from "@/components/Icon";
import { Play, Pause, Volume2, VolumeX, Maximize, Minimize } from "lucide-react";
import { videoElementController } from "@/lib/playerController";
import type { PlayerController } from "@/lib/playerController";

type Props = {
  // The live <video>, or null before <Player> mounts it / after it unmounts.
  videoEl: HTMLVideoElement | null;
  // Total duration hint from the stream metadata. The element's own
  // durationchange refines this once media loads (except on a resumed
  // transcode, where the element only knows the remaining part).
  durationSec?: number;
  // Source seconds at which the stream's own timeline starts (stream/start's
  // offset_sec for a resumed HLS stream; 0 otherwise).
  offsetSec?: number;
  // Seek to a source time before offsetSec: the page restarts the stream there.
  onSeekBeforeStart?: (sourceSec: number) => void;
};

export function VideoTransport({ videoEl, durationSec, offsetSec = 0, onSeekBeforeStart }: Props) {
  const offset = offsetSec > 0 ? offsetSec : 0;
  const barRef = useRef<HTMLDivElement | null>(null);
  // Uniform player controller (item 8c). The transport drives the <video>
  // through this so a future watch-together room can command playback the same
  // way regardless of which player is mounted. offset is captured via a ref so
  // the controller always maps element time to source time correctly.
  const videoElRef = useRef<HTMLVideoElement | null>(videoEl);
  videoElRef.current = videoEl;
  const offsetRef = useRef(offset);
  offsetRef.current = offset;
  const controllerRef = useRef<ReturnType<typeof videoElementController> | null>(null);
  const controller: PlayerController = useMemo(() => {
    const c = videoElementController(
      () => videoElRef.current,
      () => offsetRef.current,
    );
    controllerRef.current = c;
    return c;
  }, []);
  useEffect(() => () => controllerRef.current?.dispose(), []);
  // True while the scrub handle is held; timeupdate then leaves the readout
  // alone so it shows where the pointer is.
  const draggingRef = useRef(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(durationSec && durationSec > 0 ? durationSec : 0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Restore device-local volume + mute on mount, matching the dock's keys.
  useEffect(() => {
    try {
      const v = localStorage.getItem("mh:volume");
      if (v !== null) {
        const n = parseFloat(v);
        if (!isNaN(n)) setVolume(Math.max(0, Math.min(1, n)));
      }
      const m = localStorage.getItem("mh:muted");
      if (m !== null) setMuted(m === "1" || m === "true");
    } catch {
      // private mode / disabled storage: keep defaults
    }
  }, []);

  // Track the element. Prime from its current state (it may already be playing
  // by the time this mounts) then follow play / pause / timeupdate /
  // volumechange / durationchange. Re-subscribes when the element identity
  // changes (mount / unmount).
  useEffect(() => {
    const v = videoEl;
    if (!v) return;
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onTime = () => {
      if (draggingRef.current) return;
      setCurrentTime(offset + (v.currentTime || 0));
    };
    const onVol = () => {
      setVolume(v.volume);
      setMuted(v.muted);
    };
    const onDur = () => {
      if (!isNaN(v.duration) && v.duration > 0) setDuration(v.duration);
    };

    setIsPlaying(!v.paused);
    setCurrentTime(offset + (v.currentTime || 0));
    if (!isNaN(v.duration) && v.duration > 0) setDuration(v.duration);

    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("volumechange", onVol);
    v.addEventListener("durationchange", onDur);
    return () => {
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("volumechange", onVol);
      v.removeEventListener("durationchange", onDur);
    };
  }, [videoEl, offset]);

  // Apply the persisted / adjusted level to the element.
  useEffect(() => {
    if (!videoEl) return;
    videoEl.volume = volume;
    videoEl.muted = muted;
  }, [videoEl, volume, muted]);

  // Fullscreen tracks the document so the button label stays correct even when
  // the user exits with Escape or the browser chrome.
  useEffect(() => {
    const onFsChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  // On a resumed transcode the element's duration covers only the remainder,
  // so the stream metadata's full duration wins.
  const effectiveDuration =
    offset > 0 && durationSec && durationSec > 0
      ? durationSec
      : duration > 0
        ? duration
        : durationSec && durationSec > 0
          ? durationSec
          : 0;
  const pct =
    effectiveDuration > 0 ? Math.min(100, (currentTime / effectiveDuration) * 100) : 0;

  const togglePlay = () => {
    const v = videoEl;
    if (!v) return;
    // Drive through the controller (item 8c). Same effect as calling the
    // element directly; routing it here means one code path a room can reuse.
    if (v.paused) {
      controller.play();
    } else {
      controller.pause();
    }
  };

  // Scrub. Derive a 0..1 ratio from where the pointer landed on the bar and
  // assign video.currentTime. Tracking pointermove while down gives
  // click-and-drag seeking. Mirrors MiniPlayer. Positions are source time;
  // a point before a resumed stream's start only previews while dragging and
  // restarts the stream on release.
  const sourceTimeAt = (clientX: number): number | null => {
    const bar = barRef.current;
    if (!bar || !effectiveDuration || effectiveDuration <= 0) return null;
    const rect = bar.getBoundingClientRect();
    if (rect.width <= 0) return null;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return ratio * effectiveDuration;
  };
  const seekToClientX = (clientX: number, release: boolean) => {
    const v = videoEl;
    const t = sourceTimeAt(clientX);
    if (!v || t == null) return;
    setCurrentTime(t);
    if (t < offset) {
      if (release && onSeekBeforeStart) onSeekBeforeStart(Math.floor(t));
      return;
    }
    // Controller.seek takes an absolute SOURCE second and maps it to element
    // time internally (item 8c). Same as the prior `v.currentTime = t - offset`.
    controller.seek(t);
  };
  const onScrubPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    draggingRef.current = true;
    seekToClientX(e.clientX, false);
    let lastX = e.clientX;
    const onMove = (ev: PointerEvent) => {
      lastX = ev.clientX;
      seekToClientX(ev.clientX, false);
    };
    const onUp = (ev: PointerEvent) => {
      draggingRef.current = false;
      seekToClientX(ev.clientX ?? lastX, true);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const onVolumeChange = (val: number) => {
    const clamped = Math.max(0, Math.min(1, val));
    setVolume(clamped);
    try {
      localStorage.setItem("mh:volume", String(clamped));
    } catch {
      // ignore
    }
    // Nudging the slider above zero implicitly unmutes.
    if (clamped > 0 && muted) {
      setMuted(false);
      try {
        localStorage.setItem("mh:muted", "0");
      } catch {
        // ignore
      }
    }
  };
  const toggleMute = () => {
    setMuted((m) => {
      const nextMuted = !m;
      try {
        localStorage.setItem("mh:muted", nextMuted ? "1" : "0");
      } catch {
        // ignore
      }
      return nextMuted;
    });
  };

  // Fullscreen the .np container (not the bare <video>) so the custom
  // transport stays on screen in fullscreen. Falls back to the element if the
  // container isn't found.
  const toggleFullscreen = () => {
    const target =
      (videoEl?.closest(".np") as HTMLElement | null) ?? videoEl ?? null;
    try {
      if (!document.fullscreenElement) {
        void target?.requestFullscreen?.().catch(() => { /* ignore */ });
      } else {
        void document.exitFullscreen?.().catch(() => { /* ignore */ });
      }
    } catch {
      // ignore
    }
  };

  return (
    <>
      <div className="scrub">
        <span className="time">{formatDuration(currentTime)}</span>
        <div
          className="bar"
          ref={barRef}
          role="slider"
          tabIndex={0}
          aria-label="Seek"
          aria-valuemin={0}
          aria-valuemax={effectiveDuration > 0 ? Math.floor(effectiveDuration) : 0}
          aria-valuenow={Math.floor(currentTime)}
          onPointerDown={onScrubPointerDown}
        >
          <div className="fill" style={{ width: `${pct}%` }} />
        </div>
        <span className="time">
          {effectiveDuration > 0 ? formatDuration(effectiveDuration) : "—"}
        </span>
      </div>
      <div className="keys">
        <button
          type="button"
          className="k"
          onClick={toggleMute}
          aria-label={muted ? "Unmute" : "Mute"}
          aria-pressed={muted}
        >
          {muted || volume === 0 ? <MuteIcon /> : <VolumeIcon />}
        </button>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={muted ? 0 : volume}
          onChange={(e) => onVolumeChange(parseFloat(e.target.value))}
          aria-label="Volume"
          className="vol-slider"
        />
        <button
          type="button"
          className="k play"
          onClick={togglePlay}
          aria-label={isPlaying ? "Pause" : "Play"}
        >
          {isPlaying ? <PauseIcon /> : <PlayIcon />}
        </button>
        <button
          type="button"
          className="k"
          onClick={toggleFullscreen}
          aria-label={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
        >
          {isFullscreen ? <FullscreenExitIcon /> : <FullscreenIcon />}
        </button>
      </div>
    </>
  );
}

function PlayIcon() {
  return <Icon icon={Play} size={30} fill aria-hidden="true" />;
}

function PauseIcon() {
  return <Icon icon={Pause} size={30} fill aria-hidden="true" />;
}

function VolumeIcon() {
  return <Icon icon={Volume2} size={22} aria-hidden="true" />;
}

function MuteIcon() {
  return <Icon icon={VolumeX} size={22} aria-hidden="true" />;
}

function FullscreenIcon() {
  return <Icon icon={Maximize} size={22} aria-hidden="true" />;
}

function FullscreenExitIcon() {
  return <Icon icon={Minimize} size={22} aria-hidden="true" />;
}
