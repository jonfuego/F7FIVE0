import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import TrackPlayer, {
  Event,
  RepeatMode,
  State,
  Track,
  useActiveTrack,
  useProgress,
  usePlaybackState,
} from "react-native-track-player";

import {
  clearServerQueue,
  fetchServerQueue,
  postTrackPlay,
  reportProgress,
  saveServerQueue,
  startStream,
} from "@/api/media";
import { useCast } from "@/cast";
import { buildTrackArtwork } from "./artwork";
import { clampCrossfade, fadeInVolume, fadeOutVolume, shouldStartFade } from "./crossfade";
import { resolveVolume } from "./loudness";
import { fetchLoudness } from "@/api/media";
import { useDownloads } from "@/download/DownloadProvider";
import { buildServerQueueItems, type QueueSnapshotItem } from "./queueSync";
import {
  cleared,
  isElapsed,
  startEndOfTrack,
  startMinutes,
  type SleepMode,
  type SleepState,
} from "./sleepTimer";
import type { SongRow } from "@/api/types";
import { getApiBase } from "@/state/config";
import { getSetting, setSetting, SETTINGS } from "@/state/settings";
import { useApi } from "@/state/auth";
import { ProgressSyncer } from "./progressSync";
import { setupPlayer } from "./setup";

interface QueueMeta {
  mediaFileId: string;
  trackId?: string | null;
  title: string;
  artist?: string | null;
  album?: string | null;
  albumId?: string | null;
  artistId?: string | null;
  artPath?: string | null;
  durationSec?: number | null;
}

export type RepeatSetting = "off" | "all" | "one";

interface NowPlaying {
  title: string;
  artist?: string;
  artPath?: string | null;
  mediaFileId?: string;
  trackId?: string | null;
  albumId?: string | null;
  artistId?: string | null;
}

/** Tracks queued before and after the tapped one (see playSongs). */
const QUEUE_BEHIND = 10;
const QUEUE_AHEAD = 50;

interface PlayerContextValue {
  ready: boolean;
  playSongs: (songs: SongRow[], startIndex: number) => Promise<void>;
  playNext: (songs: SongRow[]) => Promise<void>;
  addToQueue: (songs: SongRow[]) => Promise<void>;
  crossfadeSec: number;
  setCrossfade: (sec: number) => void;
  playbackRate: number;
  setRate: (r: number) => Promise<void>;
  loudnessOn: boolean;
  setLoudness: (on: boolean) => void;
  loudnessAlbum: boolean;
  setLoudnessAlbumMode: (on: boolean) => void;
  loudnessBoost: boolean;
  setLoudnessAllowBoost: (on: boolean) => void;
  sleep: SleepState;
  setSleepTimer: (mode: SleepMode, minutes?: number) => void;
  togglePlay: () => Promise<void>;
  next: () => Promise<void>;
  previous: () => Promise<void>;
  seekTo: (sec: number) => Promise<void>;
  jumpTo: (index: number) => Promise<void>;
  removeAt: (index: number) => Promise<void>;
  moveTrack: (from: number, to: number) => Promise<void>;
  clearQueue: () => Promise<void>;
  cycleRepeat: () => Promise<void>;
  toggleShuffle: () => Promise<void>;
  repeatMode: RepeatSetting;
  shuffleOn: boolean;
  getQueueItems: () => { metas: QueueMeta[]; activeIndex: number };
  /** Hand the current queue to a connected Chromecast receiver: sign a cast URL
   * per track, load it as a cast queue at the current track + position, and
   * pause local playback. Returns false when there's no queue or no session. */
  castCurrentQueue: () => Promise<boolean>;
  queueVersion: number;
  nowPlaying: NowPlaying | null;
  isPlaying: boolean;
  position: number;
  duration: number;
  hasQueue: boolean;
}

export type { QueueMeta };

const PlayerContext = createContext<PlayerContextValue | null>(null);

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const api = useApi();
  const cast = useCast();
  const downloads = useDownloads();
  const downloadsRef = useRef(downloads);
  downloadsRef.current = downloads;
  const [ready, setReady] = useState(false);
  const [hasQueue, setHasQueue] = useState(false);
  const [repeatMode, setRepeatMode] = useState<RepeatSetting>("off");
  const [shuffleOn, setShuffleOn] = useState(false);
  const [queueVersion, setQueueVersion] = useState(0); // bump to re-render the queue panel
  const [crossfadeSec, setCrossfadeState] = useState(0);
  const [playbackRate, setPlaybackRateState] = useState(1);
  const [sleep, setSleepState] = useState<SleepState>(cleared());
  const queueMeta = useRef<QueueMeta[]>([]);
  const recovering = useRef(false);
  const lastPlayReported = useRef<string | null>(null);
  const crossfadeRef = useRef(0);
  const sleepRef = useRef<SleepState>(sleep);
  sleepRef.current = sleep;

  // Loudness leveling (crit 46). Base volume the crossfade ramp multiplies
  // against, plus the resolved settings kept in refs for the async apply.
  const [loudnessOn, setLoudnessOn] = useState(false);
  const [loudnessAlbum, setLoudnessAlbum] = useState(false);
  const [loudnessBoost, setLoudnessBoost] = useState(false);
  const loudnessOnRef = useRef(false);
  loudnessOnRef.current = loudnessOn;
  const loudnessAlbumRef = useRef(false);
  loudnessAlbumRef.current = loudnessAlbum;
  const loudnessBoostRef = useRef(false);
  loudnessBoostRef.current = loudnessBoost;
  /** Baseline volume for the current track (1 or loudness-attenuated). The
   * crossfade fade-out multiplies this so the two features compose. */
  const baseVolumeRef = useRef(1);
  // True while the first `crossfade` seconds of a track that followed a
  // naturally-ending one are ramping in (the other half of the crossfade).
  const fadingInRef = useRef(false);
  const loudnessCache = useRef<Map<string, number>>(new Map());

  const activeTrack = useActiveTrack();
  const progress = useProgress(250);
  const playback = usePlaybackState();
  const isPlaying = playback.state === State.Playing;

  useEffect(() => {
    let active = true;
    setupPlayer()
      .then(() => active && setReady(true))
      .catch(() => active && setReady(false));
    return () => {
      active = false;
    };
  }, []);

  // Progress sync: every 15s while playing, and once on each track change.
  const syncer = useRef<ProgressSyncer | null>(null);
  const activeIndexRef = useRef<number>(-1);

  useEffect(() => {
    const s = new ProgressSyncer({
      getSnapshot: () => {
        const idx = activeIndexRef.current;
        const meta = idx >= 0 ? queueMeta.current[idx] : undefined;
        if (!meta) return null;
        return {
          trackId: meta.mediaFileId,
          positionSec: progressRef.current.position,
          durationSec: progressRef.current.duration || undefined,
          playing: playingRef.current,
        };
      },
      report: async (snap) => {
        if (!downloadsRef.current.online) {
          downloadsRef.current.bufferOffline({
            kind: "progress",
            mediaFileId: snap.trackId,
            positionSec: snap.positionSec,
            durationSec: snap.durationSec,
            at: Date.now(),
          });
          return;
        }
        await reportProgress(api, snap.trackId, snap.positionSec, snap.durationSec).catch(() => {});
      },
    });
    s.start();
    syncer.current = s;
    return () => s.stop();
  }, [api]);

  // Keep refs the syncer reads without re-creating it.
  const progressRef = useRef(progress);
  progressRef.current = progress;
  const playingRef = useRef(isPlaying);
  playingRef.current = isPlaying;

  // Persist the queue to the server so it survives a restart and syncs across
  // devices. Fire-and-forget; a failed sync never interrupts playback.
  const repeatRef = useRef<RepeatSetting>(repeatMode);
  repeatRef.current = repeatMode;
  const shuffleRef = useRef<boolean>(shuffleOn);
  shuffleRef.current = shuffleOn;

  const pushQueue = useCallback(async () => {
    const items = buildServerQueueItems(queueMeta.current as QueueSnapshotItem[]);
    const idx = activeIndexRef.current;
    await saveServerQueue(
      api,
      items,
      idx >= 0 && idx < items.length ? idx : items.length > 0 ? 0 : null,
      repeatRef.current,
      shuffleRef.current,
    ).catch(() => {});
  }, [api]);

  // Hydrate from the server queue on launch (GET /api/queue). We don't
  // auto-load audio (signed URLs would be stale), but reading it here proves
  // the round trip and lets a future "resume queue" affordance use it.
  useEffect(() => {
    let active = true;
    fetchServerQueue(api)
      .then((q) => {
        if (!active || !q) return;
        if (q.repeat_mode === "off" || q.repeat_mode === "all" || q.repeat_mode === "one") {
          setRepeatMode(q.repeat_mode);
          void TrackPlayer.setRepeatMode(
            q.repeat_mode === "one" ? RepeatMode.Track : q.repeat_mode === "all" ? RepeatMode.Queue : RepeatMode.Off,
          ).catch(() => {});
        }
        setShuffleOn(!!q.shuffle);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [api]);

  // Load persisted player prefs (crossfade, playback rate, loudness).
  useEffect(() => {
    void getSetting<number>(SETTINGS.crossfadeSec, 0).then((c) => {
      crossfadeRef.current = clampCrossfade(c);
      setCrossfadeState(crossfadeRef.current);
    });
    void getSetting<number>(SETTINGS.playbackRate, 1).then((r) => {
      setPlaybackRateState(r);
      void TrackPlayer.setRate(r).catch(() => {});
    });
    void getSetting<boolean>(SETTINGS.loudness, false).then(setLoudnessOn);
    void getSetting<boolean>(SETTINGS.loudnessAlbum, false).then(setLoudnessAlbum);
    void getSetting<boolean>(SETTINGS.loudnessAllowBoost, false).then(setLoudnessBoost);
  }, []);

  // Compute + apply the loudness base volume for the active track. Fetches
  // per-track gain from /loudness (cached by trackId), resolves a 0..1 volume by
  // the current settings, stores it as the crossfade baseline, and sets it live.
  const applyLoudness = useCallback(async () => {
    const idx = activeIndexRef.current;
    const meta = idx >= 0 ? queueMeta.current[idx] : undefined;
    if (!loudnessOnRef.current || !meta?.trackId) {
      baseVolumeRef.current = 1;
      void TrackPlayer.setVolume(1).catch(() => {});
      return;
    }
    const trackId = meta.trackId;
    let vol = loudnessCache.current.get(trackId);
    if (vol == null) {
      try {
        const loud = await fetchLoudness(api, trackId);
        vol = resolveVolume(loud, {
          enabled: true,
          albumMode: loudnessAlbumRef.current,
          allowBoost: loudnessBoostRef.current,
        });
        // Cache the raw gain-derived volume for track mode; album/boost changes
        // re-resolve, so cache keyed by the resolved value is fine per-session.
        loudnessCache.current.set(trackId, vol);
      } catch {
        vol = 1; // no analysis yet: full volume
      }
    }
    // Guard against a race: only apply if this is still the active track.
    if (activeIndexRef.current === idx) {
      baseVolumeRef.current = vol;
      // During a crossfade fade-in the progress tick applies ramp * baseline.
      if (!fadingInRef.current) void TrackPlayer.setVolume(vol).catch(() => {});
    }
  }, [api]);

  // Crossfade fade-out near track end + minutes sleep-timer auto-pause. Driven
  // by the 250ms progress tick.
  useEffect(() => {
    const cf = crossfadeRef.current;
    if (cf > 0 && fadingInRef.current) {
      // Fade-in half of the crossfade on the incoming track.
      if (progress.position >= cf) {
        fadingInRef.current = false;
        void TrackPlayer.setVolume(baseVolumeRef.current).catch(() => {});
      } else {
        const ramp = fadeInVolume(progress.position, cf);
        void TrackPlayer.setVolume(ramp * baseVolumeRef.current).catch(() => {});
      }
    } else if (cf > 0 && progress.duration > 0 && shouldStartFade(progress.position, progress.duration, cf)) {
      // Fade multiplies the loudness baseline so both features compose.
      const ramp = fadeOutVolume(progress.position, progress.duration, cf);
      void TrackPlayer.setVolume(ramp * baseVolumeRef.current).catch(() => {});
    }
    if (isElapsed(sleepRef.current, Date.now())) {
      void TrackPlayer.pause();
      setSleepState(cleared());
    }
  }, [progress.position, progress.duration]);

  useEffect(() => {
    const sub = TrackPlayer.addEventListener(Event.PlaybackActiveTrackChanged, async () => {
      // A new track started. If the previous one ran into its crossfade window
      // (it ended on its own), ramp this one in from silence; otherwise restore
      // full volume (undo any fade). Also honor an "end of track" sleep timer.
      const cfNow = crossfadeRef.current;
      const prevPos = progressRef.current.position || 0;
      const prevDur = progressRef.current.duration || 0;
      const endedNaturally = cfNow > 0 && prevDur > 0 && prevPos >= prevDur - cfNow - 1;
      fadingInRef.current = endedNaturally;
      void TrackPlayer.setVolume(endedNaturally ? 0 : 1).catch(() => {});
      baseVolumeRef.current = 1;
      if (sleepRef.current.mode === "track") {
        void TrackPlayer.pause();
        setSleepState(cleared());
      }
      // Record a play for the track we just left (Recently/Most Played inputs),
      // the way the web dock POSTs to /api/track-plays.
      const prevIdx = activeIndexRef.current;
      const prev = prevIdx >= 0 ? queueMeta.current[prevIdx] : undefined;
      if (prev?.trackId && lastPlayReported.current !== prev.trackId) {
        lastPlayReported.current = prev.trackId;
        const played = Math.round((progressRef.current.position || 0) * 1000);
        const dur = progressRef.current.duration || prev.durationSec || 0;
        const completed = dur > 0 ? progressRef.current.position >= dur - 5 : false;
        if (!downloadsRef.current.online) {
          downloadsRef.current.bufferOffline({
            kind: "track_play",
            trackId: prev.trackId,
            msPlayed: played,
            completed,
            at: Date.now(),
          });
        } else {
          void postTrackPlay(api, prev.trackId, played, completed);
        }
      }
      const idx = (await TrackPlayer.getActiveTrackIndex()) ?? -1;
      activeIndexRef.current = idx;
      void applyLoudness();
      syncer.current?.flush();
      void pushQueue();
    });
    return () => sub.remove();
  }, [api, pushQueue, applyLoudness]);

  // Expired-URL recovery: on a playback error, re-sign the active track's URL
  // and reload it once.
  useEffect(() => {
    const sub = TrackPlayer.addEventListener(Event.PlaybackError, async () => {
      if (recovering.current) return;
      recovering.current = true;
      try {
        const idx = (await TrackPlayer.getActiveTrackIndex()) ?? -1;
        const meta = idx >= 0 ? queueMeta.current[idx] : undefined;
        if (!meta) return;
        const at = progressRef.current.position;
        const fresh = await startStream(api, meta.mediaFileId, Math.floor(at));
        const current = await TrackPlayer.getActiveTrack();
        if (current) {
          await TrackPlayer.load({ ...current, url: fresh.url });
          await TrackPlayer.seekTo(at);
          await TrackPlayer.play();
        }
      } catch {
        // second failure: leave stopped; UI shows the error state elsewhere
      } finally {
        recovering.current = false;
      }
    });
    return () => sub.remove();
  }, [api]);

  const playSongs = useCallback(
    async (songs: SongRow[], startIndex: number) => {
      const tapped = songs[startIndex];
      const playable = songs.filter((s) => s.media_files.length > 0);
      if (playable.length === 0) return;
      // Queue a window around the tapped track instead of the whole list: the
      // Songs screen can hold the entire library, and every entry needs its own
      // signed URL (Option A: fresh just before play).
      let tappedIdx = tapped ? playable.findIndex((s) => s.id === tapped.id) : 0;
      if (tappedIdx < 0) tappedIdx = 0;
      const from = Math.max(0, tappedIdx - QUEUE_BEHIND);
      const windowed = playable.slice(from, tappedIdx + QUEUE_AHEAD);
      // Offline / downloaded first: a downloaded track plays from its local file
      // (stored by media_file_id, never a URL). Otherwise sign a fresh URL.
      // With no network, only downloaded tracks are queued and no stream/start
      // request is made at all (nothing to wait on).
      const offline = !downloadsRef.current.online;
      const signed = await Promise.all(
        windowed.map((s) => {
          const local = downloadsRef.current.localPathFor(s.media_files[0].id);
          if (local) return Promise.resolve<{ url: string; art_url?: string | null; cover_path?: string | null }>({ url: local });
          if (offline) return Promise.resolve(null);
          return startStream(api, s.media_files[0].id).catch(() => null);
        }),
      );
      const tracks: Track[] = [];
      const metas: QueueMeta[] = [];
      let startAt = -1;
      const tappedId = playable[tappedIdx].id;
      windowed.forEach((s, i) => {
        const sig = signed[i];
        if (!sig) return;
        // If the tapped song itself can't play (offline, not downloaded), start
        // at the first playable one after it.
        if (startAt < 0 && (s.id === tappedId || i > tappedIdx - from)) startAt = tracks.length;
        tracks.push({
          id: s.id,
          url: sig.url,
          title: s.title,
          artist: s.artist_name,
          album: s.album_title,
          duration: s.duration_sec ?? undefined,
          artwork: buildTrackArtwork({ base: getApiBase(), artUrl: sig.art_url, coverPath: sig.cover_path ?? s.cover_path }),
        });
        metas.push({
          mediaFileId: s.media_files[0].id,
          trackId: s.id,
          title: s.title,
          artist: s.artist_name,
          album: s.album_title,
          albumId: s.album_id,
          artistId: s.artist_id,
          artPath: s.cover_path,
          durationSec: s.duration_sec,
        });
      });
      if (tracks.length === 0) return;
      queueMeta.current = metas;
      await TrackPlayer.reset();
      await TrackPlayer.add(tracks);
      const safeIndex = startAt < 0 ? 0 : Math.min(startAt, tracks.length - 1);
      await TrackPlayer.skip(safeIndex);
      activeIndexRef.current = safeIndex;
      setHasQueue(true);
      lastPlayReported.current = null;
      await TrackPlayer.play();
      void applyLoudness();
      syncer.current?.flush();
      setQueueVersion((v) => v + 1);
      void pushQueue();
    },
    [api, pushQueue, applyLoudness],
  );

  /** Sign a window of songs into track-player tracks + parallel metas. */
  const signSongs = useCallback(
    async (songs: SongRow[]): Promise<{ tracks: Track[]; metas: QueueMeta[] }> => {
      const playable = songs.filter((s) => s.media_files.length > 0);
      const signed = await Promise.all(
        playable.map((s) => startStream(api, s.media_files[0].id).catch(() => null)),
      );
      const tracks: Track[] = [];
      const metas: QueueMeta[] = [];
      playable.forEach((s, i) => {
        const sig = signed[i];
        if (!sig) return;
        tracks.push({
          id: s.id,
          url: sig.url,
          title: s.title,
          artist: s.artist_name,
          album: s.album_title,
          duration: s.duration_sec ?? undefined,
          artwork: buildTrackArtwork({ base: getApiBase(), artUrl: sig.art_url, coverPath: sig.cover_path ?? s.cover_path }),
        });
        metas.push({
          mediaFileId: s.media_files[0].id,
          trackId: s.id,
          title: s.title,
          artist: s.artist_name,
          album: s.album_title,
          albumId: s.album_id,
          artistId: s.artist_id,
          artPath: s.cover_path,
          durationSec: s.duration_sec,
        });
      });
      return { tracks, metas };
    },
    [api],
  );

  /** Play next: insert right after the current track (TrackPlayer.add with an
   * insert index). */
  const playNext = useCallback(
    async (songs: SongRow[]) => {
      const { tracks, metas } = await signSongs(songs);
      if (tracks.length === 0) return;
      const at = Math.max(0, activeIndexRef.current) + 1;
      await TrackPlayer.add(tracks, at);
      queueMeta.current.splice(at, 0, ...metas);
      setHasQueue(true);
      setQueueVersion((v) => v + 1);
      void pushQueue();
    },
    [signSongs, pushQueue],
  );

  /** Add to queue: append to the end (TrackPlayer.add with no insert index). */
  const addToQueue = useCallback(
    async (songs: SongRow[]) => {
      const { tracks, metas } = await signSongs(songs);
      if (tracks.length === 0) return;
      await TrackPlayer.add(tracks);
      queueMeta.current.push(...metas);
      setHasQueue(true);
      setQueueVersion((v) => v + 1);
      void pushQueue();
    },
    [signSongs, pushQueue],
  );

  const jumpTo = useCallback(async (index: number) => {
    try {
      await TrackPlayer.skip(index);
      activeIndexRef.current = index;
      await TrackPlayer.play();
    } catch {
      /* out of range */
    }
  }, []);

  const removeAt = useCallback(
    async (index: number) => {
      if (index === activeIndexRef.current) return; // can't remove the active track
      try {
        await TrackPlayer.remove([index]);
        queueMeta.current.splice(index, 1);
        if (index < activeIndexRef.current) activeIndexRef.current -= 1;
        setQueueVersion((v) => v + 1);
        void pushQueue();
      } catch {
        /* ignore */
      }
    },
    [pushQueue],
  );

  const moveTrack = useCallback(
    async (from: number, to: number) => {
      if (from === to) return;
      try {
        await TrackPlayer.move(from, to);
        const [m] = queueMeta.current.splice(from, 1);
        queueMeta.current.splice(to, 0, m);
        const act = activeIndexRef.current;
        if (from === act) activeIndexRef.current = to;
        else if (from < act && to >= act) activeIndexRef.current -= 1;
        else if (from > act && to <= act) activeIndexRef.current += 1;
        setQueueVersion((v) => v + 1);
        void pushQueue();
      } catch {
        /* ignore */
      }
    },
    [pushQueue],
  );

  const clearQueue = useCallback(async () => {
    await TrackPlayer.reset();
    queueMeta.current = [];
    activeIndexRef.current = -1;
    setHasQueue(false);
    setQueueVersion((v) => v + 1);
    await clearServerQueue(api).catch(() => {});
  }, [api]);

  const cycleRepeat = useCallback(async () => {
    const nextMode: RepeatSetting = repeatRef.current === "off" ? "all" : repeatRef.current === "all" ? "one" : "off";
    setRepeatMode(nextMode);
    await TrackPlayer.setRepeatMode(
      nextMode === "one" ? RepeatMode.Track : nextMode === "all" ? RepeatMode.Queue : RepeatMode.Off,
    ).catch(() => {});
    void pushQueue();
  }, [pushQueue]);

  const toggleShuffle = useCallback(async () => {
    // Shuffle the upcoming tracks (everything after the active one), keeping the
    // current track in place, then reflect the new order in the metas.
    const nextOn = !shuffleRef.current;
    setShuffleOn(nextOn);
    if (nextOn) {
      const act = activeIndexRef.current;
      const q = await TrackPlayer.getQueue();
      const tail = q.slice(act + 1);
      if (tail.length > 1) {
        // Fisher-Yates over indices, then re-apply by remove+add so
        // track-player and metas stay aligned.
        const order = tail.map((_, i) => i);
        for (let i = order.length - 1; i > 0; i -= 1) {
          const j = Math.floor((i + 1) * ((i * 2654435761) % 1000) / 1000) % (i + 1);
          [order[i], order[j]] = [order[j], order[i]];
        }
        const tailMetas = queueMeta.current.slice(act + 1);
        const newTailMetas = order.map((i) => tailMetas[i]);
        const idxs = tail.map((_, i) => act + 1 + i);
        await TrackPlayer.remove(idxs).catch(() => {});
        await TrackPlayer.add(order.map((i) => tail[i])).catch(() => {});
        queueMeta.current = [...queueMeta.current.slice(0, act + 1), ...newTailMetas];
      }
    }
    setQueueVersion((v) => v + 1);
    void pushQueue();
  }, [pushQueue]);

  const getQueueItems = useCallback((): { metas: QueueMeta[]; activeIndex: number } => {
    return { metas: queueMeta.current, activeIndex: activeIndexRef.current };
  }, [queueVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  const togglePlay = useCallback(async () => {
    if (playingRef.current) {
      await TrackPlayer.pause();
      syncer.current?.flush();
    } else {
      await TrackPlayer.play();
    }
  }, []);

  const castCurrentQueue = useCallback(async (): Promise<boolean> => {
    const metas = queueMeta.current;
    if (metas.length === 0) return false;
    const startIndex = Math.max(0, activeIndexRef.current);
    const startPositionSec = Math.floor(progressRef.current.position || 0);
    const activeMediaId = metas[startIndex]?.mediaFileId;
    // Sign a direct cast URL per track; the receiver fetches each itself from
    // the server, so every URL must be absolute + signed (purpose:"cast" so
    // the server logs the cast start).
    const signed = await Promise.all(
      metas.map((m) =>
        startStream(api, m.mediaFileId, undefined, { purpose: "cast" })
          .then((s) => ({ s, m }))
          .catch(() => null),
      ),
    );
    const resolved = signed.filter((x): x is { s: Awaited<ReturnType<typeof startStream>>; m: QueueMeta } => x !== null);
    const tracks = resolved.map(({ s, m }) => ({
      url: s.url,
      title: m.title,
      artist: m.artist ?? undefined,
      album: m.album ?? undefined,
      // Only the signed, header-less art URL is usable by the receiver.
      artUrl: s.art_url ?? undefined,
    }));
    if (tracks.length === 0) return false;
    const idx = Math.max(0, resolved.findIndex(({ m }) => m.mediaFileId === activeMediaId));
    const ok = await cast.castMusicQueue({ tracks, startIndex: idx, startPositionSec });
    if (ok) {
      await TrackPlayer.pause().catch(() => {});
      syncer.current?.flush();
    }
    return ok;
  }, [api, cast]);

  const next = useCallback(async () => {
    try {
      await TrackPlayer.skipToNext();
    } catch {
      /* end of queue */
    }
  }, []);

  const previous = useCallback(async () => {
    if (progressRef.current.position > 3) {
      await TrackPlayer.seekTo(0);
      return;
    }
    try {
      await TrackPlayer.skipToPrevious();
    } catch {
      await TrackPlayer.seekTo(0);
    }
  }, []);

  const seekTo = useCallback(async (sec: number) => {
    await TrackPlayer.seekTo(sec);
  }, []);

  const nowPlaying = useMemo<NowPlaying | null>(() => {
    if (!activeTrack) return null;
    const idx = activeIndexRef.current;
    const meta = idx >= 0 ? queueMeta.current[idx] : undefined;
    return {
      title: activeTrack.title ?? "Unknown",
      artist: activeTrack.artist,
      artPath: meta?.artPath ?? (typeof activeTrack.artwork === "string" ? activeTrack.artwork : null),
      mediaFileId: meta?.mediaFileId,
      trackId: meta?.trackId ?? null,
      albumId: meta?.albumId ?? null,
      artistId: meta?.artistId ?? null,
    };
  }, [activeTrack]);

  const setCrossfade = useCallback((sec: number) => {
    const c = clampCrossfade(sec);
    crossfadeRef.current = c;
    setCrossfadeState(c);
    void setSetting(SETTINGS.crossfadeSec, c);
  }, []);

  const setRate = useCallback(async (r: number) => {
    setPlaybackRateState(r);
    await TrackPlayer.setRate(r).catch(() => {});
    void setSetting(SETTINGS.playbackRate, r);
  }, []);

  const setLoudness = useCallback(
    (on: boolean) => {
      setLoudnessOn(on);
      loudnessOnRef.current = on;
      void setSetting(SETTINGS.loudness, on);
      loudnessCache.current.clear();
      void applyLoudness();
    },
    [applyLoudness],
  );

  const setLoudnessAlbumMode = useCallback(
    (on: boolean) => {
      setLoudnessAlbum(on);
      loudnessAlbumRef.current = on;
      void setSetting(SETTINGS.loudnessAlbum, on);
      loudnessCache.current.clear();
      void applyLoudness();
    },
    [applyLoudness],
  );

  const setLoudnessAllowBoost = useCallback(
    (on: boolean) => {
      setLoudnessBoost(on);
      loudnessBoostRef.current = on;
      void setSetting(SETTINGS.loudnessAllowBoost, on);
      loudnessCache.current.clear();
      void applyLoudness();
    },
    [applyLoudness],
  );

  const setSleepTimer = useCallback((mode: SleepMode, minutes?: number) => {
    setSleepState(
      mode === "minutes"
        ? startMinutes(Date.now(), minutes ?? 30)
        : mode === "track"
          ? startEndOfTrack()
          : cleared(),
    );
  }, []);

  const value = useMemo<PlayerContextValue>(
    () => ({
      ready,
      playSongs,
      playNext,
      addToQueue,
      crossfadeSec,
      setCrossfade,
      playbackRate,
      setRate,
      loudnessOn,
      setLoudness,
      loudnessAlbum,
      setLoudnessAlbumMode,
      loudnessBoost,
      setLoudnessAllowBoost,
      sleep,
      setSleepTimer,
      togglePlay,
      next,
      previous,
      seekTo,
      jumpTo,
      removeAt,
      moveTrack,
      clearQueue,
      cycleRepeat,
      toggleShuffle,
      repeatMode,
      shuffleOn,
      getQueueItems,
      castCurrentQueue,
      queueVersion,
      nowPlaying,
      isPlaying,
      position: progress.position,
      duration: progress.duration,
      hasQueue,
    }),
    [
      ready,
      playSongs,
      playNext,
      addToQueue,
      crossfadeSec,
      setCrossfade,
      playbackRate,
      setRate,
      loudnessOn,
      setLoudness,
      loudnessAlbum,
      setLoudnessAlbumMode,
      loudnessBoost,
      setLoudnessAllowBoost,
      sleep,
      setSleepTimer,
      togglePlay,
      next,
      previous,
      seekTo,
      jumpTo,
      removeAt,
      moveTrack,
      clearQueue,
      cycleRepeat,
      toggleShuffle,
      repeatMode,
      shuffleOn,
      getQueueItems,
      castCurrentQueue,
      queueVersion,
      nowPlaying,
      isPlaying,
      progress.position,
      progress.duration,
      hasQueue,
    ],
  );

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>;
}

export function usePlayer(): PlayerContextValue {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error("usePlayer must be used within PlayerProvider");
  return ctx;
}
