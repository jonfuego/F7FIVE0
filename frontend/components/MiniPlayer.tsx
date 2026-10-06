// Persistent fixed-bottom audio dock. Mounted once at app/layout.tsx
// inside the QueueProvider. Owns the two ping-ponged <audio> elements used
// by the queue (A/B double buffer for gapless playback; the active one
// carries id="mh-dock-audio"). Marquee re-skin: 3-column grid at desktop (artwork + title /
// scrubber + time / source badge + transport). The center column drops
// at <720px so a phone still has artwork + title and transport without
// the dock collapsing into a single line.
//
// All stream-start, resume-threshold, heartbeat, and track-plays POST
// behavior is preserved verbatim from Phase 5 — only the JSX/CSS
// changed.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { CSSProperties } from "react";
import type HlsType from "hls.js";
import {
  ListMusic,
  Pause,
  Play,
  Repeat,
  Shuffle,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
} from "lucide-react";
import { Icon } from "@/components/Icon";
import { apiGet, apiPost, apiPut } from "@/lib/client-api";
import {
  colorForTitle,
  formatDuration,
  hueFromString,
} from "@/lib/format";
import {
  hideMediaNotification,
  requestNotificationPermission,
  showMediaNotification,
  subscribeToNotificationActions,
} from "@/lib/media-notification";
import {
  useQueue,
  type QueueItem,
  type RepeatMode,
} from "@/lib/queue";
import { QueuePanel } from "./QueuePanel";
import { PlayerTrackMenu } from "./PlayerTrackMenu";
import { videoElementController } from "@/lib/playerController";
import type { PlayerController } from "@/lib/playerController";
import type {
  Progress,
  StreamStart,
  StreamStartRequest,
} from "@/lib/types";

const HEARTBEAT_MS = 10_000;
const RESUME_MIN_SEC = 15;
const RESUME_TAIL_SEC = 30;
const PLAY_LOG_SKIP_MIN_SEC = 30;
const PLAY_LOG_COMPLETE_FRACTION = 0.9;
// How far before track end we prefetch the next track's stream URL. The
// `ended` handler then sets src + plays from the cached URL with no inline
// /api/stream/start await, so the queue advances even when the screen is
// off and the network round trip can't complete inside the freeze window.
const PREFETCH_LEAD_SEC = 25;

// The item the queue will land on at natural track end, mirroring the
// reducer's non-shuffle `next` logic. Returns null when the next track is
// not predictable (shuffle on, repeat-one, or end of a non-looping queue),
// in which case we skip prefetch and fall back to the inline fetch path.
function predictNextItem(
  items: QueueItem[],
  currentIndex: number | null,
  repeat: RepeatMode,
  shuffle: boolean,
): QueueItem | null {
  if (currentIndex === null) return null;
  if (repeat === "one") return null;
  if (shuffle) return null;
  const nextIdx = currentIndex + 1;
  if (nextIdx >= items.length) {
    if (repeat === "all" && items.length > 0) return items[0] ?? null;
    return null;
  }
  return items[nextIdx] ?? null;
}

export function MiniPlayer() {
  const {
    items,
    currentIndex,
    next,
    prev,
    repeat,
    shuffle,
    setRepeat,
    setShuffle,
    clear,
    playing: queuePlaying,
    setPlaying,
  } = useQueue();
  const pathname = usePathname();
  // A/B double buffer. Two <audio> elements ping-pong so the next track can
  // preload into the idle element while the current one plays; at track end
  // we switch elements instead of re-sourcing one. `audioRef` always points
  // at the active element so every existing read (transport, media session,
  // scrub, smartPrev) follows a swap untouched. The active element is the
  // one carrying id="mh-dock-audio" (see the 2026-05-01 dock-audio ADR).
  const audioARef = useRef<HTMLAudioElement | null>(null);
  const audioBRef = useRef<HTMLAudioElement | null>(null);
  const activeRef = useRef<"A" | "B">("A");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const barRef = useRef<HTMLDivElement | null>(null);
  // Uniform player controller (item 8c) over the active dock <audio>. The dock
  // is always direct-play, so the element clock is source time (offset 0). The
  // toggle and scrub below drive the audio through this so a future
  // watch-together room can command the dock the same way as the video player.
  const controllerRef = useRef<ReturnType<typeof videoElementController> | null>(null);
  const audioController: PlayerController = useMemo(() => {
    const c = videoElementController(() => audioRef.current, () => 0);
    controllerRef.current = c;
    return c;
  }, []);
  useEffect(() => () => controllerRef.current?.dispose(), []);
  const [stream, setStream] = useState<StreamStart | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [now, setNow] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  // Drives the conditional id={...} so React reassigns id="mh-dock-audio" to
  // whichever element is active after a swap. Mirrors activeRef for render.
  const [activeKey, setActiveKey] = useState<"A" | "B">("A");

  // Resolve the active / idle physical element from the current pointer.
  const getActive = useCallback(
    () => (activeRef.current === "A" ? audioARef.current : audioBRef.current),
    [],
  );
  const getIdle = useCallback(
    () => (activeRef.current === "A" ? audioBRef.current : audioARef.current),
    [],
  );
  // Flip the active pointer, hand the dock-audio id to the new active element
  // before anything reads it, and keep audioRef pointed at it. Synchronous so
  // a getElementById("mh-dock-audio") caller never resolves the wrong element.
  const swapActive = useCallback(() => {
    const oldKey = activeRef.current;
    const newKey: "A" | "B" = oldKey === "A" ? "B" : "A";
    const oldEl = oldKey === "A" ? audioARef.current : audioBRef.current;
    const newEl = newKey === "A" ? audioARef.current : audioBRef.current;
    if (newEl) newEl.id = "mh-dock-audio";
    if (oldEl && oldEl !== newEl) oldEl.removeAttribute("id");
    activeRef.current = newKey;
    audioRef.current = newEl;
    setActiveKey(newKey);
  }, []);
  // media_file_id currently loaded + buffered into the idle element, so the
  // `ended` swap knows the idle buffer is ready and maybePrefetchNext won't
  // re-arm the same target.
  const bufferedTargetRef = useRef<string | null>(null);
  // Set in `ended` just before next() when we hand off to an already-playing
  // swapped element, so the playback effect adopts that element instead of
  // re-sourcing and restarting it.
  const gaplessHandoffRef = useRef<string | null>(null);
  // Keep audioRef on the active element. The dock renders nothing while the
  // queue is empty, so the <audio> elements mount later than this component;
  // ref callbacks see them arrive (an effect keyed on activeKey ran once at
  // mount, saw null, and left audioRef null, so the dock Play button and the
  // media keys did nothing). swapActive() repoints audioRef on a swap.
  const setAudioA = useCallback((el: HTMLAudioElement | null) => {
    audioARef.current = el;
    if (activeRef.current === "A") audioRef.current = el;
  }, []);
  const setAudioB = useCallback((el: HTMLAudioElement | null) => {
    audioBRef.current = el;
    if (activeRef.current === "B") audioRef.current = el;
  }, []);

  // hls.js instances attached to a dock element (transcoded audio). Keyed by
  // element so a swap or a track change tears down exactly the one in use.
  const hlsByElRef = useRef(new Map<HTMLAudioElement, HlsType>());
  const detachHls = useCallback((el: HTMLAudioElement) => {
    const h = hlsByElRef.current.get(el);
    if (!h) return;
    hlsByElRef.current.delete(el);
    try {
      h.destroy();
    } catch {
      // ignore
    }
  }, []);
  useEffect(() => {
    const map = hlsByElRef.current;
    return () => {
      for (const h of map.values()) {
        try {
          h.destroy();
        } catch {
          // ignore
        }
      }
      map.clear();
    };
  }, []);

  const currentItem = currentIndex !== null ? items[currentIndex] ?? null : null;
  const onWatchRoute = pathname?.startsWith("/watch") ?? false;
  const onLoginRoute = pathname?.startsWith("/login") ?? false;
  const queueEmpty = currentIndex === null || items.length === 0;

  const initialResumeRef = useRef<number>(0);
  // Mirror the latest `repeat` value into a ref so the audio `ended`
  // handler — installed in an effect keyed on stream/track — reads the
  // up-to-date mode without re-binding listeners on every toggle.
  const repeatRef = useRef(repeat);
  useEffect(() => {
    repeatRef.current = repeat;
  }, [repeat]);

  // Mirror the live queue snapshot into refs so the prefetch check (driven
  // by the audio `timeupdate` listener, installed in an effect that does
  // not re-bind on every queue change) and the `ended` handler can read
  // the current items / position / shuffle without stale closures.
  const itemsRef = useRef(items);
  const currentIndexRef = useRef(currentIndex);
  const shuffleRef = useRef(shuffle);
  itemsRef.current = items;
  currentIndexRef.current = currentIndex;
  shuffleRef.current = shuffle;

  // Prefetched stream for the upcoming queue item. Holds the target
  // media_file_id alongside the resolved StreamStart so the stream effect
  // and the `ended` handler can reuse it without another network call.
  const prefetchRef = useRef<{ mediaFileId: string; stream: StreamStart } | null>(null);
  // The media_file_id of an in-flight prefetch, so the ~4Hz timeupdate
  // doesn't fire duplicate /api/stream/start calls for the same target.
  const prefetchInFlightRef = useRef<string | null>(null);

  // While the current track plays, prefetch the next track's stream once
  // we're inside the lead window. No-op under shuffle / repeat-one / end of
  // queue (next track not predictable). Recomputes the target each tick, so
  // a queue reorder or next-item change invalidates a stale prefetch.
  // Drop any track armed into the idle element so it can buffer a fresh
  // target. Used when the predicted next item changes or stops being
  // predictable (queue reorder, shuffle toggled on mid-track).
  const resetIdleBuffer = useCallback(() => {
    if (!bufferedTargetRef.current) return;
    const idle = getIdle();
    if (idle) {
      try {
        idle.pause();
      } catch {
        // ignore
      }
      idle.removeAttribute("src");
      idle.preload = "metadata";
      try {
        idle.load();
      } catch {
        // ignore
      }
    }
    bufferedTargetRef.current = null;
  }, [getIdle]);

  const maybePrefetchNext = useCallback(
    (audio: HTMLAudioElement) => {
      const dur = audio.duration;
      if (isNaN(dur) || dur <= 0) return;
      const remaining = dur - audio.currentTime;
      if (remaining <= 0 || remaining > PREFETCH_LEAD_SEC) return;
      const upcoming = predictNextItem(
        itemsRef.current,
        currentIndexRef.current,
        repeatRef.current,
        shuffleRef.current,
      );
      if (!upcoming) {
        // Next track is not predictable (shuffle / repeat-one / end of
        // queue). Release any idle buffer armed for a now-invalid target.
        resetIdleBuffer();
        return;
      }
      const targetId = upcoming.media_file_id;
      // Drop a prefetch (and idle buffer) that no longer points at the
      // upcoming item, e.g. after a queue reorder.
      if (prefetchRef.current && prefetchRef.current.mediaFileId !== targetId) {
        prefetchRef.current = null;
      }
      if (bufferedTargetRef.current && bufferedTargetRef.current !== targetId) {
        resetIdleBuffer();
      }
      // Resolve the upcoming stream URL once.
      if (
        !prefetchRef.current ||
        prefetchRef.current.mediaFileId !== targetId
      ) {
        if (prefetchInFlightRef.current === targetId) return;
        prefetchInFlightRef.current = targetId;
        void apiPost<StreamStart>("/api/stream/start", { file_id: targetId })
          .then((data) => {
            prefetchRef.current = { mediaFileId: targetId, stream: data };
          })
          .catch(() => {
            // Best-effort: a failed prefetch just means `ended` falls back to
            // the inline fetch-then-play path.
          })
          .finally(() => {
            if (prefetchInFlightRef.current === targetId) {
              prefetchInFlightRef.current = null;
            }
          });
        return;
      }
      // URL resolved: arm the idle element so it buffers the next track
      // ahead with preload="auto". This is what makes the `ended` swap
      // gapless: the idle element is already loaded, so we only call play()
      // on it, never re-source it. Volume/mute are applied to both elements
      // by the volume effect, so a swap keeps the level consistent.
      // Only a direct stream can be buffered by setting src; a transcoded
      // (HLS) track starts through hls.js when it becomes current.
      if (
        bufferedTargetRef.current !== targetId &&
        prefetchRef.current.stream.mode === "direct"
      ) {
        const idle = getIdle();
        if (idle) {
          idle.src = prefetchRef.current.stream.url;
          idle.preload = "auto";
          try {
            idle.load();
          } catch {
            // ignore
          }
          bufferedTargetRef.current = targetId;
        }
      }
    },
    [getIdle, resetIdleBuffer],
  );

  // Mirror queuePlaying into a ref so the stream effect can read the
  // persisted value without adding it to the dep array.
  const queuePlayingRef = useRef(queuePlaying);
  useEffect(() => {
    queuePlayingRef.current = queuePlaying;
  }, [queuePlaying]);

  // Shared previous-track rule. A press more than 3s into the current
  // track restarts it; otherwise step the queue back. Referenced by the
  // dock prev button, the Media Session previoustrack handler, and the
  // SW notification prev branch so all three behave identically. Declared
  // here (above those effects) so its dependency arrays can reference it.
  const smartPrev = useCallback(() => {
    const a = audioRef.current;
    if (a && !isNaN(a.currentTime) && a.currentTime > 3) {
      try {
        a.currentTime = 0;
      } catch {
        // ignore
      }
      return;
    }
    prev();
  }, [prev]);

  // Gates auto-play on the very first stream load after a page load.
  // null = not yet decided. On the first stream: honor the persisted
  // queuePlaying value. On every subsequent stream (user-driven skip /
  // advance): always play. This is reset to null only on component mount
  // (i.e., once per page load), so the "don't auto-play on fresh login"
  // guard fires exactly once per session.
  const shouldAutoPlayRef = useRef<boolean | null>(null);
  // Gates the progress-resume lookup to the very first stream after a
  // page load. The first stream may resume mid-track (restoring the
  // persisted queue exactly where it was left). Every user-driven track
  // change after that starts at 0 and never hits the progress endpoint,
  // so clicking a song plays it from the beginning. Reset only on mount.
  const progressResumeUsedRef = useRef(false);
  useEffect(() => {
    setStream(null);
    setStreamError(null);
    initialResumeRef.current = 0;
    if (!currentItem) return;

    const mediaFileId = currentItem.media_file_id;

    // Background-advance fast path. If we prefetched this item's stream
    // while the previous track was still playing, use it directly so no
    // /api/stream/start round trip sits in the gap between tracks (that
    // gap is what stalls the queue on Android with the screen off).
    const pf = prefetchRef.current;
    if (pf && pf.mediaFileId === mediaFileId) {
      prefetchRef.current = null;
      initialResumeRef.current = 0;
      setStream(pf.stream);
      return;
    }

    let cancelled = false;

    (async () => {
      let resumeSec = 0;
      if (!progressResumeUsedRef.current) {
        progressResumeUsedRef.current = true;
        try {
          const p = await apiGet<Progress | null>(
            `/api/library/progress/${mediaFileId}`,
          );
          if (p) {
            const dur = p.duration_sec ?? currentItem.duration_sec;
            const inResumeWindow =
              p.position_sec >= RESUME_MIN_SEC &&
              (dur == null || p.position_sec < dur - RESUME_TAIL_SEC);
            if (inResumeWindow) resumeSec = p.position_sec;
          }
        } catch {
          // No progress is fine; start from 0.
        }
      }
      if (cancelled) return;

      try {
        const body: StreamStartRequest = { file_id: mediaFileId };
        if (resumeSec > 0) body.resume_sec = resumeSec;
        const data = await apiPost<StreamStart>("/api/stream/start", body);
        if (cancelled) return;
        initialResumeRef.current =
          data.mode === "direct" && resumeSec > 0 ? resumeSec : 0;
        setStream(data);
      } catch (err) {
        if (cancelled) return;
        setStreamError(err instanceof Error ? err.message : "Failed to start stream");
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentItem?.media_file_id]);

  // Track-play log accounting. We write a `track_plays` row when the
  // current track ends naturally (always) and when the user advances
  // away from a track they had been listening to for at least 30s
  // (counts as a skip with progress). `playLoggedRef` keeps us from
  // double-writing if both the ended-handler and the cleanup-skip
  // path fire for the same track.
  const playLoggedRef = useRef<boolean>(false);
  useEffect(() => {
    playLoggedRef.current = false;
  }, [currentItem?.media_file_id]);

  useEffect(() => {
    const audio = getActive();
    if (!audio || !stream) return;

    // Gapless handoff: `ended` already swapped to this (previously idle)
    // element and called play() on its prefetched, fully-buffered src. Do
    // NOT re-source or re-play it — that would rebuffer and restart the
    // track from 0, defeating gapless. Adopt it: bind listeners + heartbeat
    // below and sync the UI from the element's live state. Every other
    // (non-gapless) track start sets src on the active element as before.
    const isGaplessHandoff =
      gaplessHandoffRef.current !== null &&
      gaplessHandoffRef.current === currentItem?.media_file_id;
    if (isGaplessHandoff) {
      gaplessHandoffRef.current = null;
      if (!isNaN(audio.duration)) setDuration(audio.duration);
      setNow(isNaN(audio.currentTime) ? 0 : audio.currentTime);
      setIsPlaying(!audio.paused);
      if (!audio.paused) {
        shouldAutoPlayRef.current = true;
        setPlaying(true);
      }
    }
    // Transcoded audio is HLS. Chrome's <audio> only plays HLS natively in
    // recent versions and Firefox not at all, so play it through hls.js
    // (MSE) like the video player does; native HLS is the fallback.
    let disposed = false;
    const useHls = !isGaplessHandoff && stream.mode === "hls";
    if (!isGaplessHandoff && !useHls) {
      audio.src = stream.url;
    }

    const trackId = currentItem?.track_id;
    const trackDurationSec = currentItem?.duration_sec ?? null;

    const logPlay = (msPlayed: number, completed: boolean) => {
      if (!trackId) return;
      if (playLoggedRef.current) return;
      playLoggedRef.current = true;
      void apiPost("/api/library/track-plays", {
        track_id: trackId,
        ms_played: Math.max(0, Math.floor(msPlayed)),
        completed,
      }).catch(() => {
        // best-effort; the queue keeps going regardless
      });
    };

    const onLoadedMetadata = () => {
      const seek = initialResumeRef.current;
      if (seek > 0 && !isNaN(audio.duration) && audio.duration > 0) {
        try {
          audio.currentTime = seek;
        } catch {
          // ignore
        }
        initialResumeRef.current = 0;
      }
      if (!isNaN(audio.duration)) setDuration(audio.duration);
    };
    const onTimeUpdate = () => {
      if (!isNaN(audio.currentTime)) setNow(audio.currentTime);
      maybePrefetchNext(audio);
    };
    const onPlay = () => {
      setIsPlaying(true);
      // Once the user is playing, mark every subsequent track to auto-play.
      shouldAutoPlayRef.current = true;
      setPlaying(true);
    };
    const onPause = () => {
      setIsPlaying(false);
      setPlaying(false);
    };
    const onEnded = () => {
      setIsPlaying(false);
      const ms = !isNaN(audio.currentTime) ? audio.currentTime * 1000 : 0;
      const durationMs = (trackDurationSec ?? Math.floor(audio.duration || 0)) * 1000;
      const completed =
        durationMs > 0 ? ms > durationMs * PLAY_LOG_COMPLETE_FRACTION : true;
      logPlay(ms, completed);
      // repeat=one: snap back to the head and play this track again. The
      // play-row was already logged above, so a single completion counts
      // once per natural finish even when looped.
      if (repeatRef.current === "one") {
        try {
          audio.currentTime = 0;
          const p = audio.play();
          if (p && typeof p.catch === "function") p.catch(() => { /* ignore */ });
        } catch {
          next();
        }
        playLoggedRef.current = false;
        return;
      }
      const upcoming = predictNextItem(
        itemsRef.current,
        currentIndexRef.current,
        repeatRef.current,
        shuffleRef.current,
      );
      const idle = getIdle();

      // Primary gapless path. The idle element is already buffered with the
      // predicted-next track, so switch elements instead of re-sourcing one:
      // hand the dock-audio id to the new active element, play it (no
      // rebuffer = no inter-track gap), reset the old active element to serve
      // as the next preload buffer, then advance the queue. The stream effect
      // re-runs for the new item, sees gaplessHandoffRef, and adopts the
      // already-playing element rather than re-sourcing it.
      if (
        upcoming &&
        idle &&
        bufferedTargetRef.current === upcoming.media_file_id &&
        prefetchRef.current?.mediaFileId === upcoming.media_file_id
      ) {
        gaplessHandoffRef.current = upcoming.media_file_id;
        swapActive();
        const nowActive = getActive();
        if (nowActive) {
          try {
            const p = nowActive.play();
            if (p && typeof p.catch === "function") p.catch(() => { /* ignore */ });
          } catch {
            // If play fails, drop the handoff flag so the stream effect's
            // normal src-then-play path recovers on the queue advance.
            gaplessHandoffRef.current = null;
          }
        }
        // Reset the element we swapped away from so it can preload the next.
        const nowIdle = getIdle();
        if (nowIdle) {
          try {
            nowIdle.pause();
          } catch {
            // ignore
          }
          nowIdle.removeAttribute("src");
          nowIdle.preload = "metadata";
          try {
            nowIdle.load();
          } catch {
            // ignore
          }
        }
        bufferedTargetRef.current = null;
        next();
        return;
      }

      // Fallback (shuffle / unpredictable next / no ready idle buffer): keep
      // the single-element behavior. If only the stream URL was prefetched
      // (no buffered idle element), set src on the active element and play so
      // a screen-off advance still moves without an inline /api/stream/start
      // round trip. Then advance the queue; the stream effect re-sources and
      // rebinds on the active element as before.
      const ready = prefetchRef.current;
      if (
        upcoming &&
        ready &&
        ready.mediaFileId === upcoming.media_file_id &&
        ready.stream.mode === "direct"
      ) {
        try {
          audio.src = ready.stream.url;
          const p = audio.play();
          if (p && typeof p.catch === "function") p.catch(() => { /* ignore */ });
        } catch {
          // Fall through to the queue advance; the stream effect rebinds.
        }
      }
      next();
    };

    audio.addEventListener("loadedmetadata", onLoadedMetadata);
    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);

    // Decide whether to auto-play this track. Skipped on a gapless handoff:
    // the swapped element is already playing, so re-issuing play() here is
    // redundant (and the src was never reset).
    // First stream since page load: check the persisted queue state.
    //   playing: true  = user was mid-play when the app closed → resume.
    //   playing: false = fresh login or was paused → don't auto-play.
    // All subsequent streams (user-driven skip / track advance): always play.
    let autoPlay: boolean;
    if (shouldAutoPlayRef.current === null) {
      autoPlay = queuePlayingRef.current;
      shouldAutoPlayRef.current = autoPlay;
    } else {
      autoPlay = true;
    }

    const startPlayback = () => {
      const playPromise = audio.play();
      if (playPromise && typeof playPromise.catch === "function") {
        playPromise.catch(() => {
          // Autoplay can be blocked by the browser. The user can hit Play.
        });
      }
    };

    if (useHls) {
      void import("hls.js").then(({ default: Hls }) => {
        if (disposed) return;
        if (!Hls.isSupported()) {
          if (audio.canPlayType("application/vnd.apple.mpegurl")) {
            audio.src = stream.url;
            if (autoPlay) startPlayback();
          } else {
            setStreamError("This browser can't play transcoded audio.");
          }
          return;
        }
        detachHls(audio);
        const hls = new Hls({ maxBufferLength: 30, enableWorker: true });
        hlsByElRef.current.set(audio, hls);
        hls.on(Hls.Events.ERROR, (_event, data) => {
          if (disposed || !data.fatal) return;
          detachHls(audio);
          setStreamError(`Playback error: ${data.type}/${data.details}`);
        });
        hls.loadSource(stream.url);
        hls.attachMedia(audio);
        if (autoPlay) startPlayback();
      }).catch(() => {
        if (!disposed) setStreamError("Failed to load the audio player");
      });
    } else if (autoPlay && !isGaplessHandoff) {
      startPlayback();
    }

    const send = (position: number) => {
      const dur =
        !isNaN(audio.duration) && audio.duration > 0
          ? Math.floor(audio.duration)
          : (stream.duration_sec ?? null);
      void apiPut<Progress>(
        `/api/library/progress/${stream.media_file_id}`,
        {
          position_sec: Math.floor(position),
          duration_sec: dur,
        },
      ).catch(() => {
        // swallow; heartbeat is best-effort
      });
    };

    const tick = () => {
      if (!audio || audio.paused || audio.ended) return;
      if (isNaN(audio.currentTime)) return;
      send(audio.currentTime);
    };

    const heartbeat = window.setInterval(tick, HEARTBEAT_MS);

    return () => {
      disposed = true;
      window.clearInterval(heartbeat);
      audio.removeEventListener("loadedmetadata", onLoadedMetadata);
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      if (audio && !isNaN(audio.currentTime) && audio.currentTime > 0) {
        send(audio.currentTime);
      }
      // Skip-with-progress: cleanup runs when the user advances away
      // from the current track before it ended naturally. Log a play
      // row when the listener committed at least PLAY_LOG_SKIP_MIN_SEC.
      if (
        !playLoggedRef.current &&
        !audio.ended &&
        !isNaN(audio.currentTime) &&
        audio.currentTime >= PLAY_LOG_SKIP_MIN_SEC
      ) {
        const ms = audio.currentTime * 1000;
        const durationMs =
          (trackDurationSec ?? Math.floor(audio.duration || 0)) * 1000;
        const completed =
          durationMs > 0 ? ms > durationMs * PLAY_LOG_COMPLETE_FRACTION : false;
        logPlay(ms, completed);
      }
      try {
        audio.pause();
      } catch {
        // ignore
      }
      detachHls(audio);
      audio.removeAttribute("src");
      try {
        audio.load();
      } catch {
        // ignore
      }
    };
  }, [stream, next, setPlaying, currentItem?.track_id, currentItem?.duration_sec, currentItem?.media_file_id, maybePrefetchNext, getActive, getIdle, swapActive, detachHls]);

  // Media Session metadata. Drives lock-screen, OS media widgets, and
  // Bluetooth AVRCP on car head units (title, artist, album, artwork).
  // Re-runs whenever the current item changes.
  useEffect(() => {
    if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
    if (!currentItem) {
      navigator.mediaSession.metadata = null;
      navigator.mediaSession.playbackState = "none";
      return;
    }
    const artwork = currentItem.cover_path
      ? [
          { src: currentItem.cover_path, sizes: "96x96", type: "image/jpeg" },
          { src: currentItem.cover_path, sizes: "256x256", type: "image/jpeg" },
          { src: currentItem.cover_path, sizes: "512x512", type: "image/jpeg" },
        ]
      : [];
    navigator.mediaSession.metadata = new MediaMetadata({
      title: currentItem.title ?? "",
      artist: currentItem.artist_name ?? "",
      album: currentItem.album_title ?? "",
      artwork,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    currentItem?.media_file_id,
    currentItem?.title,
    currentItem?.artist_name,
    currentItem?.album_title,
    currentItem?.cover_path,
  ]);

  // Mirror play/pause state to the OS so the lock screen and head unit
  // show the correct transport icon.
  useEffect(() => {
    if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
    navigator.mediaSession.playbackState = isPlaying ? "playing" : "paused";
  }, [isPlaying]);

  // Action handlers for hardware media keys, lock-screen buttons, and
  // Bluetooth car controls (steering wheel, head unit). The previoustrack
  // 3s rule matches iOS / native player behavior: a press more than 3s
  // into the track restarts the current track; otherwise advance to the
  // prior queue item.
  //
  // Deliberately limited to play / pause / previoustrack / nexttrack /
  // seekto. Android's lock-screen widget has limited button slots, and
  // when seekbackward / seekforward are registered the OS heuristic
  // tends to pick those over prev/next, leaving the lock screen without
  // prev/next buttons. seekto + setPositionState still drives the scrub
  // bar correctly. If we want -10s / +30s buttons later, gate them on
  // a podcast-only context.
  useEffect(() => {
    if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
    const ms = navigator.mediaSession;

    const setHandler = (
      action: MediaSessionAction,
      handler: MediaSessionActionHandler | null,
    ) => {
      try {
        ms.setActionHandler(action, handler);
      } catch {
        // Some actions are not supported in every browser; ignore.
      }
    };

    setHandler("play", () => {
      const a = audioRef.current;
      if (!a) return;
      const p = a.play();
      if (p && typeof p.catch === "function") p.catch(() => { /* ignore */ });
    });
    setHandler("pause", () => {
      const a = audioRef.current;
      if (a) a.pause();
    });
    setHandler("previoustrack", () => {
      // eslint-disable-next-line no-console
      console.log("[mediaSession] previoustrack");
      smartPrev();
    });
    setHandler("nexttrack", () => {
      // eslint-disable-next-line no-console
      console.log("[mediaSession] nexttrack");
      next();
    });
    setHandler("seekto", (details) => {
      const a = audioRef.current;
      if (!a || details?.seekTime == null) return;
      try {
        if (details.fastSeek && typeof a.fastSeek === "function") {
          a.fastSeek(details.seekTime);
        } else {
          a.currentTime = details.seekTime;
        }
      } catch { /* ignore */ }
    });

    // Explicitly null out the actions we used to register so a stale
    // browser-cached handler from the prior bundle doesn't keep
    // outranking prev/next on the lock screen.
    setHandler("seekbackward", null);
    setHandler("seekforward", null);
    setHandler("stop", null);

    return () => {
      setHandler("play", null);
      setHandler("pause", null);
      setHandler("previoustrack", null);
      setHandler("nexttrack", null);
      setHandler("seekto", null);
    };
  }, [next, smartPrev]);

  // Push position state to the OS so the lock-screen scrubber and car
  // progress display reflect reality. The Math.floor on `now` throttles
  // updates to roughly 1Hz so we don't flood the OS bridge.
  const flooredNow = Math.floor(now);
  useEffect(() => {
    if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
    if (!duration || isNaN(duration) || duration <= 0) return;
    const safePos = Math.max(0, Math.min(now, duration));
    try {
      navigator.mediaSession.setPositionState({
        duration,
        position: safePos,
        playbackRate: audioRef.current?.playbackRate ?? 1,
      });
    } catch {
      // setPositionState throws on invalid combinations; swallow.
    }
    // `now` is referenced for the actual position write but the effect
    // is keyed on flooredNow so it only fires once per second.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [duration, flooredNow]);

  // Service Worker notification fallback. Additive to the Media Session
  // wiring above; Firefox Android never surfaces prev/next via the
  // notification panel from Media Session alone, so we render our own
  // notification with explicit transport buttons. Browsers that do
  // surface Media Session natively (Chrome) get a redundant but harmless
  // second surface.
  useEffect(() => {
    if (!currentItem) {
      void hideMediaNotification();
      return;
    }
    void showMediaNotification({
      title: currentItem.title ?? "",
      artist: currentItem.artist_name ?? "",
      album: currentItem.album_title ?? "",
      artworkUrl: currentItem.cover_path ?? null,
      isPlaying,
      mediaFileId: currentItem.media_file_id,
    });
  }, [
    currentItem?.media_file_id,
    currentItem?.title,
    currentItem?.artist_name,
    currentItem?.album_title,
    currentItem?.cover_path,
    isPlaying,
    currentItem,
  ]);

  // Dispatch SW-notification action clicks back into the dock controls.
  // The 'prev' branch mirrors the Media Session previoustrack rule:
  // restart current if past 3s, otherwise step the queue back.
  useEffect(() => {
    const unsubscribe = subscribeToNotificationActions((action) => {
      if (action === "prev") {
        smartPrev();
        return;
      }
      if (action === "play") {
        const a = audioRef.current;
        if (!a) return;
        if (a.paused) {
          const p = a.play();
          if (p && typeof p.catch === "function") p.catch(() => { /* ignore */ });
        } else {
          a.pause();
        }
        return;
      }
      if (action === "next") {
        next();
      }
    });
    return unsubscribe;
  }, [next, smartPrev]);

  // One-shot notification permission prompt. The first non-null
  // currentItem is downstream of an explicit user click (Play, or a
  // queue mutation that originated from a click) and counts as a user
  // gesture in Firefox/Chrome. Ref-gates so reload doesn't re-prompt.
  const permissionRequestedRef = useRef(false);
  useEffect(() => {
    if (permissionRequestedRef.current) return;
    if (!currentItem) return;
    permissionRequestedRef.current = true;
    void requestNotificationPermission();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentItem?.media_file_id]);

  // Pause-on-login. The dock element itself returns null below when on
  // /login, but the <audio> tag stays mounted at the root through the
  // route change for a few render cycles and would otherwise keep
  // playing through a session-expiry redirect. Explicitly pause and
  // wipe the queue so a fresh login starts clean.
  useEffect(() => {
    if (pathname !== "/login") return;
    for (const audio of [audioARef.current, audioBRef.current]) {
      if (!audio) continue;
      try {
        audio.pause();
      } catch {
        // ignore
      }
    }
    clear();
  }, [pathname, clear]);

  // Restore device-local volume + mute on mount. Volume is intentionally
  // not part of the server-synced queue state; it lives in localStorage.
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

  // Apply volume + mute to BOTH dock <audio> elements so the level is
  // consistent across an A/B swap (the idle preload buffer needs the same
  // level as the active element). Re-applies when a new stream loads so the
  // elements honor the persisted level.
  useEffect(() => {
    for (const a of [audioARef.current, audioBRef.current]) {
      if (!a) continue;
      a.volume = volume;
      a.muted = muted;
    }
  }, [volume, muted, stream]);

  // Reserve space for the fixed dock so it never covers page content (the
  // Home "Continue Watching" heading, the bottom of every page). Mirror the
  // exact visibility of the `.mini` bar below: shown only with a non-empty
  // queue and off the /login and /watch routes. The matching bottom padding
  // is applied by the body[data-dock="1"] rule in globals.css, sized from
  // the same tokens the dock uses so it stays pixel-accurate per breakpoint.
  const dockBarVisible = !queueEmpty && !onLoginRoute && !onWatchRoute;
  useEffect(() => {
    const prev = document.body.getAttribute("data-dock");
    if (dockBarVisible) {
      document.body.setAttribute("data-dock", "1");
    } else {
      document.body.removeAttribute("data-dock");
    }
    return () => {
      if (prev === null) document.body.removeAttribute("data-dock");
      else document.body.setAttribute("data-dock", prev);
    };
  }, [dockBarVisible]);

  if (queueEmpty) return null;
  // onWatchRoute: dock chrome hides via the conditional in JSX,
  // but the <audio> stays mounted so playback survives the route change.

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    // Route through the controller (item 8c). Same effect as before.
    if (audio.paused) {
      audioController.play();
    } else {
      audioController.pause();
    }
  };

  // Scrub. Derive a 0..1 ratio from where the pointer landed on the bar
  // and assign audio.currentTime. Tracking pointermove while down gives
  // click-and-drag seeking.
  const seekToClientX = (clientX: number) => {
    const bar = barRef.current;
    const audio = audioRef.current;
    if (!bar || !audio || !duration || duration <= 0) return;
    const rect = bar.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const t = ratio * duration;
    // Controller.seek takes a source second; the dock is direct-play so source
    // time == element time (item 8c). Same as the prior audio.currentTime = t.
    audioController.seek(t);
    setNow(t);
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

  const onVolumeChange = (v: number) => {
    const clamped = Math.max(0, Math.min(1, v));
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

  // The shared track menu (3-dot) acts on the current queue item's album and
  // artist. Items whose id is missing are disabled inside the menu.
  const currentAlbumId = currentItem?.album_id ?? null;
  const currentArtistId = currentItem?.artist_id ?? null;

  const artistName = currentItem?.artist_name?.trim() || null;
  const albumTitle = currentItem?.album_title?.trim() || null;
  const artistHref = currentItem?.artist_id
    ? `/music/artists/${currentItem.artist_id}`
    : null;
  const albumHref = currentItem?.album_id
    ? `/music/${currentItem.album_id}`
    : null;
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(currentItem?.title ?? ""),
    ["--ph" as never]: String(hueFromString(currentItem?.title ?? "")),
  };
  const expandHref = currentItem ? `/watch/${currentItem.media_file_id}` : "/";
  const pct = duration > 0 ? Math.min(100, (now / duration) * 100) : 0;

  // Right before navigating to /watch we stash the current playhead so
  // the watch page can skip the resume prompt and start at the same
  // position. The dock's <audio> still unmounts on the route change
  // (causing a brief gap), but the prompt+pause-then-restart user flow
  // is gone.
  const stashExpandHint = () => {
    if (!currentItem) return;
    try {
      const audio = audioRef.current;
      const pos = audio && !isNaN(audio.currentTime)
        ? Math.max(0, Math.floor(audio.currentTime))
        : 0;
      sessionStorage.setItem(
        "mh:expand",
        JSON.stringify({
          media_file_id: currentItem.media_file_id,
          position_sec: pos,
          ts: Date.now(),
        }),
      );
    } catch {
      // best-effort; private mode / disabled storage just means the
      // resume prompt fires as it does today.
    }
  };
  const sourceBadge = stream
    ? stream.mode === "direct"
      ? "Direct"
      : "Transcode"
    : "Audio";

  return (
    <>
      {!onLoginRoute && !onWatchRoute && (
      <div className="mini" style={tint} role="region" aria-label="Mini player">
        <div className="left" style={{ minWidth: 0 }}>
          <Link
            href={expandHref}
            className="thumb"
            aria-label={`Open player${currentItem?.title ? ` for ${currentItem.title}` : ""}`}
            onClick={stashExpandHint}
          >
            <div className="keyart-mini" />
            {currentItem?.cover_path ? (
              <img
                src={currentItem.cover_path}
                alt={currentItem.title ?? ""}
              />
            ) : null}
          </Link>
          <div className="body">
            <Link
              href={expandHref}
              className="t"
              onClick={stashExpandHint}
              style={{ display: "block", color: "inherit", textDecoration: "none" }}
            >
              {currentItem?.title ?? "Nothing playing"}
            </Link>
            {artistName || albumTitle ? (
              <div className="s">
                {artistName ? (
                  artistHref ? (
                    <SubtitleLink href={artistHref}>{artistName}</SubtitleLink>
                  ) : (
                    <span>{artistName}</span>
                  )
                ) : null}
                {artistName && albumTitle ? " • " : null}
                {albumTitle ? (
                  albumHref ? (
                    <SubtitleLink href={albumHref}>{albumTitle}</SubtitleLink>
                  ) : (
                    <span>{albumTitle}</span>
                  )
                ) : null}
              </div>
            ) : streamError ? (
              <div className="s" style={{ color: "var(--danger)" }}>
                {streamError}
              </div>
            ) : null}
          </div>
        </div>

        <div className="center">
          <div className="scrub">
            <span>{formatDuration(now)}</span>
            <div
              className="bar"
              ref={barRef}
              role="slider"
              tabIndex={0}
              aria-label="Seek"
              aria-valuemin={0}
              aria-valuemax={duration > 0 ? Math.floor(duration) : 0}
              aria-valuenow={Math.floor(now)}
              onPointerDown={onScrubPointerDown}
            >
              <div style={{ width: `${pct}%` }} />
            </div>
            <span>{duration > 0 ? formatDuration(duration) : "—"}</span>
          </div>
        </div>

        <div className="right">
          <span className="source-badge" aria-label="Stream source">
            {sourceBadge}
          </span>
          <button
            type="button"
            onClick={() => setShuffle(!shuffle)}
            aria-label={shuffle ? "Shuffle on" : "Shuffle off"}
            aria-pressed={shuffle}
            className="icbtn"
            style={{
              color: shuffle ? "var(--warning)" : undefined,
              opacity: shuffle ? 1 : 0.55,
            }}
          >
            <ShuffleIcon />
          </button>
          <button
            type="button"
            onClick={smartPrev}
            aria-label="Previous"
            className="icbtn"
          >
            <PrevIcon />
          </button>
          <button
            type="button"
            onClick={togglePlay}
            aria-label={isPlaying ? "Pause" : "Play"}
            className="icbtn play"
          >
            {isPlaying ? <PauseIcon /> : <PlayIcon />}
          </button>
          <button
            type="button"
            onClick={next}
            aria-label="Next"
            className="icbtn"
          >
            <NextIcon />
          </button>
          <button
            type="button"
            onClick={() => {
              const order: RepeatMode[] = ["off", "all", "one"];
              const i = order.indexOf(repeat);
              setRepeat(order[(i + 1) % order.length]);
            }}
            aria-label={`Repeat: ${repeat}`}
            aria-pressed={repeat !== "off"}
            className="icbtn"
            style={{
              color: repeat !== "off" ? "var(--warning)" : undefined,
              opacity: repeat !== "off" ? 1 : 0.55,
              position: "relative",
            }}
          >
            <RepeatIcon />
            {repeat === "one" ? (
              <span
                aria-hidden
                style={{
                  position: "absolute",
                  right: 2,
                  top: 1,
                  fontSize: 8,
                  fontFamily: "var(--mono)",
                  lineHeight: 1,
                  fontWeight: 700,
                }}
              >
                1
              </span>
            ) : null}
          </button>
          <button
            type="button"
            onClick={toggleMute}
            aria-label={muted ? "Unmute" : "Mute"}
            aria-pressed={muted}
            className="icbtn"
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
          <PlayerTrackMenu
            albumId={currentAlbumId}
            artistId={currentArtistId}
            placement="up"
            buttonClassName="icbtn"
            iconSize={16}
          />
          <button
            type="button"
            onClick={() => setPanelOpen(true)}
            aria-label="Open queue"
            className="icbtn"
          >
            <QueueIcon />
          </button>
        </div>

      </div>
      )}

      {/* A/B double buffer. Both elements stay mounted unconditionally (per
          the 2026-05-01 dock-audio ADR). Only the active element carries
          id="mh-dock-audio"; swapActive() reassigns it on every swap so the
          dock-audio singleton contract keeps resolving the element currently
          producing sound. The active default preload stays "metadata"; the
          idle element is bumped to "auto" imperatively when armed as the
          next-track buffer. */}
      <audio
        id={activeKey === "A" ? "mh-dock-audio" : undefined}
        ref={setAudioA}
        preload="metadata"
        style={{ display: "none" }}
      />
      <audio
        id={activeKey === "B" ? "mh-dock-audio" : undefined}
        ref={setAudioB}
        preload="metadata"
        style={{ display: "none" }}
      />

      {!onLoginRoute && <QueuePanel open={panelOpen} onClose={() => setPanelOpen(false)} />}
    </>
  );
}

function PrevIcon() {
  return <Icon icon={SkipBack} size={16} fill />;
}
function NextIcon() {
  return <Icon icon={SkipForward} size={16} fill />;
}
function PlayIcon() {
  return <Icon icon={Play} size={14} fill />;
}
function PauseIcon() {
  return <Icon icon={Pause} size={14} fill />;
}
function ShuffleIcon() {
  return <Icon icon={Shuffle} size={16} />;
}
function RepeatIcon() {
  return <Icon icon={Repeat} size={16} />;
}
function QueueIcon() {
  return <Icon icon={ListMusic} size={16} />;
}
function VolumeIcon() {
  return <Icon icon={Volume2} size={16} />;
}
function MuteIcon() {
  return <Icon icon={VolumeX} size={16} />;
}

function SubtitleLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  const [hover, setHover] = useState(false);
  return (
    <Link
      href={href}
      style={{
        color: "var(--ink-2)",
        textDecoration: hover ? "underline" : "none",
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {children}
    </Link>
  );
}
