// Player. Takes a StreamStart response and renders a <video> tag with the
// right source attachment strategy:
//
//   - mode === "direct": set video.src to the signed MP4 URL. Browsers
//     handle byte-range seeking natively.
//   - mode === "hls": if the browser supports HLS natively
//     (Safari / iOS), set video.src to the master playlist directly. The
//     Stream Gateway rewrites child playlists and segment URLs to keep
//     the signed query on every sub-fetch.
//   - mode === "hls" without native support: dynamically import hls.js
//     and attach via MediaSource. hls.js will forward the signed query
//     itself because the manifest rewrites carry it per-URI.
//
// Playback errors bubble up to onError so the page can show something.
//
// Resume: the page decides whether to resume. If it passes an
// `initialResume` value we seek there once metadata is loaded (or
// immediately if metadata is already present). Passing nothing (or 0)
// starts from the beginning. Fetching the stored position and running
// the "Resume from X / Start over" prompt is the page's job; keeping it
// out of the Player means the Player never silently overrides a user
// choice.
//
// Progress: during playback we heartbeat to the backend every
// HEARTBEAT_MS. On unmount we flush one final write so we don't drop
// the last few seconds. When a cast session is active, the heartbeat
// uses the remote player's current time instead of the local video.
//
// Quality selector: on the MSE path we expose a gear menu overlaid on
// the player. The menu lists Auto + each level in the ladder (sorted
// high to low). Every level is its own ffmpeg on the server, so a level
// switch is a cold start. The player therefore starts PINNED to one level:
// the viewer's last pick on this browser, else the top of the ladder when
// the server has hardware encoding, else the highest level at or below
// 720p. hls.js ABR only runs when the viewer picks "Auto". Native HLS
// (Safari) and direct-play don't expose a level API, so the menu is
// hidden for those modes.
//
// Cast: when the Cast SDK is loaded and a session is active, the Player
// pauses local playback, sends the same signed stream URL to the
// receiver, and shows a "Casting to <device>" overlay. On session end
// it seeks the local video to the remote position and resumes. The
// launcher button lives in the overlay next to the gear icon. During
// a cast session the gear is hidden because hls.js is still attached
// locally but not playing.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type HlsType from "hls.js";
import type { Level } from "hls.js";
import { apiPut } from "@/lib/client-api";
import type { MediaMarker, Progress, StreamStart } from "@/lib/types";
import CastButton from "./CastButton";
import type { QualityControlData } from "./QualityMenu";
import { useCast } from "@/lib/cast";
import { Icon } from "@/components/Icon";
import { Cast } from "lucide-react";
import { loadFeatures, useFeatures } from "@/lib/features";
import {
  CPU_START_HEIGHT,
  pickStartLevel,
  readQualityPref,
  serverQualityHeights,
  writeQualityPref,
} from "@/lib/quality";

type Props = {
  stream: StreamStart;
  onError?: (message: string) => void;
  autoPlay?: boolean;
  initialResume?: number;
  // Optional absolute URL to the poster artwork for the Cast receiver.
  // Same-origin is fine; Cast devices on the local network reach the
  // tunnel-exposed origin just like the browser does.
  posterUrl?: string;
  // Detected intro/credits ranges. When currentTime falls inside one, a
  // Skip button appears that seeks to the marker end.
  markers?: MediaMarker[];
  // Hands the live <video> element to the parent (the watch page) so the
  // custom VideoTransport can drive it. Called with the element on mount and
  // null on unmount. Replaces the old document.querySelector(".np video") poll.
  onVideoEl?: (el: HTMLVideoElement | null) => void;
  // CPU-only servers send one rendition per stream, so quality changes go
  // back to the server: the page re-requests the stream at this height.
  serverQuality?: number | null;
  onServerQuality?: (height: number) => void;
  // The quality gear moved out of the Player overlay into the VideoTransport
  // controls row. Player still owns the level state, so it reports the gear
  // descriptor (or null when there's nothing to pick / while casting) up to the
  // watch page, which hands it to VideoTransport and also reads the playing
  // rendition height from it for the info line.
  onQualityControl?: (data: QualityControlData | null) => void;
};

const HEARTBEAT_MS = 10_000;


// Absolute-ize a same-origin path so the Cast receiver can fetch it. The
// BFF rewrites `/api/stream/start` responses to path-only URLs so they
// resolve under the tunnel in the browser; the Cast device on the LAN
// needs a scheme + host to dereference.
function toAbsolute(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  if (typeof window === "undefined") return url;
  if (url.startsWith("/")) return `${window.location.origin}${url}`;
  return `${window.location.origin}/${url}`;
}

function castContentTypeFor(mode: StreamStart["mode"]): string {
  return mode === "hls" ? "application/vnd.apple.mpegurl" : "video/mp4";
}

export function Player({
  stream,
  onError,
  autoPlay = true,
  initialResume,
  posterUrl,
  markers = [],
  onVideoEl,
  serverQuality,
  onServerQuality,
  onQualityControl,
}: Props) {
  const features = useFeatures();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const hlsRef = useRef<HlsType | null>(null);

  // Callback ref: keep the internal ref in sync and hand the element up to the
  // parent. Stable across renders (onVideoEl is a state setter on the page) so
  // React doesn't detach/reattach it every render.
  const setVideoNode = useCallback(
    (el: HTMLVideoElement | null) => {
      videoRef.current = el;
      onVideoEl?.(el);
    },
    [onVideoEl],
  );
  const [ready, setReady] = useState(false);
  // Playhead, sampled from the <video> timeupdate event, used only to decide
  // whether a skip-intro / skip-credits button should show.
  const [currentTime, setCurrentTime] = useState(0);

  // Quality selector state. `levels` is populated on MANIFEST_PARSED;
  // `loadedLevel` tracks whichever level ABR or the user settled on;
  // `userLevel` is -1 for Auto, else the explicit level index the user
  // pinned (so the UI can show Auto vs Pinned separately).
  const [levels, setLevels] = useState<Level[]>([]);
  const [loadedLevel, setLoadedLevel] = useState<number>(-1);
  const [userLevel, setUserLevel] = useState<number>(-1);

  // Cast bridge. useCast polls for SDK readiness internally so it's safe
  // to call unconditionally; when the SDK never loads, `status` stays
  // "unavailable" and the commands are no-ops.
  const cast = useCast();
  // Mirror the cast state into a ref so the heartbeat interval and the
  // unmount flush can read the latest values without being torn down
  // every time cast state changes.
  const castRef = useRef(cast);
  useEffect(() => {
    castRef.current = cast;
  }, [cast]);

  // Cast session transition handler. Fires on every cast.isConnected
  // flip and orchestrates the bridge between local and remote playback.
  const wasConnectedRef = useRef(false);
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const nowConnected = cast.isConnected;
    const wasConnected = wasConnectedRef.current;
    wasConnectedRef.current = nowConnected;

    if (nowConnected && !wasConnected) {
      // Starting to cast. Pause local playback at whatever position it's
      // at and hand the same signed URL to the receiver with startTime
      // set to the current local position. The HMAC already covers
      // `t=<bucket>` so we send exactly what the backend signed; the
      // receiver's `startTime` is a client-side seek, not a new signing.
      const startAt = isFinite(video.currentTime) && video.currentTime > 0
        ? video.currentTime
        : (initialResume ?? 0);
      try { video.pause(); } catch { /* ignore */ }

      const absoluteUrl = toAbsolute(stream.url);
      void cast
        .loadMedia({
          contentUrl: absoluteUrl,
          contentType: castContentTypeFor(stream.mode),
          title: stream.title ?? undefined,
          posterUrl: posterUrl,
          startTime: startAt > 0 ? startAt : undefined,
          durationSec: stream.duration_sec ?? undefined,
        })
        .catch((err: unknown) => {
          const message = err instanceof Error ? err.message : String(err);
          onError?.(`Cast failed: ${message}`);
          // Try to recover local playback so the user isn't stranded.
          try { void video.play(); } catch { /* ignore */ }
        });
    } else if (!nowConnected && wasConnected) {
      // Cast session ended. Seek local video to wherever the receiver
      // left off and resume. Browsers sometimes reject play() without a
      // user gesture if the tab was backgrounded; swallow the rejection
      // and let the user hit play manually if needed.
      const resumeAt = cast.currentTime;
      try {
        if (resumeAt > 0 && isFinite(video.duration) && video.duration > 0) {
          video.currentTime = resumeAt;
        }
      } catch { /* ignore */ }
      try {
        const p = video.play();
        if (p && typeof p.catch === "function") p.catch(() => { /* ignore */ });
      } catch { /* ignore */ }
    }
    // cast.currentTime is read only in the transition branch, but it's
    // most accurate on the tick the session actually ends, so we leave
    // it out of deps. The transition is driven by isConnected.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cast.isConnected, stream, onError, posterUrl, initialResume]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    let disposed = false;
    let heartbeat: number | null = null;
    // Where to seek to within the element once media is ready, in element
    // (stream) seconds. Direct play uses initialResume (a source second, since
    // its timeline == source). HLS resumed from a bucketed start seeks forward
    // by seek_within_sec so the viewer lands on the EXACT requested second
    // even though the encode began at the bucket boundary.
    const seekWithin =
      stream.mode === "hls" ? (stream.seek_within_sec ?? 0) : 0;
    let resumePos: number | null =
      stream.mode === "direct"
        ? initialResume != null && initialResume > 0
          ? initialResume
          : null
        : seekWithin > 0
          ? seekWithin
          : null;

    // Reset quality state on every new stream.
    setLevels([]);
    setLoadedLevel(-1);
    setUserLevel(-1);

    async function attach() {
      if (!video) return;

      if (stream.mode === "direct") {
        video.src = stream.url;
        setReady(true);
        return;
      }

      try {
        const [{ default: Hls }, features] = await Promise.all([
          import("hls.js"),
          loadFeatures(),
        ]);
        if (disposed) return;
        const hardware = Boolean(features.transcode?.hardware);
        // Prefer hls.js wherever MSE works. Native HLS players (Firefox and
        // Chrome on Android, Safari) switch levels on their own, and each
        // level is a separate ffmpeg on the server. Native is the fallback
        // for browsers without MSE (older iPhones).
        if (!Hls.isSupported()) {
          if (video.canPlayType("application/vnd.apple.mpegurl")) {
            video.src = stream.url;
            setReady(true);
            return;
          }
          onError?.("HLS playback is not supported in this browser.");
          return;
        }
        const instance = new Hls({
          // Reasonable defaults. F7FIVE0 segments are 6s and the Stream
          // Gateway caps concurrent transcodes, so a small buffer ahead
          // keeps memory modest.
          maxBufferLength: 30,
          // Drop what has already played. hls.js keeps the whole back buffer
          // by default (backBufferLength Infinity), so a long movie piled up
          // every played segment in the SourceBuffer until Chrome's own quota
          // kicked in: about 590 s of 1080p and 326 MB more browser memory
          // after 10 minutes on the dev PC.
          backBufferLength: 30,
          enableWorker: true,
          // Don't fetch a level playlist until we've pinned one: each level
          // request starts an ffmpeg on the server.
          autoStartLoad: false,
        });
        hlsRef.current = instance;
        instance.on(Hls.Events.MANIFEST_PARSED, (_event, data) => {
          if (disposed) return;
          // Copy so React treats it as a new array; hls.js mutates the
          // internal levels object over time.
          setLevels([...data.levels]);
          const start = pickStartLevel(
            data.levels.map((lv) => lv.height ?? 0),
            readQualityPref(),
            hardware,
          );
          if (start >= 0) {
            instance.startLevel = start;
            instance.loadLevel = start; // manual level: ABR stays off
          }
          setUserLevel(start);
          setLoadedLevel(start >= 0 ? start : instance.currentLevel);
          instance.startLoad();
        });
        instance.on(Hls.Events.LEVEL_SWITCHED, (_event, data) => {
          if (disposed) return;
          setLoadedLevel(data.level);
        });

        // Bounded fatal-error recovery. A single fatal error used to swap the
        // whole page for an ErrorBox, so any transient network blip or a
        // re-spawn gap killed playback permanently. Instead: retry network
        // errors with startLoad and backoff, recover media errors, and only
        // give up (destroy + onError) once a small budget is exhausted. A
        // healthy stretch (FRAG_BUFFERED) restores the budget so a later,
        // unrelated blip gets the full allowance again.
        const MAX_NET_RETRIES = 4;
        const MAX_MEDIA_RETRIES = 3;
        let netRetries = 0;
        let mediaRetries = 0;
        instance.on(Hls.Events.FRAG_BUFFERED, () => {
          netRetries = 0;
          mediaRetries = 0;
        });
        instance.on(Hls.Events.ERROR, (_event, data) => {
          if (disposed) return;
          if (!data.fatal) return;

          if (data.type === Hls.ErrorTypes.NETWORK_ERROR && netRetries < MAX_NET_RETRIES) {
            netRetries += 1;
            // Exponential-ish backoff capped at 2s. startLoad re-fetches the
            // manifest and segments; the keepalive ping keeps the encoder
            // alive underneath so the re-fetch finds fresh output.
            const delay = Math.min(2000, 250 * 2 ** (netRetries - 1));
            window.setTimeout(() => {
              if (disposed) return;
              try { instance.startLoad(); } catch { /* ignore */ }
            }, delay);
            return;
          }
          if (data.type === Hls.ErrorTypes.MEDIA_ERROR && mediaRetries < MAX_MEDIA_RETRIES) {
            mediaRetries += 1;
            try {
              // Second media-error attempt: swap the audio codec first, which
              // clears the class of media errors a plain recover can't.
              if (mediaRetries >= 2) instance.swapAudioCodec();
              instance.recoverMediaError();
            } catch { /* ignore */ }
            return;
          }

          // Unrecoverable type, or the retry budget is spent: tear down and
          // surface it so the page shows the error state.
          try { instance.destroy(); } catch { /* ignore */ }
          if (hlsRef.current === instance) hlsRef.current = null;
          onError?.(`Playback error: ${data.type}/${data.details}`);
        });
        instance.loadSource(stream.url);
        instance.attachMedia(video);
        setReady(true);
      } catch (err) {
        onError?.(err instanceof Error ? err.message : "Failed to load player");
      }
    }

    function trySeekNow() {
      if (!video || resumePos == null) return;
      if (!isNaN(video.duration) && video.duration > 0) {
        try { video.currentTime = resumePos; } catch { /* ignore */ }
        resumePos = null;
      }
    }

    function onLoadedMetadata() {
      trySeekNow();
    }

    // A resumed HLS stream's timeline starts at 0 at the encode start
    // (timeline_offset_sec, the bucket) into the source; convert element time
    // to source time for saved progress. Falls back to offset_sec for an older
    // backend without the timeline field.
    const base =
      stream.mode === "hls"
        ? (stream.timeline_offset_sec ?? stream.offset_sec ?? 0)
        : 0;

    function send(streamPosition: number, durationHint?: number | null) {
      // Fire-and-forget. If the write fails we'll catch up on the next tick.
      const position = base + streamPosition;
      const duration =
        base > 0 && stream.duration_sec
          ? Math.floor(stream.duration_sec)
          : durationHint != null && durationHint > 0
            ? Math.floor(durationHint)
            : video && !isNaN(video.duration) && video.duration > 0
              ? Math.floor(video.duration)
              : (stream.duration_sec ?? null);
      void apiPut<Progress>(
        `/api/library/progress/${stream.media_file_id}`,
        {
          position_sec: Math.floor(position),
          duration_sec: duration,
        },
      ).catch(() => { /* swallow */ });
    }

    function pingKeepAlive() {
      // Keep the transcode session alive while an HLS stream is mounted, even
      // while paused (a pause is exactly what used to trip the 90s idle kill).
      // The HMAC payload is uid:mid:exp:offset_bucket and does not cover the
      // path, so the keepalive URL is the signed stream URL with its pathname
      // swapped to the keepalive route. Direct-play has no session to keep.
      if (!(stream.mode === "hls")) return;
      if (typeof window === "undefined") return;
      try {
        const u = new URL(stream.url, window.location.origin);
        u.pathname = `/stream/keepalive/${stream.media_file_id}`;
        void fetch(u.toString(), { method: "GET", cache: "no-store" }).catch(() => { /* ignore */ });
      } catch {
        // ignore
      }
    }

    function tick() {
      pingKeepAlive();
      // When casting, the receiver is the source of truth for playhead.
      const c = castRef.current;
      if (c.isConnected) {
        if (c.currentTime > 0) {
          send(c.currentTime, c.duration > 0 ? c.duration : stream.duration_sec);
        }
        return;
      }
      if (!video) return;
      if (video.paused || video.ended) return;
      if (isNaN(video.currentTime)) return;
      send(video.currentTime);
    }

    video.addEventListener("loadedmetadata", onLoadedMetadata);
    attach();
    // If metadata was already loaded by the time this effect runs (rare but
    // possible on fast caches), seek immediately without waiting for the event.
    trySeekNow();
    heartbeat = window.setInterval(tick, HEARTBEAT_MS);

    return () => {
      disposed = true;
      if (heartbeat !== null) {
        window.clearInterval(heartbeat);
        heartbeat = null;
      }
      // Final flush. If the user was mid-playback this captures the last
      // heartbeat-worth of progress so reloading the page resumes close
      // to where they left off. If we're still casting on unmount, trust
      // the receiver's time over the local video's (which is paused).
      const c = castRef.current;
      if (c.isConnected && c.currentTime > 0) {
        send(c.currentTime, c.duration > 0 ? c.duration : stream.duration_sec);
      } else if (video && !isNaN(video.currentTime) && video.currentTime > 0) {
        send(video.currentTime);
      }
      if (video) {
        video.removeEventListener("loadedmetadata", onLoadedMetadata);
      }
      const instance = hlsRef.current;
      if (instance) {
        try {
          instance.destroy();
        } catch {
          // ignore
        }
        hlsRef.current = null;
      }
      if (video) {
        video.removeAttribute("src");
        try {
          video.load();
        } catch {
          // ignore
        }
      }
    };
  }, [stream, onError, initialResume]);

  const selectLevel = useCallback((index: number) => {
    const instance = hlsRef.current;
    if (!instance) return;
    instance.currentLevel = index; // -1 means auto
    setUserLevel(index);
    const height = index >= 0 ? instance.levels[index]?.height : undefined;
    writeQualityPref(index < 0 ? "auto" : height ? String(height) : "auto");
  }, []);

  // Sample the playhead for the skip-button gate. timeupdate fires a few
  // times a second, which is plenty for showing/hiding a button.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onTime = () => setCurrentTime(video.currentTime || 0);
    video.addEventListener("timeupdate", onTime);
    return () => video.removeEventListener("timeupdate", onTime);
  }, []);

  // Markers are in source time; a resumed HLS stream's clock starts at the
  // encode start (timeline_offset_sec, the bucket) into the source.
  const timeBase =
    stream.mode === "hls"
      ? (stream.timeline_offset_sec ?? stream.offset_sec ?? 0)
      : 0;
  const sourceTime = currentTime + timeBase;
  const activeMarker =
    markers.find((m) => sourceTime >= m.start_sec && sourceTime < m.end_sec) ?? null;

  function skipMarker(m: MediaMarker) {
    const video = videoRef.current;
    if (!video) return;
    try {
      video.currentTime = Math.max(0, m.end_sec - timeBase);
    } catch {
      /* ignore */
    }
  }

  const isCasting = cast.isConnected;

  // The quality gear descriptor. Same conditions the overlay used, but the gear
  // now renders in the VideoTransport bar: multi-rendition HLS switches hls.js
  // levels; a CPU-only server restarts the stream at the chosen height. Null
  // while casting or when there's nothing to pick. Reported up so VideoTransport
  // can render it and the watch page can read the playing rendition height.
  const qualityControl = useMemo<QualityControlData | null>(() => {
    if (isCasting) return null;
    if (levels.length > 1) {
      return { kind: "hls", levels, loadedLevel, userLevel, onSelect: selectLevel };
    }
    if (stream.mode === "hls" && onServerQuality && features && !features.transcode?.hardware) {
      return {
        kind: "server",
        heights: serverQualityHeights(stream.height),
        current: serverQuality ?? CPU_START_HEIGHT,
        onSelect: onServerQuality,
      };
    }
    return null;
  }, [
    isCasting,
    levels,
    loadedLevel,
    userLevel,
    selectLevel,
    stream.mode,
    stream.height,
    onServerQuality,
    features,
    serverQuality,
  ]);

  useEffect(() => {
    onQualityControl?.(qualityControl);
  }, [qualityControl, onQualityControl]);

  return (
    <div className="relative h-full w-full">
      <video
        ref={setVideoNode}
        autoPlay={autoPlay}
        playsInline
        preload="metadata"
        className={`h-full w-full bg-black ${ready ? "" : "opacity-0"}`}
      />

      {/* Casting overlay. Covers the video so the user sees status rather
          than a frozen frame. Includes a Disconnect shortcut. */}
      {isCasting ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/95 text-neutral-100">
          <CastPlayingIcon />
          <div className="mt-4 text-lg font-semibold">
            Casting to {cast.deviceName ?? "your device"}
          </div>
          {stream.title ? (
            <div className="mt-1 text-sm text-neutral-400">{stream.title}</div>
          ) : null}
          <div className="mt-5 flex items-center gap-2">
            <button
              type="button"
              onClick={cast.playPause}
              className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-100 transition hover:border-neutral-500"
            >
              {cast.isPaused ? "Play" : "Pause"}
            </button>
            <button
              type="button"
              onClick={() => cast.endSession(true)}
              className="rounded-md bg-hive px-3 py-1.5 text-xs font-medium text-on-hive transition hover:bg-hive-hover"
            >
              Stop casting
            </button>
          </div>
        </div>
      ) : null}

      {/* Skip Intro / Skip Credits. Shows only while the playhead is inside
          a detected marker and we're not casting. Sits above the custom
          VideoTransport bar (taller than the old native strip) at the
          bottom-right, so bottom-44 clears the transport height. */}
      {activeMarker && !isCasting ? (
        <button
          type="button"
          onClick={() => skipMarker(activeMarker)}
          className="absolute bottom-44 right-4 z-20 rounded-md bg-black/70 px-4 py-2 text-sm font-medium text-neutral-100 backdrop-blur-sm transition hover:bg-black/90"
        >
          {activeMarker.kind === "intro" ? "Skip Intro" : "Skip Credits"}
        </button>
      ) : null}

      {/* Top-right overlay: cast button only. The quality gear moved to the
          VideoTransport controls row (it was too close to the Close player X). */}
      <div className="absolute right-3 top-3 z-10 flex items-center gap-2">
        <CastButton status={cast.status} />
      </div>
    </div>
  );
}

function CastPlayingIcon() {
  return <Icon icon={Cast} size={48} aria-hidden="true" className="text-hive-text" />;
}
