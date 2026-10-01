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

"use client";

import { useEffect, useRef, useState } from "react";
import { formatDuration } from "@/lib/format";

type Props = {
  // The live <video>, or null before <Player> mounts it / after it unmounts.
  videoEl: HTMLVideoElement | null;
  // Total duration hint from the stream metadata. The element's own
  // durationchange refines this once media loads.
  durationSec?: number;
};

export function VideoTransport({ videoEl, durationSec }: Props) {
  const barRef = useRef<HTMLDivElement | null>(null);
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
    const onTime = () => setCurrentTime(v.currentTime || 0);
    const onVol = () => {
      setVolume(v.volume);
      setMuted(v.muted);
    };
    const onDur = () => {
      if (!isNaN(v.duration) && v.duration > 0) setDuration(v.duration);
    };

    setIsPlaying(!v.paused);
    setCurrentTime(v.currentTime || 0);
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
  }, [videoEl]);

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

  const effectiveDuration =
    duration > 0 ? duration : durationSec && durationSec > 0 ? durationSec : 0;
  const pct =
    effectiveDuration > 0 ? Math.min(100, (currentTime / effectiveDuration) * 100) : 0;

  const togglePlay = () => {
    const v = videoEl;
    if (!v) return;
    if (v.paused) {
      const p = v.play();
      if (p && typeof p.catch === "function") p.catch(() => { /* ignore */ });
    } else {
      v.pause();
    }
  };

  // Scrub. Derive a 0..1 ratio from where the pointer landed on the bar and
  // assign video.currentTime. Tracking pointermove while down gives
  // click-and-drag seeking. Mirrors MiniPlayer.
  const seekToClientX = (clientX: number) => {
    const bar = barRef.current;
    const v = videoEl;
    if (!bar || !v || !effectiveDuration || effectiveDuration <= 0) return;
    const rect = bar.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const t = ratio * effectiveDuration;
    try {
      v.currentTime = t;
    } catch {
      // ignore
    }
    setCurrentTime(t);
  };
  const onScrubPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    seekToClientX(e.clientX);
    const onMove = (ev: PointerEvent) => seekToClientX(ev.clientX);
    const onUp = () => {
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
  return (
    <svg viewBox="0 0 24 24" width="30" height="30" fill="currentColor" aria-hidden>
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="30" height="30" fill="currentColor" aria-hidden>
      <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
    </svg>
  );
}

function VolumeIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden>
      <path d="M3 10v4h4l5 5V5L7 10H3zm13.5 2a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4z" />
    </svg>
  );
}

function MuteIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden>
      <path d="M3 10v4h4l5 5V5L7 10H3zm16.5 2 2.3-2.3-1.4-1.4-2.3 2.3-2.3-2.3-1.4 1.4 2.3 2.3-2.3 2.3 1.4 1.4 2.3-2.3 2.3 2.3 1.4-1.4-2.3-2.3z" />
    </svg>
  );
}

function FullscreenIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4" />
    </svg>
  );
}

function FullscreenExitIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M9 4v4a1 1 0 0 1-1 1H4M15 4v4a1 1 0 0 0 1 1h4M9 20v-4a1 1 0 0 0-1-1H4M15 20v-4a1 1 0 0 1 1-1h4" />
    </svg>
  );
}
