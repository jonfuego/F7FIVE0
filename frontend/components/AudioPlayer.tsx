// AudioPlayer. Counterpart to <Player> for audio-only streams (MP3,
// M4A, AAC, WAV, FLAC, OGG). A 16:9 video frame is the wrong shape for
// a 4-minute track, so this component renders a compact card with the
// title line + a native <audio> controls bar.
//
// Direct-play only in v1. The backend's can_direct_play routes the
// Chromecast-safe container subset to /stream/direct/; containers that
// don't direct-play (OPUS/WMA) still produce a `mode: "hls"` response
// but those need an audio-only HLS fork in the transcoder which isn't
// built yet. When the caller hands us an HLS audio stream we degrade
// to attaching the master playlist to <audio>, which Safari handles
// natively and everything else will fail loudly in the console rather
// than silently.
//
// Cast: same bridge as <Player>. When a cast session is active we pause
// local audio, push the signed URL + cover art to the receiver, and
// heartbeat using the receiver's time. Session end seeks local audio
// to the receiver's position and resumes.
//
// Progress: identical heartbeat contract as <Player> so the same
// watch_progress row covers both paths.

"use client";

import { useEffect, useRef, useState } from "react";
import { apiPut } from "@/lib/client-api";
import type { Progress, StreamStart } from "@/lib/types";
import CastButton from "./CastButton";
import { useCast } from "@/lib/cast";
import { Icon } from "@/components/Icon";
import { Music } from "lucide-react";

type Props = {
  stream: StreamStart;
  onError?: (message: string) => void;
  autoPlay?: boolean;
  initialResume?: number;
  // Optional cover art URL. Same-origin is fine; the Cast receiver on
  // the LAN reaches the tunnel origin like the browser does.
  posterUrl?: string;
  // Optional subtitle line under the title (e.g. "Artist - Album").
  subtitle?: string | null;
};

const HEARTBEAT_MS = 10_000;

function toAbsolute(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  if (typeof window === "undefined") return url;
  if (url.startsWith("/")) return `${window.location.origin}${url}`;
  return `${window.location.origin}/${url}`;
}

// Content-Type hint we send to the Cast receiver. The Default Media
// Receiver sniffs the stream anyway, but a matching hint speeds the
// initial load and avoids a warning in the cast debug console.
function castContentTypeFor(stream: StreamStart): string {
  if (stream.mode === "hls") return "application/vnd.apple.mpegurl";
  const c = (stream.container ?? "").toLowerCase();
  if (c === "mp3") return "audio/mpeg";
  if (c === "m4a") return "audio/mp4";
  if (c === "aac") return "audio/aac";
  if (c === "wav") return "audio/wav";
  if (c === "flac") return "audio/flac";
  if (c === "ogg" || c === "oga") return "audio/ogg";
  return "audio/mpeg";
}

export function AudioPlayer({
  stream,
  onError,
  autoPlay = true,
  initialResume,
  posterUrl,
  subtitle,
}: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [ready, setReady] = useState(false);

  const cast = useCast();
  const castRef = useRef(cast);
  useEffect(() => {
    castRef.current = cast;
  }, [cast]);

  // Cast session transitions. Pause local on connect, resume local on disconnect.
  const wasConnectedRef = useRef(false);
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const nowConnected = cast.isConnected;
    const wasConnected = wasConnectedRef.current;
    wasConnectedRef.current = nowConnected;

    if (nowConnected && !wasConnected) {
      const startAt =
        isFinite(audio.currentTime) && audio.currentTime > 0
          ? audio.currentTime
          : (initialResume ?? 0);
      try { audio.pause(); } catch { /* ignore */ }

      const absoluteUrl = toAbsolute(stream.url);
      void cast
        .loadMedia({
          contentUrl: absoluteUrl,
          contentType: castContentTypeFor(stream),
          title: stream.title ?? undefined,
          posterUrl: posterUrl,
          startTime: startAt > 0 ? startAt : undefined,
          durationSec: stream.duration_sec ?? undefined,
        })
        .catch((err: unknown) => {
          const message = err instanceof Error ? err.message : String(err);
          onError?.(`Cast failed: ${message}`);
          try { void audio.play(); } catch { /* ignore */ }
        });
    } else if (!nowConnected && wasConnected) {
      const resumeAt = cast.currentTime;
      try {
        if (resumeAt > 0 && isFinite(audio.duration) && audio.duration > 0) {
          audio.currentTime = resumeAt;
        }
      } catch { /* ignore */ }
      try {
        const p = audio.play();
        if (p && typeof p.catch === "function") p.catch(() => { /* ignore */ });
      } catch { /* ignore */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cast.isConnected, stream, onError, posterUrl, initialResume]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    let heartbeat: number | null = null;
    let resumePos: number | null =
      initialResume != null && initialResume > 0 ? initialResume : null;

    // Attach source. Direct-play is the common path; HLS audio would
    // only arrive here for containers we couldn't direct-play (OPUS,
    // WMA). Safari <audio> can play HLS natively; other browsers will
    // surface an error we pass to onError.
    audio.src = stream.url;
    setReady(true);

    function trySeekNow() {
      if (!audio || resumePos == null) return;
      if (!isNaN(audio.duration) && audio.duration > 0) {
        try { audio.currentTime = resumePos; } catch { /* ignore */ }
        resumePos = null;
      }
    }

    function onLoadedMetadata() {
      trySeekNow();
    }

    function onMediaError() {
      const err = audio?.error;
      if (!err) return;
      const codeMap: Record<number, string> = {
        1: "aborted",
        2: "network",
        3: "decode",
        4: "src_not_supported",
      };
      onError?.(`Audio error: ${codeMap[err.code] ?? `code_${err.code}`}`);
    }

    function send(position: number, durationHint?: number | null) {
      const duration =
        durationHint != null && durationHint > 0
          ? Math.floor(durationHint)
          : audio && !isNaN(audio.duration) && audio.duration > 0
            ? Math.floor(audio.duration)
            : (stream.duration_sec ?? null);
      void apiPut<Progress>(
        `/api/library/progress/${stream.media_file_id}`,
        {
          position_sec: Math.floor(position),
          duration_sec: duration,
        },
      ).catch(() => { /* swallow */ });
    }

    function tick() {
      const c = castRef.current;
      if (c.isConnected) {
        if (c.currentTime > 0) {
          send(c.currentTime, c.duration > 0 ? c.duration : stream.duration_sec);
        }
        return;
      }
      if (!audio) return;
      if (audio.paused || audio.ended) return;
      if (isNaN(audio.currentTime)) return;
      send(audio.currentTime);
    }

    audio.addEventListener("loadedmetadata", onLoadedMetadata);
    audio.addEventListener("error", onMediaError);
    trySeekNow();
    heartbeat = window.setInterval(tick, HEARTBEAT_MS);

    return () => {
      if (heartbeat !== null) {
        window.clearInterval(heartbeat);
        heartbeat = null;
      }
      const c = castRef.current;
      if (c.isConnected && c.currentTime > 0) {
        send(c.currentTime, c.duration > 0 ? c.duration : stream.duration_sec);
      } else if (audio && !isNaN(audio.currentTime) && audio.currentTime > 0) {
        send(audio.currentTime);
      }
      if (audio) {
        audio.removeEventListener("loadedmetadata", onLoadedMetadata);
        audio.removeEventListener("error", onMediaError);
        audio.removeAttribute("src");
        try { audio.load(); } catch { /* ignore */ }
      }
    };
  }, [stream, onError, initialResume]);

  const isCasting = cast.isConnected;

  return (
    // Full-bleed wrapper. The Watch page's flex column gives us the full
    // viewport height; we expand to fill it so the backdrop covers the
    // whole frame. `relative` anchors the backdrop + card.
    <div className="relative isolate flex h-full min-h-full w-full flex-1 items-center justify-center overflow-hidden">
      {/* Backdrop. Same cover art, blown up and blurred, with a vignette
          so controls read cleanly over whatever the cover hue is. When
          there's no artwork we fall back to a soft gradient. */}
      {posterUrl ? (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={posterUrl}
            alt=""
            aria-hidden="true"
            className="absolute inset-0 -z-10 h-full w-full scale-110 object-cover opacity-40 blur-2xl"
          />
          <div
            aria-hidden="true"
            className="absolute inset-0 -z-10 bg-gradient-to-b from-black/60 via-black/70 to-black/90"
          />
        </>
      ) : (
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 bg-gradient-to-b from-neutral-900 via-neutral-950 to-black"
        />
      )}

      {/* Foreground card. Semi-transparent so the backdrop bleeds through
          the edges; backdrop-blur adds a frosted effect where the card
          overlaps the blurred cover. */}
      <div className="mx-3 w-full max-w-md rounded-2xl border border-white/10 bg-neutral-950/70 p-6 shadow-2xl backdrop-blur-xl sm:p-8">
        <div className="flex flex-col items-center text-center">
          {posterUrl ? (
            // Large square cover. Drop-shadow lifts it off the frosted card.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={posterUrl}
              alt={stream.album_title ?? stream.title ?? ""}
              className="aspect-square w-full max-w-[18rem] rounded-xl object-cover shadow-[0_20px_50px_rgba(0,0,0,0.6)] ring-1 ring-white/10"
            />
          ) : (
            <div className="flex aspect-square w-full max-w-[18rem] items-center justify-center rounded-xl bg-neutral-900/80 text-neutral-600 shadow-[0_20px_50px_rgba(0,0,0,0.6)] ring-1 ring-white/10">
              <NoteIcon />
            </div>
          )}

          <div className="mt-5 w-full">
            <div className="truncate text-lg font-semibold text-neutral-50">
              {stream.title ?? "Unknown track"}
            </div>
            {subtitle ? (
              <div className="mt-1 truncate text-sm text-neutral-300">
                {subtitle}
              </div>
            ) : null}
          </div>

          <div className="mt-5 w-full">
            <audio
              ref={audioRef}
              controls={!isCasting}
              autoPlay={autoPlay}
              preload="metadata"
              className={`w-full ${ready ? "" : "opacity-0"}`}
            />
          </div>

          <div className="mt-4 flex items-center gap-2">
            <CastButton status={cast.status} />
          </div>
        </div>

        {isCasting ? (
          <div className="mt-5 rounded-lg border border-hive bg-hive-tint px-3 py-2 text-sm text-ink">
            <div className="flex items-center justify-between gap-3">
              <div className="truncate">
                Casting to {cast.deviceName ?? "your device"}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={cast.playPause}
                  className="rounded-md border border-hive px-2.5 py-1 text-xs text-ink transition hover:border-hive"
                >
                  {cast.isPaused ? "Play" : "Pause"}
                </button>
                <button
                  type="button"
                  onClick={() => cast.endSession(true)}
                  className="rounded-md bg-hive px-2.5 py-1 text-xs font-medium text-on-hive transition hover:bg-hive-hover"
                >
                  Stop
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function NoteIcon() {
  return <Icon icon={Music} size={32} aria-hidden="true" />;
}
