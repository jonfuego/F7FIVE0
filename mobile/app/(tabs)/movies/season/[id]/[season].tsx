import { useLocalSearchParams, useRouter } from "expo-router";
import { ArrowLeft } from "lucide-react-native";
import React, { useMemo } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { useSeries } from "@/api/queries";
import { colors, MIN_TOUCH, spacing, typography } from "@/state/theme";
import { EpisodeFileMenu } from "@/ui/EpisodeFileMenu";
import { IconButton } from "@/ui/IconButton";
import { QueryState } from "@/ui/QueryState";
import { Screen } from "@/ui/Screen";
import { episodesForSeason, parseSeason, seasonTitle } from "@/ui/seasons";

/** One season of a show (`/movies/season/<seriesId>/<n>`): its episodes,
 * each playable and with the File info menu, and a Back arrow to the show.
 * Reached from the season heading on the show screen. */
export default function SeasonScreen(): React.ReactElement {
  const { id, season: seasonParam } = useLocalSearchParams<{ id: string; season: string }>();
  const router = useRouter();
  const series = useSeries(id ?? "");
  const season = parseSeason(seasonParam);
  const episodes = useMemo(
    () => (series.data && season !== null ? episodesForSeason(series.data.episodes, season) : []),
    [series.data, season],
  );
  const back = () => (router.canGoBack() ? router.back() : router.replace(`/movies/show/${id}`));

  return (
    <Screen
      title={season !== null ? seasonTitle(season) : "Season"}
      right={<IconButton icon={ArrowLeft} accessibilityLabel="Back" onPress={back} />}
    >
      <QueryState
        isLoading={series.isLoading}
        isError={series.isError}
        data={series.data}
        onRetry={series.refetch}
        isEmpty={() => episodes.length === 0}
        emptyTitle="No episodes"
        emptyMessage="This season has no episodes in your library."
      >
        {(s) => (
          <ScrollView
            contentContainerStyle={styles.content}
            refreshControl={
              <RefreshControl refreshing={series.isFetching} onRefresh={series.refetch} tintColor={colors.accent} />
            }
          >
            <Text style={styles.show} numberOfLines={1}>
              {s.title}
            </Text>
            {episodes.map((ep) => {
              const fileId = ep.media_files[0]?.id;
              const label = `${ep.episode_number}. ${ep.title ?? `Episode ${ep.episode_number}`}`;
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
                  {ep.media_files[0] ? (
                    <EpisodeFileMenu
                      file={ep.media_files[0]}
                      label={`S${ep.season_number}E${ep.episode_number} ${ep.title ?? `Episode ${ep.episode_number}`}`}
                    />
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
  show: { ...typography.caption, color: colors.textMuted, marginBottom: spacing.md },
  muted: { ...typography.caption, color: colors.textMuted },
  episode: {
    minHeight: MIN_TOUCH,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  epMain: { flex: 1, paddingVertical: spacing.md, gap: spacing.xs },
  epTitle: { ...typography.body, fontWeight: "600" },
  pressed: { opacity: 0.7 },
  disabled: { opacity: 0.4 },
});
