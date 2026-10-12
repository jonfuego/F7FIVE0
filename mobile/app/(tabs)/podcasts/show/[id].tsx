import { useLocalSearchParams, useRouter } from "expo-router";
import { ChevronLeft } from "lucide-react-native";
import React, { useMemo, useState } from "react";
import { Alert, FlatList, Pressable, StyleSheet, Switch, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  invalidatePodcasts,
  requestServerDownload,
  setAutoDownload,
  setEpisodePlayed,
  subscribe,
  unsubscribe,
  usePodcast,
} from "@/api/podcasts";
import type { PodcastEpisodeRow, PodcastShow } from "@/api/types";
import { useDownloads } from "@/download/DownloadProvider";
import { usePlayer } from "@/player/PlayerProvider";
import { useApi } from "@/state/auth";
import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { Artwork } from "@/ui/Artwork";
import { ChipBar } from "@/ui/ChipBar";
import { IconButton } from "@/ui/IconButton";
import { PodcastEpisodeRow as EpisodeRowView } from "@/ui/PodcastEpisodeRow";
import { filterEpisodes, type EpisodeFilter } from "@/ui/podcastState";
import { QueryState } from "@/ui/QueryState";

const FRIENDLY: Record<string, string> = {
  no_podcast_folder: "The server has no podcasts folder yet. An admin can add one in Admin > Library folders.",
  podcast_folder_unreachable: "The server's podcasts folder can't be opened right now.",
  not_subscribed: "Follow the show first.",
  video_not_supported: "Video podcasts aren't supported yet.",
};

function messageFor(e: unknown): string {
  const detail = (e as { body?: { detail?: string } } | null)?.body?.detail;
  return (detail && FRIENDLY[detail]) || "Something went wrong. Try again.";
}

/** One show: art, description (plain text), follow / unfollow, auto-download,
 * and the episodes newest first with All / Unplayed / Downloaded filters. Each
 * episode plays, downloads to the phone (works offline afterwards), can be
 * saved to the server, and can be marked played. */
export default function PodcastShowScreen(): React.ReactElement {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const query = usePodcast(id);
  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <View style={styles.top}>
        <IconButton icon={ChevronLeft} onPress={() => router.back()} accessibilityLabel="Back" />
      </View>
      <QueryState
        isLoading={query.isLoading}
        isError={query.isError}
        data={query.data}
        onRetry={() => void query.refetch()}
      >
        {(data) => <Show show={data.podcast} episodes={data.episodes} total={data.total} />}
      </QueryState>
    </SafeAreaView>
  );
}

function Show({
  show,
  episodes,
  total,
}: {
  show: PodcastShow;
  episodes: PodcastEpisodeRow[];
  total: number;
}): React.ReactElement {
  const api = useApi();
  const { playEpisode } = usePlayer();
  const { isDownloaded } = useDownloads();
  const [filter, setFilter] = useState<EpisodeFilter>("all");
  const [busy, setBusy] = useState(false);

  const shown = useMemo(
    () => filterEpisodes(episodes, filter, isDownloaded),
    [episodes, filter, isDownloaded],
  );

  const play = async (ep: PodcastEpisodeRow) => {
    const ok = await playEpisode({
      id: ep.id,
      podcastId: show.id,
      title: ep.title,
      showTitle: show.title,
      coverPath: show.art_url,
      durationSec: ep.duration_sec,
    });
    if (!ok) Alert.alert("Can't play that", "It isn't downloaded and the server can't be reached.");
  };

  const guarded = async (run: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    try {
      await run();
    } catch (e) {
      Alert.alert("Couldn't do that", messageFor(e));
    } finally {
      setBusy(false);
    }
  };

  const header = (
    <View style={styles.header}>
      <View style={styles.hero}>
        <Artwork path={show.art_url} size={120} rounded />
        <View style={styles.heroMeta}>
          <Text style={styles.title} numberOfLines={3}>{show.title}</Text>
          {show.author ? <Text style={styles.author} numberOfLines={2}>{show.author}</Text> : null}
        </View>
      </View>
      <Pressable
        onPress={() =>
          void guarded(() =>
            show.subscribed ? unsubscribe(api, show.id) : subscribe(api, { podcastId: show.id }),
          )
        }
        disabled={busy}
        accessibilityRole="button"
        accessibilityLabel={show.subscribed ? `Unfollow ${show.title}` : `Follow ${show.title}`}
        style={[show.subscribed ? styles.outlineBtn : styles.followBtn, busy && styles.off]}
      >
        <Text style={show.subscribed ? styles.outlineTxt : styles.followTxt}>
          {show.subscribed ? "Unfollow" : "Follow"}
        </Text>
      </Pressable>
      {show.subscribed ? (
        <View style={styles.toggleRow}>
          <Text style={styles.toggleText}>Download new episodes to the server</Text>
          <Switch
            value={show.auto_download}
            onValueChange={(on) => void guarded(() => setAutoDownload(api, show.id, on))}
            disabled={busy}
            accessibilityLabel="Download new episodes to the server"
            trackColor={{ true: colors.accent, false: colors.line }}
            thumbColor={colors.text}
          />
        </View>
      ) : null}
      {show.description ? <Text style={styles.description}>{show.description}</Text> : null}
      {show.last_error ? (
        <Text style={styles.warn}>
          The last check of this feed failed: {show.last_error}. The episodes are from the last good copy.
        </Text>
      ) : null}
      <ChipBar
        label={`Episodes ${total}`}
        options={[
          { key: "all", label: "All" },
          { key: "unplayed", label: "Unplayed" },
          { key: "downloaded", label: "Downloaded" },
        ]}
        value={filter}
        onChange={(k) => setFilter(k as EpisodeFilter)}
        divider={false}
      />
    </View>
  );

  return (
    <FlatList
      data={shown}
      keyExtractor={(e) => e.id}
      ListHeaderComponent={header}
      contentContainerStyle={styles.list}
      renderItem={({ item }) => (
        <View style={styles.rowWrap}>
          <EpisodeRowView
            ep={item}
            show={show}
            subscribed={show.subscribed}
            onPlay={() => void play(item)}
            onTogglePlayed={() =>
              void guarded(async () => {
                await setEpisodePlayed(api, item.id, item.state.kind !== "played");
                invalidatePodcasts();
              })
            }
            onServerDownload={() =>
              void guarded(async () => {
                await requestServerDownload(api, item.id);
                Alert.alert("Queued", "The server will download this episode into its podcasts folder.");
              })
            }
          />
        </View>
      )}
      ListEmptyComponent={
        <Text style={styles.empty}>
          {filter === "downloaded"
            ? "No downloaded episodes of this show."
            : filter === "unplayed"
              ? "Everything is played."
              : show.last_checked_at
                ? "No episodes in this feed."
                : "Fetching the feed. Check back in a moment."}
        </Text>
      }
    />
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  top: { paddingHorizontal: spacing.sm },
  list: { paddingBottom: 140 },
  rowWrap: { paddingHorizontal: spacing.lg },
  header: { gap: spacing.md, paddingBottom: spacing.sm },
  hero: { flexDirection: "row", gap: spacing.lg, paddingHorizontal: spacing.lg },
  heroMeta: { flex: 1, justifyContent: "center", gap: spacing.xs },
  title: { ...typography.title },
  author: { ...typography.body, color: colors.textMuted },
  followBtn: {
    marginHorizontal: spacing.lg,
    minHeight: MIN_TOUCH,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  followTxt: { color: colors.background, fontWeight: "700" },
  outlineBtn: {
    marginHorizontal: spacing.lg,
    minHeight: MIN_TOUCH,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
  },
  outlineTxt: { color: colors.text, fontWeight: "600" },
  off: { opacity: 0.5 },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    minHeight: MIN_TOUCH,
  },
  toggleText: { ...typography.body, flex: 1, paddingRight: spacing.md },
  description: { ...typography.body, color: colors.textMuted, paddingHorizontal: spacing.lg },
  warn: { ...typography.caption, color: colors.accent, paddingHorizontal: spacing.lg },
  empty: { ...typography.body, color: colors.textMuted, padding: spacing.lg },
});
