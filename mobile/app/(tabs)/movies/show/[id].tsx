import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useEffect, useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { markUnwatched, markWatched } from "@/api/media";
import { useAllProgress, useSeries } from "@/api/queries";
import type { Episode } from "@/api/types";
import { nextUnwatchedEpisode, type ProgressMap } from "@/player/onDeck";
import { useApi } from "@/state/auth";
import { invalidateWatchState } from "@/state/query";
import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { Artwork } from "@/ui/Artwork";
import { Backdrop } from "@/ui/Backdrop";
import { DownloadButton } from "@/ui/DownloadButton";
import { QueryState } from "@/ui/QueryState";
import { Screen } from "@/ui/Screen";

/** Show detail: poster, season picker, episode list with server-backed
 * watched checks, and a Plex-style primary button that plays the On Deck
 * episode (resume the in-progress one, else the next unwatched). Tapping an
 * episode plays its first media file; the watch route resumes saved progress. */
export default function ShowDetailScreen(): React.ReactElement {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const api = useApi();
  const series = useSeries(id ?? "");
  const [season, setSeason] = useState<number | null>(null);
  const progress = useAllProgress();
  const [watched, setWatched] = useState<Set<string>>(new Set());

  // Seed the watched checks from the server's progress rows.
  useEffect(() => {
    if (!progress.data) return;
    setWatched(new Set(progress.data.filter((p) => !!p.completed_at).map((p) => p.media_file_id)));
  }, [progress.data]);

  const progressMap = useMemo<ProgressMap>(() => {
    const m: ProgressMap = {};
    for (const p of progress.data ?? []) {
      m[p.media_file_id] = {
        position_sec: p.position_sec,
        completed_at: watched.has(p.media_file_id) ? p.completed_at ?? "local" : null,
      };
    }
    for (const id of watched) if (!m[id]) m[id] = { position_sec: 0, completed_at: "local" };
    return m;
  }, [progress.data, watched]);
  const onDeckEp = useMemo(
    () => (series.data ? nextUnwatchedEpisode(series.data.episodes, progressMap) : null),
    [series.data, progressMap],
  );

  const toggleWatched = async (fileId: string) => {
    const isOn = watched.has(fileId);
    setWatched((prev) => {
      const nextSet = new Set(prev);
      if (isOn) nextSet.delete(fileId);
      else nextSet.add(fileId);
      return nextSet;
    });
    if (isOn) await markUnwatched(api, fileId).catch(() => {});
    else await markWatched(api, fileId).catch(() => {});
    invalidateWatchState();
  };

  const seasons = useMemo(() => {
    const map = new Map<number, Episode[]>();
    for (const ep of series.data?.episodes ?? []) {
      const list = map.get(ep.season_number) ?? [];
      list.push(ep);
      map.set(ep.season_number, list);
    }
    for (const list of map.values()) list.sort((a, b) => a.episode_number - b.episode_number);
    // Specials (season 0) go last.
    return [...map.entries()].sort(([a], [b]) => (a === 0 ? 1 : b === 0 ? -1 : a - b));
  }, [series.data]);

  const current = season ?? seasons[0]?.[0] ?? null;
  const episodes = seasons.find(([n]) => n === current)?.[1] ?? [];

  return (
    <Screen title="Show">
      <QueryState
        isLoading={series.isLoading}
        isError={series.isError}
        data={series.data}
        onRetry={series.refetch}
        isEmpty={(d) => d.episodes.length === 0}
        emptyTitle="No episodes yet"
        emptyMessage="Episodes will appear here once they're in your library."
      >
        {(s) => (
          <ScrollView
            contentContainerStyle={styles.content}
            refreshControl={
              <RefreshControl refreshing={series.isFetching} onRefresh={series.refetch} tintColor={colors.accent} />
            }
          >
            <Backdrop path={s.poster_path} height={180}>
              <View style={styles.hero}>
                <Artwork path={s.poster_path} size={110} rounded />
                <View style={styles.heroText}>
                  <Text style={typography.heading} numberOfLines={3}>
                    {s.title}
                  </Text>
                  {s.year ? <Text style={styles.muted}>{s.year}</Text> : null}
                </View>
              </View>
            </Backdrop>

            {onDeckEp && onDeckEp.media_files[0] ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Play S${onDeckEp.season_number} E${onDeckEp.episode_number}`}
                onPress={() => router.push(`/watch/${onDeckEp.media_files[0].id}`)}
                style={({ pressed }) => [styles.playNext, pressed && styles.pressed]}
              >
                <Ionicons name="play" size={18} color={colors.background} />
                <Text style={styles.playNextText} numberOfLines={1}>
                  {(progressMap[onDeckEp.media_files[0].id]?.position_sec ?? 0) > 0 ? "Resume" : "Play"}{" "}
                  S{onDeckEp.season_number} E{onDeckEp.episode_number}
                  {onDeckEp.title ? ` · ${onDeckEp.title}` : ""}
                </Text>
              </Pressable>
            ) : null}

            {seasons.length > 1 ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
                {seasons.map(([n]) => (
                  <Pressable
                    key={n}
                    accessibilityRole="button"
                    accessibilityState={{ selected: n === current }}
                    accessibilityLabel={n === 0 ? "Specials" : `Season ${n}`}
                    onPress={() => setSeason(n)}
                    style={[styles.chip, n === current && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, n === current && styles.chipTextActive]}>
                      {n === 0 ? "Specials" : `Season ${n}`}
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>
            ) : null}

            {episodes.map((ep) => {
              const fileId = ep.media_files[0]?.id;
              const label = `${ep.episode_number}. ${ep.title ?? `Episode ${ep.episode_number}`}`;
              const isWatched = !!fileId && watched.has(fileId);
              return (
                <View key={ep.id} style={styles.episode}>
                  <Pressable
                    disabled={!fileId}
                    accessibilityRole="button"
                    accessibilityLabel={fileId ? `Play ${label}` : `${label}, not available`}
                    onPress={() => fileId && router.push(`/watch/${fileId}`)}
                    style={({ pressed }) => [styles.epMain, pressed && styles.pressed, !fileId && styles.disabled]}
                  >
                    <Text style={styles.epTitle} numberOfLines={1}>
                      {label}
                    </Text>
                    {ep.overview ? (
                      <Text style={styles.muted} numberOfLines={2}>
                        {ep.overview}
                      </Text>
                    ) : null}
                  </Pressable>
                  {fileId ? (
                    <DownloadButton
                      compact
                      mediaFileId={fileId}
                      title={`${s.title} S${ep.season_number}E${ep.episode_number}${ep.title ? ` ${ep.title}` : ""}`}
                      opts={{
                        kind: "episode",
                        meta: {
                          coverPath: s.poster_path ?? null,
                          container: ep.media_files[0]?.container ?? null,
                          group: s.title,
                        },
                      }}
                    />
                  ) : null}
                  {fileId ? (
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={isWatched ? "Mark episode unwatched" : "Mark episode watched"}
                      onPress={() => void toggleWatched(fileId)}
                      style={styles.epWatched}
                    >
                      <Ionicons
                        name={isWatched ? "checkmark-circle" : "ellipse-outline"}
                        size={22}
                        color={isWatched ? colors.bulb : colors.textFaint}
                      />
                    </Pressable>
                  ) : null}
                </View>
              );
            })}
          </ScrollView>
        )}
      </QueryState>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: spacing.xxl },
  playNext: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: colors.bulb,
    alignSelf: "flex-start",
    maxWidth: "100%",
  },
  playNextText: { color: colors.background, fontWeight: "700", flexShrink: 1 },
  hero: { flexDirection: "row", gap: spacing.lg, marginBottom: spacing.lg },
  heroText: { flex: 1, justifyContent: "center", gap: spacing.xs },
  muted: { ...typography.caption, color: colors.textMuted },
  chips: { gap: spacing.sm, paddingBottom: spacing.md },
  chip: {
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    justifyContent: "center",
  },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { fontSize: 14, fontWeight: "600", color: colors.text },
  chipTextActive: { color: colors.background },
  episode: {
    minHeight: MIN_TOUCH,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  epMain: { flex: 1, paddingVertical: spacing.md, gap: spacing.xs },
  epWatched: { width: MIN_TOUCH, height: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
  epTitle: { ...typography.body, fontWeight: "600" },
  pressed: { opacity: 0.7 },
  disabled: { opacity: 0.4 },
});
