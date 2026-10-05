import { useQuery } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  SlidersHorizontal,
} from "lucide-react-native";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import Video, {
  OnProgressData,
  SelectedTrackType,
  TextTrackType,
  VideoRef,
} from "react-native-video";
import type { ISO639_1, SelectedTrack, TextTracks } from "react-native-video";

import { fetchMarkers, fetchMediaStreams, fetchNextEpisode, startStream } from "@/api/media";
import type { StreamQuality, StreamStart, SubtitleChoice } from "@/api/types";
import { CastButton, useCast } from "@/cast";
import { useDownloads } from "@/download/DownloadProvider";
import { useApi } from "@/state/auth";
import { deviceName } from "@/state/config";
import { getSetting, setSetting } from "@/state/settings";
import { colors, fonts, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { Icon } from "@/ui/Icon";
import { IconButton } from "@/ui/IconButton";
import { Scrubber } from "@/ui/Scrubber";
import {
  audioLabel,
  defaultAudioIndex,
  QUALITIES,
  qualityLabel,
  subtitleLabel,
} from "./streamChoices";
import { activeMarker, clampSeek, formatClock, hlsBaseOffset, upNextState } from "./transport";
import { videoController } from "@/player/playerController";

interface VideoPlayerProps {
  mediaFileId: string;
  resumeSec?: number;
  onClose: () => void;
  /** Play another media file in place (Up Next auto-advance, crit 37). */
  onPlayNext?: (mediaFileId: string) => void;
}

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;

const PROGRESS_INTERVAL_SEC = 15;

/** Per-device quality setting key (crit 41: quality remembered per device). The
 * device name namespaces it so a shared account keeps distinct choices per
 * phone/TV. Not a token, so AsyncStorage via SETTINGS is fine. */
function qualitySettingKey(): string {
  return `videoQuality:${deviceName()}`;
}

/** Full-screen video player on react-native-video, ported from the PWA's
 * VideoTransport + Player: scrubber with time, back 10 s / forward 30 s,
 * play/pause, auto-hiding controls (crit 8); Skip intro from /api/markers; a
 * Plex-style Up Next countdown driven by the credits marker that then plays the
 * next episode's media file (crit 37); subtitle / audio / quality / speed
 * pickers (crit 41). Resumes from saved progress (HLS resume offsets are
 * bucketed server-side, so the timeline is re-based), reports progress every
 * 15 s, re-signs once on a load error and whenever a picker choice changes. */
export function VideoPlayer({ mediaFileId, resumeSec = 0, onClose, onPlayNext }: VideoPlayerProps): React.ReactElement {
  const api = useApi();
  const cast = useCast();
  const downloads = useDownloads();
  const downloadsRef = useRef(downloads);
  downloadsRef.current = downloads;
  const ref = useRef<VideoRef>(null);
  const [stream, setStream] = useState<StreamStart | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [pickerOpen, setPickerOpen] = useState(false);
  const pausedRef = useRef(false);
  pausedRef.current = paused;
  const pickerOpenRef = useRef(false);
  pickerOpenRef.current = pickerOpen;
  const recovered = useRef(false);
  const lastReport = useRef(0);
  const positionRef = useRef(resumeSec);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Absolute playhead (source seconds) and the HLS base offset of the current
  // stream: HLS resumes start the timeline at the server's 10 s bucket.
  const [position, setPosition] = useState(resumeSec);
  const [seekable, setSeekable] = useState(0);
  const requestedResume = useRef(resumeSec);
  const [rate, setRate] = useState(1);
  const [upNextDismissed, setUpNextDismissed] = useState(false);
  const advanced = useRef(false);

  // Picker state.
  const [quality, setQuality] = useState<StreamQuality>("original");
  // The first stream request waits for the remembered quality so it is signed
  // once, not once with the default and again with the saved value.
  const [qualityReady, setQualityReady] = useState(false);
  // Only an explicit user pick re-signs the stream. The container default is
  // derived for display and never triggers a second /stream/start (that swap
  // restarted the player and doubled start-up time).
  const [pickedAudio, setPickedAudio] = useState<number | undefined>(undefined);
  const [subtitle, setSubtitle] = useState<SubtitleChoice>("off");

  const streams = useQuery({
    queryKey: ["streams", mediaFileId],
    queryFn: () => fetchMediaStreams(api, mediaFileId),
    staleTime: 60 * 60 * 1000,
  });
  const markers = useQuery({
    queryKey: ["markers", mediaFileId],
    queryFn: () => fetchMarkers(api, mediaFileId),
    staleTime: 60 * 60 * 1000,
  });
  const nextEp = useQuery({
    queryKey: ["next-episode", mediaFileId],
    queryFn: () => fetchNextEpisode(api, mediaFileId),
    staleTime: 5 * 60 * 1000,
  });

  // Load the remembered per-device quality before the first stream request.
  useEffect(() => {
    let alive = true;
    void getSetting<StreamQuality>(qualitySettingKey(), "original")
      .then((q) => {
        if (alive) setQuality(q);
      })
      .finally(() => {
        if (alive) setQualityReady(true);
      });
    return () => {
      alive = false;
    };
  }, []);
  const audioIndex = pickedAudio ?? (streams.data ? defaultAudioIndex(streams.data.audio) : undefined);

  const loadUrl = useCallback(async () => {
    setError(null);
    // A downloaded file plays from local storage (offline or not): direct
    // play, absolute timeline, no signed URL to expire.
    const local = downloadsRef.current.itemFor(mediaFileId);
    if (local?.localPath) {
      requestedResume.current = Math.floor(positionRef.current);
      setStream({
        media_file_id: mediaFileId,
        mode: "direct",
        url: local.localPath,
        expires_at: "",
        title: local.title,
        duration_sec: local.meta?.durationSec ?? null,
      });
      return;
    }
    try {
      requestedResume.current = Math.floor(positionRef.current);
      const s = await startStream(api, mediaFileId, requestedResume.current, {
        audioTrackIndex: pickedAudio,
        subtitle,
        quality,
      });
      setStream(s);
    } catch {
      setError("Couldn't start playback.");
    }
  }, [api, mediaFileId, pickedAudio, subtitle, quality]);

  useEffect(() => {
    if (!qualityReady) return;
    void loadUrl();
  }, [loadUrl, qualityReady]);

  // HLS transcodes are reaped after ~90 s without requests (e.g. while paused).
  useEffect(() => {
    if (!stream || stream.mode !== "hls") return;
    const keepaliveUrl = stream.url.replace(/\/stream\/hls\/[^?]+/, `/stream/keepalive/${mediaFileId}`);
    const timer = setInterval(() => {
      void fetch(keepaliveUrl, { method: "GET" }).catch(() => undefined);
    }, 30_000);
    return () => clearInterval(timer);
  }, [stream, mediaFileId]);

  const scheduleHide = useCallback(() => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    // 5 s like Plex; never while paused or while the options sheet is open.
    hideTimer.current = setTimeout(() => {
      if (!pausedRef.current && !pickerOpenRef.current) setControlsVisible(false);
    }, 5000);
  }, []);

  useEffect(() => {
    scheduleHide();
    return () => {
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, [scheduleHide]);

  const base = stream ? hlsBaseOffset(stream.mode, requestedResume.current) : 0;
  const duration = stream?.duration_sec && stream.duration_sec > 0 ? stream.duration_sec : base + seekable;

  const onProgress = useCallback(
    (data: OnProgressData) => {
      const abs = data.currentTime + base;
      positionRef.current = abs;
      setPosition(abs);
      if (data.seekableDuration > 0) setSeekable(data.seekableDuration);
      if (Math.abs(abs - lastReport.current) >= PROGRESS_INTERVAL_SEC) {
        lastReport.current = abs;
        const total = stream?.duration_sec ?? (data.seekableDuration >= 1 ? base + data.seekableDuration : undefined);
        if (!downloadsRef.current.online) {
          // Offline: queue the progress; it flushes when the network returns.
          downloadsRef.current.bufferOffline({
            kind: "progress",
            mediaFileId,
            positionSec: Math.floor(abs),
            durationSec: total ? Math.floor(total) : undefined,
            at: Date.now(),
          });
          return;
        }
        void api
          .request(`/api/progress/${mediaFileId}`, {
            method: "PUT",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
              position_sec: Math.floor(abs),
              duration_sec: total ? Math.floor(total) : undefined,
            }),
          })
          .catch(() => {});
      }
    },
    [api, mediaFileId, base, stream],
  );

  /** Seek to an absolute source second (re-based for HLS resumes). */
  const seekAbs = useCallback(
    (absSec: number) => {
      const target = clampSeek(absSec, duration, base);
      positionRef.current = target;
      setPosition(target);
      ref.current?.seek(target - base);
    },
    [duration, base],
  );

  // Uniform player controller (item 8c). Groundwork so a future watch-together
  // room can command this player (play/pause/seek/setRate) and read its
  // position without knowing it is react-native-video. Behavior is unchanged:
  // play/pause flip the same `paused` state and seek reuses seekAbs. Deps are
  // read through refs/callbacks so the controller identity stays stable.
  const baseRef = useRef(base);
  baseRef.current = base;
  const controller = useMemo(
    () =>
      videoController({
        getRef: () => ref.current,
        getBase: () => baseRef.current,
        getPosition: () => positionRef.current,
        getPaused: () => pausedRef.current,
        setPaused,
        setRate,
      }),
    [],
  );
  // Keep the eslint deps happy without changing behavior: the controller is a
  // stable groundwork handle the room layer will drive later.
  void controller;

  const next = nextEp.data ?? null;
  const upNext = upNextState(position, markers.data, !!next && !!onPlayNext);
  const marker = activeMarker(position, markers.data);

  const advance = useCallback(() => {
    if (advanced.current || !next || !onPlayNext) return;
    advanced.current = true;
    onPlayNext(next.media_file_id);
  }, [next, onPlayNext]);

  // Auto-advance when the credits countdown reaches zero.
  useEffect(() => {
    if (upNext.show && !upNextDismissed && upNext.secondsLeft === 0) advance();
  }, [upNext.show, upNext.secondsLeft, upNextDismissed, advance]);

  // Cast hand-off. When a receiver connects, mint a fresh signed URL with
  // purpose:"cast" (the receiver fetches it itself from the server) and
  // load it, carrying the current position over, then pause local playback. On
  // disconnect, resume locally at wherever the receiver left off.
  const castedRef = useRef(false);
  const castVideoNow = useCallback(async () => {
    try {
      const at = Math.floor(positionRef.current);
      const s = await startStream(api, mediaFileId, at, {
        audioTrackIndex: pickedAudio,
        subtitle,
        quality,
        purpose: "cast",
      });
      const ok = await cast.castVideo({
        url: s.url,
        mode: s.mode,
        title: s.title ?? stream?.title ?? undefined,
        artUrl: s.art_url ?? undefined,
        startPositionSec: at,
        isMovie: true,
      });
      if (ok) setPaused(true);
    } catch {
      // Keep playing locally if the hand-off fails.
    }
  }, [api, mediaFileId, pickedAudio, subtitle, quality, cast, stream]);

  useEffect(() => {
    if (cast.isConnected && !castedRef.current) {
      castedRef.current = true;
      void castVideoNow();
    } else if (!cast.isConnected && castedRef.current) {
      // Session ended: resume local playback where the receiver was.
      castedRef.current = false;
      setPaused(false);
    }
  }, [cast.isConnected, castVideoNow]);

  const onError = useCallback(async () => {
    if (recovered.current) {
      setError("Playback failed.");
      return;
    }
    recovered.current = true;
    await loadUrl();
  }, [loadUrl]);

  const toggleControls = useCallback(() => {
    setControlsVisible((v) => !v);
    scheduleHide();
  }, [scheduleHide]);

  // Apply a picker change: persist quality per device, then re-sign (audio and
  // quality force a new remux; subtitles that are burned/off also re-sign).
  const applyChoices = useCallback(
    (next: { quality?: StreamQuality; audioIndex?: number; subtitle?: SubtitleChoice }) => {
      recovered.current = false;
      if (next.quality !== undefined) {
        setQuality(next.quality);
        void setSetting(qualitySettingKey(), next.quality);
      }
      if (next.audioIndex !== undefined) setPickedAudio(next.audioIndex);
      if (next.subtitle !== undefined) setSubtitle(next.subtitle);
      // loadUrl re-runs via its dependency change.
    },
    [],
  );

  // Build the react-native-video textTracks list from the streams that carry a
  // signed .vtt URL (or a constructed one). Selecting a numeric subtitle shows
  // that side-loaded text track; burn-in / off are handled server-side.
  const textTracks = useMemo<TextTracks>(() => {
    const subs = streams.data?.subtitles ?? [];
    const out: TextTracks = [];
    subs.forEach((s) => {
      const uri = s.vtt_url ?? undefined;
      if (!uri) return;
      out.push({
        title: subtitleLabel(s),
        language: (s.language ?? "en") as ISO639_1,
        type: TextTrackType.VTT,
        uri,
      });
    });
    return out;
  }, [streams.data]);

  const selectedTextTrack = useMemo<SelectedTrack>(() => {
    if (typeof subtitle !== "number") return { type: SelectedTrackType.DISABLED };
    return { type: SelectedTrackType.INDEX, value: subtitle };
  }, [subtitle]);

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.errText}>{error}</Text>
        <Pressable
          onPress={() => {
            recovered.current = false;
            void loadUrl();
          }}
          accessibilityRole="button"
          accessibilityLabel="Retry"
          style={styles.retry}
        >
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
        <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close">
          <Text style={styles.close}>Close</Text>
        </Pressable>
      </View>
    );
  }

  if (!stream) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return (
    <Pressable style={styles.fill} onPress={toggleControls}>
      <Video
        ref={ref}
        source={{ uri: stream.url }}
        style={styles.fill}
        resizeMode="contain"
        paused={paused}
        onProgress={onProgress}
        onError={onError}
        onLoad={(d) => {
          if (d.duration > 0) setSeekable(d.duration);
          const rel = positionRef.current - base;
          if (rel > 0) ref.current?.seek(rel);
        }}
        onEnd={advance}
        rate={rate}
        progressUpdateInterval={1000}
        enterPictureInPictureOnLeave
        controls={false}
        playInBackground={false}
        textTracks={textTracks.length > 0 ? textTracks : undefined}
        selectedTextTrack={selectedTextTrack}
      />
      {controlsVisible ? (
        <View style={styles.overlay} pointerEvents="box-none">
          <View style={styles.topBar}>
            <IconButton icon={ChevronDown} onPress={onClose} accessibilityLabel="Close player" color="#fff" />
            <Text style={styles.title} numberOfLines={1}>
              {stream.title ?? "Now playing"}
            </Text>
            <CastButton tintColor="#fff" />
            <IconButton
              icon={SlidersHorizontal}
              onPress={() => setPickerOpen(true)}
              accessibilityLabel="Audio, subtitles and quality"
              color="#fff"
            />
          </View>
          <View style={styles.centerRow}>
            <Pressable
              onPress={() => {
                seekAbs(positionRef.current - 10);
                scheduleHide();
              }}
              accessibilityRole="button"
              accessibilityLabel="Back 10 seconds"
              style={styles.jump}
            >
              <Icon icon={SkipBack} size={30} color="#fff" fill />
              <Text style={styles.jumpTxt}>10</Text>
            </Pressable>
            <IconButton
              icon={paused ? Play : Pause}
              onPress={() => {
                setPaused((p) => !p);
                scheduleHide();
              }}
              accessibilityLabel={paused ? "Play" : "Pause"}
              color="#fff"
              size={56}
              fill
            />
            <Pressable
              onPress={() => {
                seekAbs(positionRef.current + 30);
                scheduleHide();
              }}
              accessibilityRole="button"
              accessibilityLabel="Forward 30 seconds"
              style={styles.jump}
            >
              <Icon icon={SkipForward} size={30} color="#fff" fill />
              <Text style={styles.jumpTxt}>30</Text>
            </Pressable>
          </View>
          <View style={styles.bottomBar}>
            <Scrubber
              position={position}
              duration={duration}
              onSeek={(sec) => {
                seekAbs(sec);
                scheduleHide();
              }}
            />
            <View style={styles.timeRow}>
              <Text style={styles.time} accessibilityLabel={`Elapsed ${formatClock(position)}`}>
                {formatClock(position)}
              </Text>
              <Text style={styles.time} accessibilityLabel={`Remaining ${formatClock(duration - position)}`}>
                -{formatClock(Math.max(0, duration - position))}
              </Text>
            </View>
          </View>
        </View>
      ) : null}

      {marker && marker.kind === "intro" ? (
        <Pressable
          onPress={() => seekAbs(marker.end_sec)}
          accessibilityRole="button"
          accessibilityLabel="Skip intro"
          style={styles.skipBtn}
        >
          <Text style={styles.skipTxt}>Skip intro</Text>
        </Pressable>
      ) : null}
      {marker && marker.kind === "credits" && !(upNext.show && !upNextDismissed) ? (
        <Pressable
          onPress={() => (next && onPlayNext ? advance() : seekAbs(marker.end_sec))}
          accessibilityRole="button"
          accessibilityLabel="Skip credits"
          style={styles.skipBtn}
        >
          <Text style={styles.skipTxt}>Skip credits</Text>
        </Pressable>
      ) : null}

      {upNext.show && !upNextDismissed && next ? (
        <View style={styles.upNext} accessibilityLabel={`Up Next ${next.title}, playing in ${upNext.secondsLeft} seconds`}>
          <Text style={styles.upNextLabel}>UP NEXT</Text>
          <Text style={styles.upNextTitle} numberOfLines={2}>
            {next.title}
          </Text>
          <Text style={styles.upNextCount}>Playing in {upNext.secondsLeft}s</Text>
          <View style={styles.upNextRow}>
            <Pressable onPress={advance} accessibilityRole="button" accessibilityLabel="Play next episode now" style={styles.upNextPlay}>
              <Icon icon={Play} size={16} color={colors.background} fill />
              <Text style={styles.upNextPlayTxt}>Play now</Text>
            </Pressable>
            <Pressable
              onPress={() => setUpNextDismissed(true)}
              accessibilityRole="button"
              accessibilityLabel="Cancel Up Next"
              style={styles.upNextCancel}
            >
              <Text style={styles.upNextCancelTxt}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      <Modal visible={pickerOpen} transparent animationType="slide" onRequestClose={() => setPickerOpen(false)}>
        <View style={styles.sheetBackdrop}>
          <View style={styles.sheet}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>Audio & Subtitles</Text>
              <Pressable
                onPress={() => setPickerOpen(false)}
                accessibilityLabel="Close picker"
                style={styles.closeBtn}
              >
                <Icon icon={ChevronDown} size={22} color={colors.text} />
              </Pressable>
            </View>
            <ScrollView>
              <Text style={styles.sectionLabel}>Quality</Text>
              <View style={styles.chipRow}>
                {QUALITIES.map((q) => (
                  <Pressable
                    key={q}
                    accessibilityRole="button"
                    accessibilityLabel={`Quality ${qualityLabel(q)}`}
                    onPress={() => applyChoices({ quality: q })}
                    style={[styles.chip, quality === q && styles.chipOn]}
                  >
                    <Text style={[styles.chipTxt, quality === q && styles.chipTxtOn]}>{qualityLabel(q)}</Text>
                  </Pressable>
                ))}
              </View>

              <Text style={styles.sectionLabel}>Speed</Text>
              <View style={styles.chipRow}>
                {SPEEDS.map((r) => (
                  <Pressable
                    key={r}
                    accessibilityRole="button"
                    accessibilityLabel={`Speed ${r}x`}
                    onPress={() => setRate(r)}
                    style={[styles.chip, rate === r && styles.chipOn]}
                  >
                    <Text style={[styles.chipTxt, rate === r && styles.chipTxtOn]}>{r}x</Text>
                  </Pressable>
                ))}
              </View>

              <Text style={styles.sectionLabel}>Audio</Text>
              {(streams.data?.audio ?? []).length === 0 ? (
                <Text style={styles.muted}>No selectable audio tracks.</Text>
              ) : (
                (streams.data?.audio ?? []).map((a) => (
                  <Pressable
                    key={a.index}
                    accessibilityRole="button"
                    accessibilityLabel={`Audio ${audioLabel(a)}`}
                    onPress={() => applyChoices({ audioIndex: a.index })}
                    style={[styles.optRow, audioIndex === a.index && styles.optRowOn]}
                  >
                    <Text style={styles.optRowTxt}>{audioLabel(a)}</Text>
                    {audioIndex === a.index ? <Icon icon={Check} size={18} color={colors.accent} /> : null}
                  </Pressable>
                ))
              )}

              <Text style={styles.sectionLabel}>Subtitles</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Subtitles off"
                onPress={() => applyChoices({ subtitle: "off" })}
                style={[styles.optRow, subtitle === "off" && styles.optRowOn]}
              >
                <Text style={styles.optRowTxt}>Off</Text>
                {subtitle === "off" ? <Icon icon={Check} size={18} color={colors.accent} /> : null}
              </Pressable>
              {(streams.data?.subtitles ?? []).map((s) => (
                <Pressable
                  key={s.index}
                  accessibilityRole="button"
                  accessibilityLabel={`Subtitle ${subtitleLabel(s)}`}
                  onPress={() => applyChoices({ subtitle: s.index })}
                  style={[styles.optRow, subtitle === s.index && styles.optRowOn]}
                >
                  <Text style={styles.optRowTxt}>{subtitleLabel(s)}</Text>
                  {subtitle === s.index ? <Icon icon={Check} size={18} color={colors.accent} /> : null}
                </Pressable>
              ))}
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Burn in subtitles"
                onPress={() => applyChoices({ subtitle: "burn" })}
                style={[styles.optRow, subtitle === "burn" && styles.optRowOn]}
              >
                <Text style={styles.optRowTxt}>Burn in (image subs)</Text>
                {subtitle === "burn" ? <Icon icon={Check} size={18} color={colors.accent} /> : null}
              </Pressable>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: "#000" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: "#000", gap: spacing.md },
  overlay: { ...StyleSheet.absoluteFillObject, justifyContent: "space-between" },
  topBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
    backgroundColor: "rgba(0,0,0,0.4)",
  },
  centerRow: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xxl },
  jump: { minWidth: MIN_TOUCH, minHeight: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
  jumpTxt: { color: "#fff", fontSize: 11, fontWeight: "700", marginTop: -2 },
  bottomBar: { paddingHorizontal: spacing.lg, paddingBottom: spacing.lg, backgroundColor: "rgba(0,0,0,0.4)" },
  timeRow: { flexDirection: "row", justifyContent: "space-between" },
  time: { color: "#fff", fontFamily: fonts.mono, fontSize: 12 },
  skipBtn: {
    position: "absolute",
    right: spacing.xl,
    bottom: 110,
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    justifyContent: "center",
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.8)",
    backgroundColor: "rgba(0,0,0,0.6)",
  },
  skipTxt: { color: "#fff", fontWeight: "700" },
  upNext: {
    position: "absolute",
    right: spacing.xl,
    bottom: 110,
    width: 280,
    padding: spacing.lg,
    borderRadius: radius.md,
    backgroundColor: "rgba(11,6,4,0.92)",
    borderWidth: 1,
    borderColor: colors.line,
    gap: spacing.xs,
  },
  upNextLabel: { color: colors.textMuted, fontFamily: fonts.mono, fontSize: 11, letterSpacing: 1 },
  upNextTitle: { color: colors.text, fontFamily: fonts.uiSemiBold, fontSize: 16 },
  upNextCount: { color: colors.accent, fontFamily: fonts.mono, fontSize: 12 },
  upNextRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  upNextPlay: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
  },
  upNextPlayTxt: { color: colors.background, fontWeight: "700" },
  upNextCancel: { minHeight: MIN_TOUCH, paddingHorizontal: spacing.lg, justifyContent: "center" },
  upNextCancelTxt: { color: colors.text },
  title: { ...typography.heading, color: "#fff", flex: 1 },
  errText: { ...typography.body, color: "#fff" },
  retry: { backgroundColor: colors.accent, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: 999 },
  retryText: { color: "#1a1206", fontWeight: "700" },
  close: { color: colors.textMuted, marginTop: spacing.md },
  sheetBackdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: "flex-end" },
  sheet: {
    maxHeight: "70%",
    backgroundColor: colors.bg2,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.lg,
  },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.md },
  sheetTitle: { ...typography.heading },
  closeBtn: { minWidth: MIN_TOUCH, minHeight: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
  sectionLabel: { ...typography.label, marginTop: spacing.md, marginBottom: spacing.sm },
  muted: { ...typography.body, color: colors.textMuted },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: {
    minHeight: 40,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.line,
    justifyContent: "center",
  },
  chipOn: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipTxt: { color: colors.text, fontWeight: "600" },
  chipTxtOn: { color: colors.background },
  optRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
  },
  optRowOn: { backgroundColor: colors.surfaceAlt },
  optRowTxt: { ...typography.body },
});
