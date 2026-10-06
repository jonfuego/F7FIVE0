import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import {
  ChevronDown,
  FileText,
  List,
  Minus,
  Pause,
  Play,
  Plus,
  Radio,
  Repeat,
  Shuffle,
  SkipBack,
  SkipForward,
  SlidersHorizontal,
} from "lucide-react-native";
import React, { useEffect, useRef, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Switch, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { CastButton, useCast } from "@/cast";
import { usePlayer } from "@/player/PlayerProvider";
import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { Artwork } from "@/ui/Artwork";
import { Icon } from "@/ui/Icon";
import { tick } from "@/ui/haptics";
import { fetchWaveform } from "@/api/media";
import { useTrackRadio } from "@/player/useTrackRadio";
import { useApi } from "@/state/auth";
import { IconButton } from "@/ui/IconButton";
import { LyricsView } from "@/ui/LyricsView";
import { PlayerTrackMenu } from "@/ui/PlayerTrackMenu";
import { QueuePanel } from "@/ui/QueuePanel";
import { WaveformScrubber } from "@/ui/WaveformScrubber";

function fmt(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Full-screen now-playing: large artwork, scrubber, transport. Dismiss with
 * the down-chevron or the Android back gesture (it's a modal route). */
export default function NowPlayingScreen(): React.ReactElement {
  const {
    nowPlaying,
    isPlaying,
    togglePlay,
    next,
    previous,
    seekTo,
    position,
    duration,
    repeatMode,
    shuffleOn,
    cycleRepeat,
    toggleShuffle,
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
    castCurrentQueue,
  } = usePlayer();
  const router = useRouter();
  const api = useApi();
  const cast = useCast();

  // Hand the queue to the receiver when a cast session connects; nothing to undo
  // on disconnect (track-player resumes locally on its own play controls).
  const castedRef = useRef(false);
  useEffect(() => {
    if (cast.isConnected && !castedRef.current) {
      castedRef.current = true;
      void castCurrentQueue();
    } else if (!cast.isConnected) {
      castedRef.current = false;
    }
  }, [cast.isConnected, castCurrentQueue]);
  const startTrackRadio = useTrackRadio();
  const trackId = nowPlaying?.trackId ?? null;
  const waveform = useQuery({
    queryKey: ["waveform", trackId],
    queryFn: () => fetchWaveform(api, trackId as string),
    enabled: !!trackId,
    staleTime: 60 * 60 * 1000,
  });
  const [queueOpen, setQueueOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [lyricsOpen, setLyricsOpen] = useState(false);
  const RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];
  const SLEEPS: { label: string; mode: "off" | "minutes" | "track"; min?: number }[] = [
    { label: "Off", mode: "off" },
    { label: "15m", mode: "minutes", min: 15 },
    { label: "30m", mode: "minutes", min: 30 },
    { label: "45m", mode: "minutes", min: 45 },
    { label: "60m", mode: "minutes", min: 60 },
    { label: "End of track", mode: "track" },
  ];

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.topBar}>
        <IconButton icon={ChevronDown} onPress={() => router.back()} accessibilityLabel="Close now playing" />
        <Text style={styles.header}>Now Playing</Text>
        <View style={styles.topRight}>
          <View style={styles.queueBtn}>
            <CastButton />
          </View>
          <Pressable
            onPress={() => setLyricsOpen(true)}
            accessibilityRole="button"
            accessibilityLabel="Open lyrics"
            style={styles.queueBtn}
          >
            <Icon icon={FileText} size={24} color={colors.text} />
          </Pressable>
          <Pressable
            onPress={() => setOptionsOpen(true)}
            accessibilityRole="button"
            accessibilityLabel="Player options"
            style={styles.queueBtn}
          >
            <Icon icon={SlidersHorizontal} size={24} color={colors.text} />
          </Pressable>
          <Pressable
            onPress={() => setQueueOpen(true)}
            accessibilityRole="button"
            accessibilityLabel="Open queue"
            style={styles.queueBtn}
          >
            <Icon icon={List} size={24} color={colors.text} />
          </Pressable>
          <PlayerTrackMenu
            albumId={nowPlaying?.albumId ?? null}
            artistId={nowPlaying?.artistId ?? null}
            beforeNavigate={() => router.back()}
            size={24}
          />
        </View>
      </View>

      <View style={styles.art}>
        <Artwork path={nowPlaying?.artPath} size={280} rounded />
      </View>

      <View style={styles.meta}>
        <Text style={styles.title} numberOfLines={1}>
          {nowPlaying?.title ?? "Nothing playing"}
        </Text>
        <Text style={styles.artist} numberOfLines={1}>
          {nowPlaying?.artist ?? ""}
        </Text>
      </View>

      <WaveformScrubber
        peaks={waveform.data?.peaks}
        position={position}
        duration={duration}
        onSeek={seekTo}
      />
      <View style={styles.times}>
        <Text style={styles.time}>{fmt(position)}</Text>
        <Text style={styles.time}>{fmt(duration)}</Text>
      </View>

      <View style={styles.transport}>
        <IconButton
          icon={Shuffle}
          onPress={() => {
            tick();
            void toggleShuffle();
          }}
          accessibilityLabel="Shuffle"
          size={24}
          color={shuffleOn ? colors.accent : colors.textMuted}
        />
        <IconButton
          icon={SkipBack}
          onPress={() => {
            tick();
            void previous();
          }}
          accessibilityLabel="Previous track"
          size={34}
          fill
        />
        <IconButton
          icon={isPlaying ? Pause : Play}
          onPress={() => {
            tick();
            void togglePlay();
          }}
          accessibilityLabel={isPlaying ? "Pause" : "Play"}
          size={28}
          diameter={56}
          square
          outlined
          fill
          color={colors.text}
        />
        <IconButton
          icon={SkipForward}
          onPress={() => {
            tick();
            void next();
          }}
          accessibilityLabel="Next track"
          size={34}
          fill
        />
        <View style={styles.repeatWrap}>
          <IconButton
            icon={Repeat}
            onPress={() => {
              tick();
              void cycleRepeat();
            }}
            accessibilityLabel={`Repeat ${repeatMode}`}
            size={24}
            color={repeatMode !== "off" ? colors.accent : colors.textMuted}
          />
          {repeatMode === "one" ? <Text style={styles.repeatOne}>1</Text> : null}
        </View>
      </View>

      <QueuePanel visible={queueOpen} onClose={() => setQueueOpen(false)} />
      <LyricsView visible={lyricsOpen} onClose={() => setLyricsOpen(false)} />

      <Modal visible={optionsOpen} transparent animationType="slide" onRequestClose={() => setOptionsOpen(false)}>
        <View style={styles.sheetBackdrop}>
          <View style={styles.sheet}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>Playback</Text>
              <Pressable onPress={() => setOptionsOpen(false)} accessibilityLabel="Close options" style={styles.queueBtn}>
                <Icon icon={ChevronDown} size={22} color={colors.text} />
              </Pressable>
            </View>
            <ScrollView>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Start track radio"
                disabled={!trackId}
                onPress={() => {
                  if (!trackId) return;
                  setOptionsOpen(false);
                  void startTrackRadio(trackId);
                }}
                style={[styles.radioBtn, !trackId && styles.radioBtnOff]}
              >
                <Icon icon={Radio} size={20} color={colors.background} />
                <Text style={styles.radioBtnTxt}>Start track radio</Text>
              </Pressable>

              <Text style={styles.optLabel}>Speed</Text>
              <View style={styles.chipRow}>
                {RATES.map((r) => (
                  <Pressable
                    key={r}
                    accessibilityRole="button"
                    accessibilityLabel={`Speed ${r}x`}
                    onPress={() => void setRate(r)}
                    style={[styles.chip, playbackRate === r && styles.chipOn]}
                  >
                    <Text style={[styles.chipTxt, playbackRate === r && styles.chipTxtOn]}>{r}x</Text>
                  </Pressable>
                ))}
              </View>

              <Text style={styles.optLabel}>Sleep timer</Text>
              <View style={styles.chipRow}>
                {SLEEPS.map((s) => {
                  const on =
                    (s.mode === "off" && sleep.mode === "off") ||
                    (s.mode === "track" && sleep.mode === "track") ||
                    (s.mode === "minutes" && sleep.mode === "minutes");
                  return (
                    <Pressable
                      key={s.label}
                      accessibilityRole="button"
                      accessibilityLabel={`Sleep ${s.label}`}
                      onPress={() => setSleepTimer(s.mode, s.min)}
                      style={[styles.chip, on && styles.chipOn]}
                    >
                      <Text style={[styles.chipTxt, on && styles.chipTxtOn]}>{s.label}</Text>
                    </Pressable>
                  );
                })}
              </View>

              <Text style={styles.optLabel}>Crossfade: {crossfadeSec === 0 ? "Off (gapless)" : `${crossfadeSec}s`}</Text>
              <View style={styles.chipRow}>
                <Pressable
                  accessibilityLabel="Decrease crossfade"
                  onPress={() => setCrossfade(crossfadeSec - 1)}
                  style={styles.stepBtn}
                >
                  <Icon icon={Minus} size={20} color={colors.text} />
                </Pressable>
                <Pressable
                  accessibilityLabel="Increase crossfade"
                  onPress={() => setCrossfade(crossfadeSec + 1)}
                  style={styles.stepBtn}
                >
                  <Icon icon={Plus} size={20} color={colors.text} />
                </Pressable>
              </View>

              <Text style={styles.optLabel}>Loudness leveling</Text>
              <View style={styles.toggleRow}>
                <Text style={styles.toggleText}>Level volume (-16 LUFS)</Text>
                <Switch
                  value={loudnessOn}
                  onValueChange={setLoudness}
                  accessibilityLabel="Toggle loudness leveling"
                  trackColor={{ true: colors.accent, false: colors.line }}
                  thumbColor={colors.text}
                />
              </View>
              <View style={styles.toggleRow}>
                <Text style={[styles.toggleText, !loudnessOn && styles.toggleDisabled]}>Album mode</Text>
                <Switch
                  value={loudnessAlbum}
                  onValueChange={setLoudnessAlbumMode}
                  disabled={!loudnessOn}
                  accessibilityLabel="Toggle album loudness mode"
                  trackColor={{ true: colors.accent, false: colors.line }}
                  thumbColor={colors.text}
                />
              </View>
              <View style={styles.toggleRow}>
                <Text style={[styles.toggleText, !loudnessOn && styles.toggleDisabled]}>Allow boost</Text>
                <Switch
                  value={loudnessBoost}
                  onValueChange={setLoudnessAllowBoost}
                  disabled={!loudnessOn}
                  accessibilityLabel="Toggle loudness boost"
                  trackColor={{ true: colors.accent, false: colors.line }}
                  thumbColor={colors.text}
                />
              </View>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background, padding: spacing.lg },
  topBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  header: { ...typography.label },
  art: { alignItems: "center", marginTop: spacing.xl },
  meta: { alignItems: "center", marginTop: spacing.xl, gap: spacing.xs },
  title: { ...typography.title, textAlign: "center" },
  artist: { ...typography.body, color: colors.textMuted },
  times: { flexDirection: "row", justifyContent: "space-between", marginTop: spacing.xs },
  time: { ...typography.caption },
  transport: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.lg,
    marginTop: spacing.xl,
  },
  queueBtn: { minWidth: MIN_TOUCH, minHeight: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
  topRight: { flexDirection: "row", alignItems: "center" },
  repeatWrap: { justifyContent: "center", alignItems: "center" },
  repeatOne: { position: "absolute", top: 2, right: 2, ...typography.caption, color: colors.accent, fontSize: 9 },
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
  optLabel: { ...typography.label, marginTop: spacing.md, marginBottom: spacing.sm },
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
  stepBtn: {
    width: MIN_TOUCH,
    height: MIN_TOUCH,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
  },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    minHeight: MIN_TOUCH,
  },
  toggleText: { ...typography.body },
  toggleDisabled: { color: colors.textFaint },
  radioBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    minHeight: MIN_TOUCH,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    marginBottom: spacing.sm,
  },
  radioBtnOff: { opacity: 0.4 },
  radioBtnTxt: { color: colors.background, fontWeight: "700" },
});
