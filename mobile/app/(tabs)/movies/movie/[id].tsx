import { useLocalSearchParams, useRouter } from "expo-router";
import React from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { markUnwatched, markWatched } from "@/api/media";
import { personName } from "@/api/types";
import { useMovie, useProgress } from "@/api/queries";
import { useApi } from "@/state/auth";
import { invalidateWatchState } from "@/state/query";
import { colors, fonts, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { Artwork } from "@/ui/Artwork";
import { Backdrop } from "@/ui/Backdrop";
import { DownloadButton } from "@/ui/DownloadButton";
import { QueryState } from "@/ui/QueryState";
import { Screen } from "@/ui/Screen";

function formatTime(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/** Movie detail: poster, facts, overview, and Play / Resume. The movie id is
 * resolved to its first media file here, because /watch takes a media file id. */
export default function MovieDetailScreen(): React.ReactElement {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const api = useApi();
  const movie = useMovie(id ?? "");
  const fileId = movie.data?.media_files?.[0]?.id ?? "";
  const progress = useProgress(fileId);
  const watched = !!progress.data?.completed_at;

  const toggleWatched = async () => {
    if (!fileId) return;
    if (watched) await markUnwatched(api, fileId).catch(() => {});
    else await markWatched(api, fileId).catch(() => {});
    void progress.refetch();
    invalidateWatchState();
  };

  return (
    <Screen title="Movie" padded={false}>
      <QueryState
        isLoading={movie.isLoading}
        isError={movie.isError}
        data={movie.data}
        onRetry={movie.refetch}
      >
        {(m) => {
          const resumeAt =
            progress.data && !progress.data.completed_at && progress.data.position_sec > 30
              ? progress.data.position_sec
              : 0;
          const facts = [m.year, m.runtime_min ? `${m.runtime_min} min` : null, ...(m.genres ?? []).slice(0, 2)]
            .filter(Boolean)
            .join("  ·  ");
          return (
            <ScrollView
              contentContainerStyle={styles.content}
              refreshControl={
                <RefreshControl
                  refreshing={movie.isFetching}
                  onRefresh={movie.refetch}
                  tintColor={colors.accent}
                />
              }
            >
              <Backdrop path={m.backdrop_path ?? m.poster_path} height={220}>
                <View style={styles.hero}>
                  <Artwork path={m.poster_path} size={110} rounded />
                  <View style={styles.heroText}>
                    <Text style={styles.heroTitle} numberOfLines={3}>
                      {m.title}
                    </Text>
                    {facts ? <Text style={styles.facts}>{facts}</Text> : null}
                    {m.tagline ? <Text style={styles.tagline}>{m.tagline}</Text> : null}
                  </View>
                </View>
              </Backdrop>

              <View style={styles.below}>
              {fileId ? (
                <View style={styles.actions}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={resumeAt ? `Resume from ${formatTime(resumeAt)}` : "Play movie"}
                    onPress={() => router.push(`/watch/${fileId}${resumeAt ? `?resume=${resumeAt}` : ""}`)}
                    style={({ pressed }) => [styles.primary, pressed && styles.pressed]}
                  >
                    <Text style={styles.primaryText}>
                      {resumeAt ? `Resume from ${formatTime(resumeAt)}` : "Play"}
                    </Text>
                  </Pressable>
                  {resumeAt ? (
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel="Play from beginning"
                      onPress={() => router.push(`/watch/${fileId}?resume=0`)}
                      style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}
                    >
                      <Text style={styles.secondaryText}>From beginning</Text>
                    </Pressable>
                  ) : null}
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={watched ? "Mark unwatched" : "Mark watched"}
                    onPress={() => void toggleWatched()}
                    style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}
                  >
                    <Text style={styles.secondaryText}>{watched ? "Mark unwatched" : "Mark watched"}</Text>
                  </Pressable>
                  <DownloadButton
                    mediaFileId={fileId}
                    title={m.title}
                    opts={{
                      kind: "movie",
                      meta: {
                        coverPath: m.poster_path ?? null,
                        durationSec: m.runtime_min ? m.runtime_min * 60 : null,
                        container: m.media_files?.[0]?.container ?? null,
                      },
                    }}
                  />
                </View>
              ) : (
                <Text style={styles.muted}>This movie has no playable file yet.</Text>
              )}

              {m.overview ? <Text style={styles.overview}>{m.overview}</Text> : null}

              {m.genres && m.genres.length > 0 ? (
                <Text style={styles.credit}>
                  <Text style={styles.creditLabel}>Genres  </Text>
                  {m.genres.join(", ")}
                </Text>
              ) : null}
              {m.directors && m.directors.length > 0 ? (
                <Text style={styles.credit}>
                  <Text style={styles.creditLabel}>Directed by  </Text>
                  {m.directors.map(personName).filter(Boolean).join(", ")}
                </Text>
              ) : null}
              {m.cast && m.cast.length > 0 ? (
                <View style={styles.castWrap}>
                  <Text style={styles.creditLabel}>Cast</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.castRow}>
                    {m.cast.slice(0, 12).map((c, i) => {
                      const nm = personName(c);
                      if (!nm) return null;
                      return (
                        <View key={`${nm}-${i}`} style={styles.castChip}>
                          <Text style={styles.castName} numberOfLines={1}>
                            {nm}
                          </Text>
                        </View>
                      );
                    })}
                  </ScrollView>
                </View>
              ) : null}
              </View>
            </ScrollView>
          );
        }}
      </QueryState>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: spacing.xxl },
  below: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg },
  hero: { flexDirection: "row", gap: spacing.lg, padding: spacing.lg, alignItems: "flex-end" },
  heroText: { flex: 1, justifyContent: "flex-end", gap: spacing.xs },
  heroTitle: { ...typography.title, fontFamily: fonts.display, fontSize: 30, letterSpacing: 0.5 },
  facts: { ...typography.label },
  tagline: { ...typography.caption, fontStyle: "italic" },
  actions: { flexDirection: "row", gap: spacing.md, marginBottom: spacing.xl, flexWrap: "wrap" },
  primary: {
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.xl,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: { fontSize: 16, fontWeight: "700", color: colors.background },
  secondary: {
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.xl,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryText: { fontSize: 16, fontWeight: "600", color: colors.text },
  pressed: { opacity: 0.8 },
  muted: { ...typography.body, color: colors.textMuted, marginBottom: spacing.xl },
  overview: { ...typography.body, lineHeight: 24, color: colors.textMuted },
  credit: { ...typography.body, color: colors.textMuted, marginTop: spacing.md },
  creditLabel: { fontFamily: fonts.mono, fontSize: 11, color: colors.textFaint, letterSpacing: 1 },
  castWrap: { marginTop: spacing.lg, gap: spacing.sm },
  castRow: { gap: spacing.sm, paddingRight: spacing.lg },
  castChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: colors.surface,
  },
  castName: { fontFamily: fonts.uiMedium, fontSize: 13, color: colors.text, maxWidth: 140 },
});
