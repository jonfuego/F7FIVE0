// Player page. Marquee NowPlaying chrome: top bar with truncating title
// and a fixed-width close button (never wraps), the existing <Player>
// (or <AudioPlayer>) below, and a transport time tick that runs every
// 1s during playback in H:MM:SS / M:SS format depending on duration.
//
// Resume prompt and the rest of the streaming flow are unchanged from
// Phase 4. Only the chrome is restyled.

"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Icon } from "@/components/Icon";
import { SkipBack, SkipForward, Play, Pause, ListMusic } from "lucide-react";
import { Player } from "@/components/Player";
import { VideoTransport } from "@/components/VideoTransport";
import type { QualityControlData } from "@/components/QualityMenu";
import { QueuePanel } from "@/components/QueuePanel";
import { PlayerTrackMenu } from "@/components/PlayerTrackMenu";
import { apiGet, apiPost, ApiError } from "@/lib/client-api";
import { formatDuration, formatResolution } from "@/lib/format";
import { useQueue, type QueueItem } from "@/lib/queue";
import type { MediaMarker, Progress, StreamStart, StreamStartRequest } from "@/lib/types";
import { loadFeatures } from "@/lib/features";
import { prefHeight, readQualityPref, writeQualityPref } from "@/lib/quality";
import { browserClientCaps } from "@/lib/playback-caps";
import { artSized } from "@/lib/art-url";

const AUDIO_CONTAINERS = new Set([
  "mp3", "m4a", "aac", "wav", "flac", "ogg", "oga", "opus", "wma",
]);

function isAudioStream(stream: StreamStart): boolean {
  const c = (stream.container ?? "").toLowerCase();
  return AUDIO_CONTAINERS.has(c);
}

// Resolution shown on the info line. In HLS mode the source size lies: a
// resumed or CPU transcode serves a smaller rendition than the file (seen:
// "TRANSCODED 1080P" while the 720p rendition played). Use the rendition that
// is actually playing (the hls.js loaded level, or the chosen server height),
// and only fall back to the source size for direct play.
function renditionResolution(
  stream: StreamStart,
  quality: QualityControlData | null,
): string {
  if (stream.mode === "hls" && quality) {
    if (quality.kind === "hls") {
      const level = quality.levels[quality.loadedLevel];
      if (level?.height) {
        return formatResolution(level.width ?? Math.round((level.height * 16) / 9), level.height);
      }
    } else if (quality.kind === "server" && quality.current) {
      return formatResolution(Math.round((quality.current * 16) / 9), quality.current);
    }
  }
  return formatResolution(stream.width, stream.height);
}

// Mint a QueueItem from a resolved stream so an audio file opened directly
// on the watch route (not already in the dock queue) can be inserted and
// played by the dock. Parent IDs aren't on StreamStart, so the dock falls
// back to plain-text artist/album labels for these inserted items.
function streamToQueueItem(stream: StreamStart): QueueItem {
  return {
    media_file_id: stream.media_file_id,
    title: stream.title ?? "",
    artist_name: stream.artist_name,
    album_title: stream.album_title,
    cover_path: stream.cover_path,
    duration_sec: stream.duration_sec,
  };
}

const RESUME_MIN_SEC = 15;
const RESUME_TAIL_SEC = 30;

type ResumeState =
  | { kind: "loading" }
  | { kind: "prompt"; position: number }
  | { kind: "chose"; resumeSec: number };

// Format a duration in seconds. Uses H:MM:SS when total duration is at
// least an hour, M:SS otherwise. AC #16 verification.
function formatTime(seconds: number, totalSec: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (totalSec >= 3600) {
    return `${h}:${pad(m)}:${pad(s)}`;
  }
  return `${m}:${pad(s)}`;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

export default function WatchPage() {
  const params = useParams<{ mediaFileId: string }>();
  const mediaFileId = params?.mediaFileId;
  const router = useRouter();
  // The dock owns the only <audio> element. If the queue is already
  // playing this same media_file_id, defer to the dock so playback
  // doesn't gap or double-up. We render a "linked" view instead of
  // mounting our own AudioPlayer.
  const queue = useQueue();
  const { skipTo: queueSkipTo, playNow: queuePlayNow, hydrated: queueHydrated } = queue;
  const queueCurrent = queue.currentIndex !== null
    ? queue.items[queue.currentIndex] ?? null
    : null;
  const linkedToDock =
    !!mediaFileId && queueCurrent?.media_file_id === mediaFileId;
  // When the queue advances past the current route (user hits Next in
  // the linked view), we want /watch to follow the queue instead of
  // mounting AudioPlayer for the old route. `followingQueue` stays
  // true across the brief window between the queue advance and the
  // route catch-up, keeping the linked view rendered.
  const linkedRef = useRef<boolean>(false);
  const [followingQueue, setFollowingQueue] = useState<boolean>(false);
  const useDockAudio = linkedToDock || followingQueue;
  const [stream, setStream] = useState<StreamStart | null>(null);
  const [resume, setResume] = useState<ResumeState>({ kind: "loading" });
  const [error, setError] = useState<string | null>(null);
  const [markers, setMarkers] = useState<MediaMarker[]>([]);

  // Live time display, ticked every 1s while playback is in progress.
  // Mirrors the prototype's NowPlaying scrubber. We poll the live <video>
  // element inside <Player> since it owns the audio/video src attachment.
  const [tNow, setTNow] = useState(0);
  const [panelOpen, setPanelOpen] = useState(false);
  // The live <video> element, handed up from <Player> via onVideoEl. Drives
  // the custom VideoTransport. Replaces the old ".np video" DOM poll.
  const [videoEl, setVideoEl] = useState<HTMLVideoElement | null>(null);
  // Saved quality pick (height). Sent to stream/start on CPU-only servers,
  // which encode exactly one rendition per stream.
  const [quality, setQuality] = useState<number | null>(() => prefHeight(readQualityPref()));
  // Quality gear descriptor reported up from <Player>. Handed to VideoTransport
  // (which renders the gear in its controls row) and read for the info line's
  // playing-rendition height.
  const [qualityControl, setQualityControl] = useState<QualityControlData | null>(null);

  // Detect "queue advanced past route while we were linked" and follow
  // it by replacing the route. Without this, /watch falls through to
  // AudioPlayer for the old mediaFileId and double-plays.
  useEffect(() => {
    if (
      linkedRef.current &&
      !linkedToDock &&
      queueCurrent &&
      mediaFileId &&
      queueCurrent.media_file_id !== mediaFileId
    ) {
      setFollowingQueue(true);
      router.replace(`/watch/${queueCurrent.media_file_id}`);
    }
    linkedRef.current = linkedToDock;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkedToDock, queueCurrent?.media_file_id, mediaFileId, router]);

  // Clear `followingQueue` once the route has caught up.
  useEffect(() => {
    if (followingQueue && linkedToDock) setFollowingQueue(false);
  }, [followingQueue, linkedToDock]);

  // Dock time tick. The video path no longer polls a DOM element here: the
  // VideoTransport owns its own time readout, driven by listeners on the
  // element handed up from <Player>. Only the dock branch remains.
  useEffect(() => {
    if (!useDockAudio) return;
    const id = window.setInterval(() => {
      const dock = document.getElementById("mh-dock-audio") as HTMLAudioElement | null;
      if (dock && !isNaN(dock.currentTime)) {
        setTNow(dock.currentTime);
      }
    }, 1000);
    return () => {
      window.clearInterval(id);
    };
  }, [useDockAudio]);

  // Load intro/credits markers for the skip button. Harmless for movies
  // (none detected) and skipped for dock-linked audio.
  useEffect(() => {
    if (!mediaFileId || useDockAudio) {
      setMarkers([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const m = await apiGet<MediaMarker[]>(`/api/library/markers/${mediaFileId}`);
        if (!cancelled) setMarkers(m);
      } catch {
        if (!cancelled) setMarkers([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mediaFileId, useDockAudio]);

  // Single audio source of truth. The dock (<MiniPlayer>) owns the only
  // <audio> element; mounting a second <AudioPlayer> here for an audio
  // track is what lets the mini-player and fullscreen play two different
  // tracks at once. Instead, reconcile an unlinked audio file into the
  // dock queue: skip to it if it's already queued, otherwise insert and
  // play it so the dock takes over and DockLinkedView renders. Gated on
  // queue hydration so a cold PWA resume onto a watch route doesn't act
  // against the empty pre-hydration queue (which would double-insert once
  // the server queue loads). Video is never reconciled; it stays on the
  // <Player> path below.
  const reconciledRef = useRef<string | null>(null);
  useEffect(() => {
    if (!mediaFileId) return;
    if (!queueHydrated) return;
    if (useDockAudio) return;
    if (reconciledRef.current === mediaFileId) return;

    const idx = queue.items.findIndex((it) => it.media_file_id === mediaFileId);
    if (idx >= 0) {
      reconciledRef.current = mediaFileId;
      queueSkipTo(idx);
      return;
    }
    // Not in the queue yet: only audio reconciles into the dock. Wait for
    // the stream metadata so a video file stays on the <Player> path.
    if (!stream || !isAudioStream(stream)) return;
    reconciledRef.current = mediaFileId;
    queuePlayNow(streamToQueueItem(stream));
  }, [mediaFileId, queueHydrated, useDockAudio, queue.items, stream, queueSkipTo, queuePlayNow]);

  // ESC closes the player and pops back to the previous route. Mirrors
  // the prototype's overlay close behavior.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        router.back();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  useEffect(() => {
    if (!mediaFileId) return;
    if (useDockAudio) {
      // Dock is already streaming this; mark resume "chose" with the
      // current dock playhead so the (skipped) stream-start effect has
      // a sane state to read.
      const dock = typeof document !== "undefined"
        ? (document.getElementById("mh-dock-audio") as HTMLAudioElement | null)
        : null;
      const pos = dock && !isNaN(dock.currentTime)
        ? Math.max(0, Math.floor(dock.currentTime))
        : 0;
      setResume({ kind: "chose", resumeSec: pos });
      return;
    }
    let cancelled = false;

    // Fast path: when the user expanded the running mini-player by
    // clicking the album cover, the dock writes an "mh:expand" hint to
    // sessionStorage with the current playhead. We consume it here so
    // the watch page skips the resume prompt and starts at the same
    // position the dock was on. Hint is one-shot (cleared on read) and
    // expires after 5s so a stale entry can't take over a real visit.
    try {
      const raw = sessionStorage.getItem("mh:expand");
      if (raw) {
        sessionStorage.removeItem("mh:expand");
        const hint = JSON.parse(raw) as {
          media_file_id?: string;
          position_sec?: number;
          ts?: number;
        };
        if (
          hint &&
          hint.media_file_id === mediaFileId &&
          typeof hint.position_sec === "number" &&
          typeof hint.ts === "number" &&
          Date.now() - hint.ts < 5000
        ) {
          setResume({ kind: "chose", resumeSec: Math.max(0, Math.floor(hint.position_sec)) });
          return () => {
            cancelled = true;
          };
        }
      }
    } catch {
      // sessionStorage can throw in private modes; fall through to the
      // normal progress lookup.
    }

    (async () => {
      try {
        const p = await apiGet<Progress | null>(
          `/api/library/progress/${mediaFileId}`,
        );
        if (cancelled) return;
        if (!p) {
          setResume({ kind: "chose", resumeSec: 0 });
          return;
        }
        const pos = p.position_sec;
        const duration = p.duration_sec;
        if (pos < RESUME_MIN_SEC) {
          setResume({ kind: "chose", resumeSec: 0 });
          return;
        }
        if (duration && pos > duration - RESUME_TAIL_SEC) {
          setResume({ kind: "chose", resumeSec: 0 });
          return;
        }
        setResume({ kind: "prompt", position: pos });
      } catch {
        if (!cancelled) setResume({ kind: "chose", resumeSec: 0 });
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaFileId]);

  useEffect(() => {
    if (!mediaFileId) return;
    if (useDockAudio) return;
    if (resume.kind !== "chose") return;
    let cancelled = false;
    (async () => {
      try {
        const body: StreamStartRequest = { file_id: mediaFileId };
        if (resume.resumeSec > 0) body.resume_sec = resume.resumeSec;
        const caps = browserClientCaps();
        if (caps) body.client_caps = caps;
        if (quality) {
          const features = await loadFeatures();
          if (!features.transcode?.hardware) {
            body.quality = `${quality}p` as StreamStartRequest["quality"];
          }
        }
        const data = await apiPost<StreamStart>("/api/stream/start", body);
        if (!cancelled) setStream(data);
      } catch (err) {
        if (cancelled) return;
        setError(messageFor(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mediaFileId, resume, useDockAudio, quality]);

  function onServerQuality(height: number) {
    writeQualityPref(String(height));
    // Source position: a resumed HLS stream's element clock reads 0 at the
    // encode start (timeline_offset_sec, the bucket), so add that to the
    // element time to get the true source second. Falls back to offset_sec for
    // an older backend that did not send the timeline field.
    const base =
      stream?.mode === "hls"
        ? (stream.timeline_offset_sec ?? stream.offset_sec ?? 0)
        : 0;
    const at = Math.floor(base + (videoEl?.currentTime ?? 0));
    setQuality(height);
    setResume({ kind: "chose", resumeSec: at });
  }

  // Scrubbing to before a resumed transcode's start: restart the stream there.
  function onSeekBeforeStart(sourceSec: number) {
    setResume({ kind: "chose", resumeSec: Math.max(0, sourceSec) });
  }

  const chosenOffset = resume.kind === "chose" ? resume.resumeSec : 0;
  const readyToPlay = stream !== null;
  const initialResume =
    stream?.mode === "direct" && chosenOffset > 0 ? chosenOffset : undefined;

  const totalSec = stream?.duration_sec ?? (useDockAudio ? (queueCurrent?.duration_sec ?? 0) : 0);
  const timeStr = formatTime(tNow, totalSec);
  const totalStr = totalSec > 0 ? formatTime(totalSec, totalSec) : "—";

  return (
    <div className="np">
      <div className="stage">
        <div className="top">
          <div
            className="title"
            style={{
              // Title truncates with text-overflow: ellipsis; overflow: hidden;
              // white-space: nowrap so it never wraps onto a second line.
              textOverflow: "ellipsis",
              overflow: "hidden",
              whiteSpace: "nowrap",
              minWidth: 0,
            }}
          >
            {stream?.title ?? queueCurrent?.title ?? "Loading…"}
          </div>
          <button
            type="button"
            className="close"
            // Fixed min-width keeps the close affordance the same size at any
            // viewport so the title can shrink-to-fit.
            style={{ minWidth: 40 }}
            onClick={() => router.back()}
            aria-label="Close player"
            title="Close (ESC)"
          >
            ✕
          </button>
        </div>

        {useDockAudio ? (
          <DockLinkedView
            item={queueCurrent}
            onPrev={queue.prev}
            onNext={queue.next}
            onOpenQueue={() => setPanelOpen(true)}
          />
        ) : readyToPlay && stream && !error && isAudioStream(stream) ? (
          // Audio never mounts its own <AudioPlayer>. The reconcile effect
          // has dispatched this file into the dock queue; show the loading
          // state until useDockAudio flips and DockLinkedView takes over.
          <LoadingBox />
        ) : error ? (
          <ErrorBox message={error} onRetry={() => window.location.reload()} />
        ) : readyToPlay && stream ? (
          <Player
            stream={stream}
            onError={setError}
            initialResume={initialResume}
            markers={markers}
            onVideoEl={setVideoEl}
            serverQuality={quality}
            onServerQuality={onServerQuality}
            onQualityControl={setQualityControl}
          />
        ) : resume.kind === "prompt" ? (
          <ResumePrompt
            position={resume.position}
            onResume={() => setResume({ kind: "chose", resumeSec: resume.position })}
            onRestart={() => setResume({ kind: "chose", resumeSec: 0 })}
          />
        ) : (
          <LoadingBox />
        )}

        <div className="controls">
          {stream && !useDockAudio ? (
            // Video path: the real transport, driving the <video> directly.
            <VideoTransport
              videoEl={videoEl}
              durationSec={totalSec}
              offsetSec={
                stream.mode === "hls"
                  ? (stream.timeline_offset_sec ?? stream.offset_sec ?? 0)
                  : 0
              }
              onSeekBeforeStart={onSeekBeforeStart}
              quality={qualityControl}
            />
          ) : (
            // Dock-audio path: the decorative scrub, driven by the dock tick.
            <div className="scrub">
              <span className="time">{timeStr}</span>
              <div className="bar">
                <div
                  className="fill"
                  style={{
                    width: totalSec > 0 ? `${Math.min(100, (tNow / totalSec) * 100)}%` : "0%",
                  }}
                />
              </div>
              <span className="time">{totalStr}</span>
            </div>
          )}
          {stream && !useDockAudio ? (
            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                justifyContent: "center",
                fontFamily: "var(--mono)",
                fontSize: 11,
                letterSpacing: "0.16em",
                textTransform: "uppercase",
                color: "var(--ink-3)",
              }}
            >
              <span>{stream.mode === "direct" ? "Direct" : "Transcoded"}</span>
              {stream.variant ? <span>· {stream.variant}</span> : null}
              {!isAudioStream(stream) ? (
                <span>· {renditionResolution(stream, qualityControl)}</span>
              ) : null}
              <span>· {stream.container?.toUpperCase() ?? ""}</span>
            </div>
          ) : null}
        </div>
      </div>
      <QueuePanel open={panelOpen} onClose={() => setPanelOpen(false)} />
    </div>
  );
}

function ResumePrompt({
  position,
  onResume,
  onRestart,
}: {
  position: number;
  onResume: () => void;
  onRestart: () => void;
}) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "grid",
        placeItems: "center",
        zIndex: 2,
      }}
    >
      <div
        style={{
          background: "var(--bg-2)",
          border: "1px solid var(--line)",
          borderRadius: 8,
          padding: "32px 28px",
          maxWidth: 360,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontFamily: "var(--display)",
            fontSize: 28,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            color: "var(--ink)",
            marginBottom: 8,
          }}
        >
          Continue Watching?
        </div>
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 12,
            letterSpacing: "0.06em",
            color: "var(--ink-3)",
            marginBottom: 20,
          }}
        >
          You left off at {formatDuration(position)}
        </div>
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          <button type="button" className="btn play" onClick={onResume}>
            <span className="tri" /> Resume
          </button>
          <button type="button" className="btn ghost" onClick={onRestart}>
            Start over
          </button>
        </div>
      </div>
    </div>
  );
}

function LoadingBox() {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "grid",
        placeItems: "center",
        color: "var(--ink-3)",
        fontFamily: "var(--mono)",
        fontSize: 12,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
      }}
    >
      Preparing the projector…
    </div>
  );
}

function ErrorBox({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "grid",
        placeItems: "center",
        zIndex: 2,
      }}
    >
      <div
        style={{
          background: "var(--bg-2)",
          border: "1px solid var(--danger)",
          borderRadius: 8,
          padding: "24px 28px",
          maxWidth: 480,
          color: "var(--danger)",
        }}
      >
        <div
          style={{
            fontFamily: "var(--display)",
            fontSize: 22,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            marginBottom: 8,
          }}
        >
          Can&apos;t play this file
        </div>
        <p
          style={{
            fontFamily: "var(--grotesk)",
            fontSize: 14,
            color: "var(--ink-2)",
            margin: "0 0 16px",
          }}
        >
          {message}
        </p>
        <button type="button" className="btn ghost" onClick={onRetry}>
          Try again
        </button>
      </div>
    </div>
  );
}

function messageFor(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.detail) {
      case "file_not_found":
        return "We couldn't find that file. It may have been removed.";
      case "file_missing":
        return "The file used to be in the library but isn't on disk right now.";
      case "file_unplayable":
        return "This file has a scan error and isn't playable.";
      case "file_not_ready":
        return "The library scan hasn't caught up to this file yet. Try again in a minute.";
      default:
        return err.detail ?? `Server returned ${err.status}.`;
    }
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}


const iconButtonStyle = {
  width: 56,
  height: 56,
  borderRadius: "50%",
  background: "transparent",
  color: "var(--ink-2)",
  display: "grid",
  placeItems: "center",
  cursor: "pointer",
  border: "1px solid var(--line)",
} as const;

function DockLinkedView({
  item,
  onPrev,
  onNext,
  onOpenQueue,
}: {
  item: QueueItem | null;
  onPrev: () => void;
  onNext: () => void;
  onOpenQueue: () => void;
}) {
  const [paused, setPaused] = useState<boolean>(true);

  // Poll the active dock element for play/pause state. The dock now plays
  // through two ping-ponged <audio> elements and reassigns id="mh-dock-audio"
  // to whichever is active on a swap, so we must re-resolve the element each
  // tick rather than caching one reference and binding listeners to it (a
  // cached element would stop reflecting state after a gapless swap).
  useEffect(() => {
    const sync = () => {
      const dock = document.getElementById("mh-dock-audio") as HTMLAudioElement | null;
      if (dock) setPaused(dock.paused);
    };
    sync();
    const id = window.setInterval(sync, 250);
    return () => window.clearInterval(id);
  }, []);

  const toggle = () => {
    const dock = document.getElementById("mh-dock-audio") as HTMLAudioElement | null;
    if (!dock) return;
    if (dock.paused) {
      const p = dock.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    } else {
      dock.pause();
    }
  };

  const artistName = item?.artist_name?.trim() || null;
  const albumTitle = item?.album_title?.trim() || null;
  const artistHref = item?.artist_id ? `/music/artists/${item.artist_id}` : null;
  const albumHref = item?.album_id ? `/music/${item.album_id}` : null;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px 36px",
        gap: 24,
        zIndex: 1,
      }}
    >
      {item?.cover_path ? (
        <img
          src={artSized(item.cover_path, 600) ?? item.cover_path}
          alt=""
          style={{
            width: "min(60vmin, 360px)",
            aspectRatio: "1/1",
            borderRadius: 12,
            objectFit: "cover",
            boxShadow: "0 24px 60px var(--scrim)",
          }}
        />
      ) : (
        <div
          style={{
            width: "min(60vmin, 360px)",
            aspectRatio: "1/1",
            borderRadius: 12,
            background: "var(--bg-2)",
            border: "1px solid var(--line)",
          }}
        />
      )}
      <div style={{ textAlign: "center", maxWidth: "100%" }}>
        <div
          style={{
            fontFamily: "var(--display)",
            fontSize: 28,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
          }}
        >
          {item?.title ?? ""}
        </div>
        {(artistName || albumTitle) ? (
          <div
            style={{
              fontFamily: "var(--grotesk)",
              fontSize: 14,
              color: "var(--ink-3)",
              marginTop: 6,
            }}
          >
            {artistName ? (
              artistHref ? (
                <Link href={artistHref} style={{ color: "inherit", textDecoration: "none" }}
                  onMouseEnter={e => (e.currentTarget.style.textDecoration = "underline")}
                  onMouseLeave={e => (e.currentTarget.style.textDecoration = "none")}
                >{artistName}</Link>
              ) : <span>{artistName}</span>
            ) : null}
            {artistName && albumTitle ? " • " : null}
            {albumTitle ? (
              albumHref ? (
                <Link href={albumHref} style={{ color: "inherit", textDecoration: "none" }}
                  onMouseEnter={e => (e.currentTarget.style.textDecoration = "underline")}
                  onMouseLeave={e => (e.currentTarget.style.textDecoration = "none")}
                >{albumTitle}</Link>
              ) : <span>{albumTitle}</span>
            ) : null}
          </div>
        ) : null}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 16,
        }}
      >
        <button
          type="button"
          onClick={onPrev}
          aria-label="Previous"
          style={iconButtonStyle}
        >
          <Icon icon={SkipBack} size={26} fill />
        </button>
        <button
          type="button"
          onClick={toggle}
          aria-label={paused ? "Play" : "Pause"}
          className="np-audio-play"
        >
          {paused ? (
            <Icon icon={Play} size={28} fill />
          ) : (
            <Icon icon={Pause} size={28} fill />
          )}
        </button>
        <button
          type="button"
          onClick={onNext}
          aria-label="Next"
          style={iconButtonStyle}
        >
          <Icon icon={SkipForward} size={26} fill />
        </button>
        <button
          type="button"
          onClick={onOpenQueue}
          aria-label="Open queue"
          style={iconButtonStyle}
        >
          <Icon icon={ListMusic} size={26} />
        </button>
        <PlayerTrackMenu
          albumId={item?.album_id ?? null}
          artistId={item?.artist_id ?? null}
          placement="up"
          buttonStyle={iconButtonStyle}
          iconSize={24}
        />
      </div>
    </div>
  );
}
