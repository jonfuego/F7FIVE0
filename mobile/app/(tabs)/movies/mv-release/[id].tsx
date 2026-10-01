import { useLocalSearchParams, useRouter } from "expo-router";
import React from "react";
import { RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { useMusicVideoRelease } from "@/api/queries";
import { colors, spacing, typography } from "@/state/theme";
import { Artwork } from "@/ui/Artwork";
import { QueryState } from "@/ui/QueryState";
import { Screen } from "@/ui/Screen";
import { TrackRow } from "@/ui/TrackRow";

/** Music video release: its videos; tapping one plays it full screen. */
export default function MusicVideoReleaseScreen(): React.ReactElement {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const release = useMusicVideoRelease(id ?? "");

  return (
    <Screen title="Music Videos">
      <QueryState
        isLoading={release.isLoading}
        isError={release.isError}
        data={release.data}
        onRetry={release.refetch}
        isEmpty={(d) => d.videos.length === 0}
        emptyTitle="No videos"
        emptyMessage="This release has no videos yet."
      >
        {(r) => (
          <ScrollView
            refreshControl={
              <RefreshControl refreshing={release.isFetching} onRefresh={release.refetch} tintColor={colors.accent} />
            }
          >
            <View style={styles.header}>
              <Artwork path={r.cover_path} size={140} rounded />
              <Text style={styles.title}>{r.title}</Text>
              <Text style={styles.sub}>{r.artist_name}</Text>
            </View>
            {r.videos.map((v) => (
              <TrackRow
                key={v.id}
                title={v.title}
                subtitle={v.media_file_id ? r.artist_name : "Not available"}
                artPath={v.thumb_path ?? r.cover_path}
                onPress={() => {
                  if (v.media_file_id) router.push(`/watch/${v.media_file_id}`);
                }}
              />
            ))}
          </ScrollView>
        )}
      </QueryState>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: { alignItems: "center", gap: spacing.xs, paddingVertical: spacing.lg },
  title: { ...typography.heading, textAlign: "center" },
  sub: { ...typography.body, color: colors.textMuted },
});
