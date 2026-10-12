import { useRouter } from "expo-router";
import { Trash2 } from "lucide-react-native";
import React, { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { searchPodcasts, subscribe, usePodcastHome } from "@/api/podcasts";
import type { PodcastEpisodeRow, PodcastSearch, PodcastShow } from "@/api/types";
import { useDownloads } from "@/download/DownloadProvider";
import { downloadToEpisode } from "@/download/podcastEntries";
import { doneItems } from "@/download/queue";
import { usePlayer } from "@/player/PlayerProvider";
import { useApi } from "@/state/auth";
import { colors, fonts, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { useViewPref } from "@/state/viewPrefs";
import { formatBytes } from "@/download/format";
import { Artwork } from "@/ui/Artwork";
import { ChipBar } from "@/ui/ChipBar";
import { IconButton } from "@/ui/IconButton";
import { MarqueeHeader } from "@/ui/MarqueeHeader";
import { PageTitle } from "@/ui/PageTitle";
import { QueryState } from "@/ui/QueryState";
import { Rail } from "@/ui/Rail";
import { Tile } from "@/ui/Tile";

const TILE = 104;
const VIEWS = ["all", "downloaded"];
function isView(v: unknown): v is string {
  return typeof v === "string" && VIEWS.includes(v);
}

const FRIENDLY: Record<string, string> = {
  feed_unreachable: "That feed could not be reached.",
  feed_invalid: "That address is not a podcast feed.",
  feed_blocked: "That address is not allowed (it points at this network).",
  request_failed_502: "The podcast directory could not be reached right now.",
};

function errorText(e: unknown): string {
  const message = e instanceof Error ? e.message : "";
  const body = (e as { body?: { detail?: string } } | null)?.body;
  const detail = body?.detail ?? message;
  return FRIENDLY[detail] ?? FRIENDLY[message] ?? "Something went wrong. Try again.";
}

/** Podcasts tab: In progress, My podcasts and On this server rails, search and
 * add by feed URL, and a Downloaded filter that lists what is on this phone.
 * Phone only (the TV layout does not list this tab). Subscriptions and progress
 * are per person. */
export default function PodcastsHome(): React.ReactElement {
  const [view, setView] = useViewPref("hub:podcasts", "all", isView);
  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <MarqueeHeader />
      <PageTitle>Podcasts</PageTitle>
      <ChipBar
        label="Show"
        options={[
          { key: "all", label: "All" },
          { key: "downloaded", label: "Downloaded" },
        ]}
        value={view}
        onChange={setView}
      />
      <View style={styles.body}>{view === "downloaded" ? <DownloadedEpisodes /> : <AllPodcasts />}</View>
    </SafeAreaView>
  );
}

function AllPodcasts(): React.ReactElement {
  const router = useRouter();
  const home = usePodcastHome();
  const { playEpisode } = usePlayer();
  const open = (id: string) => router.push(`/podcasts/show/${id}`);

  const resume = async (ep: PodcastEpisodeRow) => {
    const ok = await playEpisode({
      id: ep.id,
      podcastId: ep.podcast_id,
      title: ep.title,
      showTitle: ep.podcast_title ?? "",
      coverPath: ep.art_url,
      durationSec: ep.duration_sec,
    });
    if (!ok) Alert.alert("Can't play that", "It isn't downloaded and the server can't be reached.");
  };

  return (
    <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      <FindShows onOpen={open} />
      <QueryState
        isLoading={home.isLoading}
        isError={home.isError}
        data={home.data}
        onRetry={() => void home.refetch()}
      >
        {(data) => {
          const mineIds = new Set(data.mine.map((s) => s.id));
          const onServer = data.on_server.filter((s) => !mineIds.has(s.id));
          return (
            <>
              {data.in_progress.length > 0 ? (
                <Rail title="In progress">
                  {data.in_progress.map((ep) => (
                    <Tile
                      key={ep.id}
                      title={ep.title}
                      subtitle={ep.podcast_title}
                      artPath={ep.art_url}
                      size={TILE}
                      compact
                      showSubtitle
                      onPress={() => void resume(ep)}
                    />
                  ))}
                </Rail>
              ) : null}
              <Rail title="My podcasts">
                {data.mine.map((show) => (
                  <ShowTile key={show.id} show={show} onPress={() => open(show.id)} />
                ))}
              </Rail>
              {data.mine.length === 0 ? (
                <Text style={styles.empty}>You are not following any podcasts yet. Search above, or paste a feed address.</Text>
              ) : null}
              {onServer.length > 0 ? (
                <Rail title="On this server">
                  {onServer.map((show) => (
                    <ShowTile key={show.id} show={show} onPress={() => open(show.id)} />
                  ))}
                </Rail>
              ) : null}
            </>
          );
        }}
      </QueryState>
    </ScrollView>
  );
}

function ShowTile({ show, onPress }: { show: PodcastShow; onPress: () => void }): React.ReactElement {
  return (
    <Tile
      title={show.title}
      subtitle={show.author}
      artPath={show.art_url}
      size={TILE}
      compact
      showSubtitle
      onPress={onPress}
    />
  );
}

/** Search the directory and add by feed URL. */
function FindShows({ onOpen }: { onOpen: (id: string) => void }): React.ReactElement {
  const api = useApi();
  const [q, setQ] = useState("");
  const [feed, setFeed] = useState("");
  const [results, setResults] = useState<PodcastSearch | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const runSearch = async () => {
    const term = q.trim();
    if (!term || busy) return;
    setBusy("search");
    setMessage(null);
    try {
      setResults(await searchPodcasts(api, term));
    } catch (e) {
      setResults(null);
      setMessage(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  const follow = async (feedUrl: string, key: string) => {
    if (busy) return;
    setBusy(key);
    setMessage(null);
    try {
      const show = await subscribe(api, { feedUrl });
      setResults(null);
      setQ("");
      setFeed("");
      onOpen(show.id);
    } catch (e) {
      setMessage(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={styles.find}>
      <View style={styles.inputRow}>
        <TextInput
          value={q}
          onChangeText={setQ}
          placeholder="Search for a podcast"
          placeholderTextColor={colors.textFaint}
          accessibilityLabel="Search for a podcast"
          returnKeyType="search"
          onSubmitEditing={() => void runSearch()}
          style={styles.input}
        />
        <Pressable
          onPress={() => void runSearch()}
          disabled={!q.trim() || busy !== null}
          accessibilityRole="button"
          accessibilityLabel="Search podcasts"
          style={[styles.btn, (!q.trim() || busy !== null) && styles.off]}
        >
          {busy === "search" ? <ActivityIndicator color={colors.background} /> : <Text style={styles.btnTxt}>Search</Text>}
        </Pressable>
      </View>

      {results ? (
        results.results.length === 0 ? (
          <Text style={styles.empty}>Nothing found for that search.</Text>
        ) : (
          <View>
            {results.results.map((r) => (
              <View key={r.feed_url} style={styles.result}>
                <Artwork path={r.art_url} size={48} rounded />
                <View style={styles.resultMeta}>
                  <Text style={styles.resultTitle} numberOfLines={1}>{r.title}</Text>
                  {r.author ? <Text style={styles.resultSub} numberOfLines={1}>{r.author}</Text> : null}
                </View>
                <Pressable
                  onPress={() => void follow(r.feed_url, r.feed_url)}
                  disabled={busy !== null}
                  accessibilityRole="button"
                  accessibilityLabel={`Follow ${r.title}`}
                  style={[styles.follow, busy !== null && styles.off]}
                >
                  <Text style={styles.followTxt}>{busy === r.feed_url ? "Adding..." : "Follow"}</Text>
                </Pressable>
              </View>
            ))}
            <Text style={styles.resultSub}>
              Results from {results.provider === "podcastindex" ? "Podcast Index" : "Apple's iTunes directory"}.
            </Text>
          </View>
        )
      ) : null}

      <View style={styles.inputRow}>
        <TextInput
          value={feed}
          onChangeText={setFeed}
          placeholder="Add by feed URL (https://...)"
          placeholderTextColor={colors.textFaint}
          accessibilityLabel="Add by feed URL"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          returnKeyType="go"
          onSubmitEditing={() => feed.trim() && void follow(feed.trim(), "url")}
          style={styles.input}
        />
        <Pressable
          onPress={() => void follow(feed.trim(), "url")}
          disabled={!feed.trim() || busy !== null}
          accessibilityRole="button"
          accessibilityLabel="Add podcast by feed URL"
          style={[styles.btn, (!feed.trim() || busy !== null) && styles.off]}
        >
          <Text style={styles.btnTxt}>{busy === "url" ? "Adding..." : "Add"}</Text>
        </Pressable>
      </View>
      {message ? <Text style={styles.error}>{message}</Text> : null}
    </View>
  );
}

/** The Downloaded filter: episodes on this phone, playable with no connection,
 * each removable from the device. */
function DownloadedEpisodes(): React.ReactElement {
  const { state, remove, online } = useDownloads();
  const { playEpisode } = usePlayer();
  const items = doneItems(state, "podcast");

  const play = async (it: (typeof items)[number]) => {
    const ep = downloadToEpisode(it);
    await playEpisode({
      id: ep.id,
      podcastId: ep.podcastId,
      title: ep.title,
      showTitle: ep.showTitle,
      coverPath: ep.coverPath,
      durationSec: ep.durationSec,
    });
  };
  const confirmRemove = (id: string, title: string) => {
    Alert.alert("Delete download", `Remove "${title}" from this device?`, [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: () => void remove(id) },
    ]);
  };

  return (
    <ScrollView contentContainerStyle={styles.content}>
      {!online ? <Text style={styles.offline}>Offline - playing from downloads</Text> : null}
      {items.length === 0 ? (
        <Text style={styles.empty}>No downloaded episodes yet. Use the download button on an episode.</Text>
      ) : (
        items.map((it) => (
          <View key={it.id} style={styles.dl}>
            <Pressable
              style={styles.dlMeta}
              onPress={() => void play(it)}
              accessibilityRole="button"
              accessibilityLabel={`Play download ${it.title}`}
            >
              <Text style={styles.resultTitle} numberOfLines={2}>{it.title}</Text>
              <Text style={styles.resultSub} numberOfLines={1}>
                {[it.meta?.album, formatBytes(it.bytes)].filter(Boolean).join(" · ")}
              </Text>
            </Pressable>
            <IconButton
              icon={Trash2}
              onPress={() => confirmRemove(it.id, it.title)}
              accessibilityLabel={`Delete download of ${it.title}`}
              color={colors.danger}
            />
          </View>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  body: { flex: 1 },
  content: { paddingBottom: 140 },
  find: { padding: spacing.lg, gap: spacing.md },
  inputRow: { flexDirection: "row", gap: spacing.sm, alignItems: "center" },
  input: {
    flex: 1,
    minHeight: MIN_TOUCH,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
    color: colors.text,
    paddingHorizontal: spacing.md,
    fontFamily: fonts.ui,
    backgroundColor: colors.bg2,
  },
  btn: {
    minHeight: MIN_TOUCH,
    minWidth: 76,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  btnTxt: { color: colors.background, fontWeight: "700" },
  off: { opacity: 0.4 },
  result: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.sm },
  resultMeta: { flex: 1 },
  resultTitle: { ...typography.body, color: colors.text },
  resultSub: { ...typography.caption },
  follow: {
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.accent,
    justifyContent: "center",
  },
  followTxt: { color: colors.accent, fontWeight: "600" },
  empty: { ...typography.body, color: colors.textMuted, padding: spacing.lg },
  error: { color: colors.danger },
  offline: { ...typography.label, color: colors.accent, padding: spacing.lg },
  dl: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    minHeight: MIN_TOUCH + 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
  },
  dlMeta: { flex: 1, paddingVertical: spacing.sm },
});
