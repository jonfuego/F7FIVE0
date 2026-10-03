import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react-native";
import React, { useEffect, useMemo, useRef } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { fetchLyrics } from "@/api/media";
import { activeLyricIndex, plainTextLines } from "@/player/lyrics";
import { usePlayer } from "@/player/PlayerProvider";
import { useApi } from "@/state/auth";
import { colors, MIN_TOUCH, spacing, typography } from "@/state/theme";
import { Icon } from "@/ui/Icon";

interface LyricsViewProps {
  visible: boolean;
  onClose: () => void;
}

const LINE_HEIGHT = 40;

/** Full-screen lyrics overlay for the now-playing screen (crit 47). Synced
 * lyrics scroll and highlight the active line off the player position; a plain
 * text fallback renders when the track has no timing. Same-host only (the
 * backend is the sole lyrics source). */
export function LyricsView({ visible, onClose }: LyricsViewProps): React.ReactElement {
  const api = useApi();
  const { nowPlaying, position } = usePlayer();
  const trackId = nowPlaying?.trackId ?? null;
  const scrollRef = useRef<ScrollView>(null);

  const lyrics = useQuery({
    queryKey: ["lyrics", trackId],
    queryFn: () => fetchLyrics(api, trackId as string),
    enabled: visible && !!trackId,
    staleTime: 5 * 60 * 1000,
  });

  const positionMs = Math.round(position * 1000);
  const activeIdx = useMemo(
    () => activeLyricIndex(lyrics.data?.lines, positionMs),
    [lyrics.data?.lines, positionMs],
  );

  // Auto-scroll the active synced line toward the vertical center.
  useEffect(() => {
    if (activeIdx < 0 || !scrollRef.current) return;
    scrollRef.current.scrollTo({ y: Math.max(0, activeIdx * LINE_HEIGHT - 160), animated: true });
  }, [activeIdx]);

  const synced = lyrics.data?.synced && lyrics.data?.lines && lyrics.data.lines.length > 0;
  const plain = plainTextLines(lyrics.data?.text);

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        <View style={styles.head}>
          <Text style={styles.headTitle} numberOfLines={1}>
            {nowPlaying?.title ?? "Lyrics"}
          </Text>
          <Pressable
            onPress={onClose}
            accessibilityRole="button"
            accessibilityLabel="Close lyrics"
            style={styles.closeBtn}
          >
            <Icon icon={ChevronDown} size={26} color={colors.text} />
          </Pressable>
        </View>

        {lyrics.isLoading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color={colors.accent} />
          </View>
        ) : lyrics.isError || (!synced && plain.length === 0) ? (
          <View style={styles.center}>
            <Text style={styles.empty}>No lyrics for this track.</Text>
          </View>
        ) : (
          <ScrollView ref={scrollRef} contentContainerStyle={styles.scroll}>
            {synced
              ? lyrics.data!.lines!.map((line, i) => (
                  <Text
                    key={`${line.time_ms}-${i}`}
                    style={[styles.line, i === activeIdx ? styles.lineActive : styles.lineDim]}
                    accessibilityLabel={i === activeIdx ? `Current line: ${line.text}` : undefined}
                  >
                    {line.text || " "}
                  </Text>
                ))
              : plain.map((line, i) => (
                  <Text key={i} style={[styles.line, styles.linePlain]}>
                    {line || " "}
                  </Text>
                ))}
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  head: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xxl,
    paddingBottom: spacing.md,
  },
  headTitle: { ...typography.heading, flex: 1 },
  closeBtn: { minWidth: MIN_TOUCH, minHeight: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  empty: { ...typography.body, color: colors.textMuted },
  scroll: { paddingHorizontal: spacing.xl, paddingVertical: spacing.xxl, paddingBottom: 240 },
  line: { minHeight: LINE_HEIGHT, fontSize: 20, lineHeight: LINE_HEIGHT, textAlign: "center" },
  lineActive: { color: colors.accent, fontWeight: "700" },
  lineDim: { color: colors.textFaint },
  linePlain: { color: colors.text, fontSize: 17, lineHeight: 28, textAlign: "left", minHeight: 28 },
});
