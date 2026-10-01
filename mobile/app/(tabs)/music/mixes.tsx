import { Ionicons } from "@expo/vector-icons";
import React, { useMemo, useState } from "react";
import { FlatList, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { fetchAutoPlaylistById, fetchMixSongs, useArtists } from "@/api/queries";
import { useDownloads } from "@/download/DownloadProvider";
import { songEntries } from "@/download/entries";
import { usePlayer } from "@/player/PlayerProvider";
import { useApi } from "@/state/auth";
import { colors, fonts, MIN_TOUCH, radius, spacing } from "@/state/theme";
import { LibraryScreen } from "@/ui/LibraryScreen";

// Every auto-playlist kind the backend exposes (app/api/auto_playlist.py, 12
// routes). Six need no parameter; five are parameterized (pickers below); and
// "track-radio" (sonic radio, Phase 2) is seeded by the playing track.
const SIMPLE_KINDS: { slug: string; title: string; subtitle: string }[] = [
  { slug: "random", title: "Shuffle All", subtitle: "Random picks from the library" },
  { slug: "recently-added", title: "Recently Added", subtitle: "Fresh in the library" },
  { slug: "most-played", title: "Most Played", subtitle: "Your heavy rotation" },
  { slug: "recently-played", title: "Recently Played", subtitle: "Back to what you had on" },
  { slug: "continue-listening", title: "Continue Listening", subtitle: "Pick up where you left off" },
  { slug: "never-played", title: "Never Played", subtitle: "Tracks you haven't heard yet" },
];

// Parameterized kinds: by-year, by-decade, by-genre (typed / chips) and
// by-artist, artist-radio (an artist chooser, not a pasted id).
const PICKERS: { slug: string; title: string; label: string; placeholder: string; keyboard: "numeric" | "default" }[] = [
  { slug: "by-year", title: "By Year", label: "Year", placeholder: "1994", keyboard: "numeric" },
  { slug: "by-decade", title: "By Decade", label: "Decade", placeholder: "1990", keyboard: "numeric" },
  { slug: "by-genre", title: "By Genre", label: "Genre", placeholder: "post-punk", keyboard: "default" },
];
const DECADES = ["1960", "1970", "1980", "1990", "2000", "2010", "2020"];
const ARTIST_PICKERS: { slug: "by-artist" | "artist-radio"; title: string }[] = [
  { slug: "by-artist", title: "By Artist" },
  { slug: "artist-radio", title: "Artist Radio" },
];
const TRACK_RADIO = "track-radio";

/** The Mixes wall (every auto-playlist kind + pickers). Page + hub (Mixes chip). */
export function MixesLibrary(): React.ReactElement {
  const api = useApi();
  const { playSongs, nowPlaying } = usePlayer();
  const { enqueueMany } = useDownloads();
  const [savedMix, setSavedMix] = useState<string | null>(null);

  // Download a whole mix for offline play (spec J: album, mix, song, movie,
  // episode). The mix is resolved now and its tracks are queued as files.
  const downloadMix = async (slug: string, title: string) => {
    if (busy) return;
    setBusy(`dl-${slug}`);
    try {
      const rows = await fetchMixSongs(api, slug);
      const n = enqueueMany(songEntries(rows, title));
      setSavedMix(n > 0 ? `${title}: ${n} tracks queued for download` : "Storage limit reached");
    } catch {
      setSavedMix("Couldn't load that mix");
    } finally {
      setBusy(null);
    }
  };
  const [busy, setBusy] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [artistFor, setArtistFor] = useState<Record<string, { id: string; name: string }>>({});
  const [choosing, setChoosing] = useState<null | "by-artist" | "artist-radio">(null);
  const [query, setQuery] = useState("");
  const artists = useArtists();
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const all = artists.data ?? [];
    return (q ? all.filter((a) => a.name.toLowerCase().includes(q)) : all).slice(0, 200);
  }, [artists.data, query]);

  const playBy = async (slug: string, id: string) => {
    if (!id || busy) return;
    setBusy(slug);
    try {
      const rows = await fetchAutoPlaylistById(api, slug, id);
      if (rows.length > 0) await playSongs(rows, 0);
    } finally {
      setBusy(null);
    }
  };

  const playSimple = async (slug: string) => {
    if (busy) return;
    setBusy(slug);
    try {
      const rows = await fetchMixSongs(api, slug);
      if (rows.length > 0) await playSongs(rows, 0);
    } finally {
      setBusy(null);
    }
  };

  const playParam = async (slug: string) => {
    const v = (values[slug] ?? "").trim();
    if (!v || busy) return;
    setBusy(slug);
    try {
      const rows = await fetchAutoPlaylistById(api, slug, v);
      if (rows.length > 0) await playSongs(rows, 0);
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.grid}>
          {SIMPLE_KINDS.map((m) => (
            <Pressable
              key={m.slug}
              accessibilityRole="button"
              accessibilityLabel={m.title}
              onPress={() => void playSimple(m.slug)}
              style={({ pressed }) => [styles.card, pressed && styles.pressed]}
            >
              <View style={styles.cardTop}>
                <Ionicons name="sparkles" size={20} color={colors.bulb} />
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Download ${m.title} mix`}
                  hitSlop={10}
                  onPress={() => void downloadMix(m.slug, m.title)}
                  style={styles.dlBtn}
                >
                  <Ionicons
                    name={busy === `dl-${m.slug}` ? "hourglass" : "download-outline"}
                    size={18}
                    color={colors.textMuted}
                  />
                </Pressable>
              </View>
              <Text style={styles.cardTitle}>{m.title}</Text>
              <Text style={styles.cardSub} numberOfLines={2}>
                {busy === m.slug ? "Loading..." : m.subtitle}
              </Text>
            </Pressable>
          ))}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Track Radio"
            disabled={!nowPlaying?.trackId}
            onPress={() => nowPlaying?.trackId && void playBy(TRACK_RADIO, nowPlaying.trackId)}
            style={({ pressed }) => [styles.card, pressed && styles.pressed, !nowPlaying?.trackId && styles.off]}
          >
            <Ionicons name="radio" size={20} color={colors.bulb} />
            <Text style={styles.cardTitle}>Track Radio</Text>
            <Text style={styles.cardSub} numberOfLines={2}>
              {busy === TRACK_RADIO
                ? "Loading..."
                : nowPlaying?.trackId
                  ? `Sonically like "${nowPlaying.title}"`
                  : "Play a song to seed it"}
            </Text>
          </Pressable>
        </View>

        {savedMix ? (
          <Text style={styles.notice} accessibilityLiveRegion="polite">
            {savedMix}
          </Text>
        ) : null}

        <Text style={styles.section}>Build a mix</Text>
        {ARTIST_PICKERS.map((p) => (
          <View key={p.slug} style={styles.pickerRow}>
            <Text style={styles.pickerTitle}>{p.title}</Text>
            <View style={styles.pickerInputs}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`${p.title} choose artist`}
                onPress={() => {
                  setQuery("");
                  setChoosing(p.slug);
                }}
                style={[styles.input, styles.chooser]}
              >
                <Text style={artistFor[p.slug] ? styles.chosen : styles.placeholder} numberOfLines={1}>
                  {artistFor[p.slug]?.name ?? "Choose an artist"}
                </Text>
                <Ionicons name="chevron-down" size={16} color={colors.textMuted} />
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Play ${p.title}`}
                disabled={!artistFor[p.slug]}
                onPress={() => artistFor[p.slug] && void playBy(p.slug, artistFor[p.slug].id)}
                style={({ pressed }) => [styles.playBtn, pressed && styles.pressed, !artistFor[p.slug] && styles.off]}
              >
                <Text style={styles.playText}>{busy === p.slug ? "..." : "Play"}</Text>
              </Pressable>
            </View>
          </View>
        ))}
        {PICKERS.map((p) => (
          <View key={p.slug} style={styles.pickerRow}>
            <Text style={styles.pickerTitle}>{p.title}</Text>
            <View style={styles.pickerInputs}>
              <TextInput
                style={styles.input}
                value={values[p.slug] ?? ""}
                onChangeText={(t) => setValues((prev) => ({ ...prev, [p.slug]: t }))}
                placeholder={p.placeholder}
                placeholderTextColor={colors.textFaint}
                keyboardType={p.keyboard}
                accessibilityLabel={`${p.title} ${p.label}`}
              />
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Play ${p.title}`}
                onPress={() => void playParam(p.slug)}
                style={({ pressed }) => [styles.playBtn, pressed && styles.pressed]}
              >
                <Text style={styles.playText}>{busy === p.slug ? "..." : "Play"}</Text>
              </Pressable>
            </View>
            {p.slug === "by-decade" ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.decades}>
                {DECADES.map((d) => (
                  <Pressable
                    key={d}
                    accessibilityRole="button"
                    accessibilityLabel={`Decade ${d}s`}
                    onPress={() => {
                      setValues((prev) => ({ ...prev, "by-decade": d }));
                      void playBy("by-decade", d);
                    }}
                    style={[styles.decade, values["by-decade"] === d && styles.decadeOn]}
                  >
                    <Text style={[styles.decadeTxt, values["by-decade"] === d && styles.decadeTxtOn]}>{d}s</Text>
                  </Pressable>
                ))}
              </ScrollView>
            ) : null}
          </View>
        ))}
      </ScrollView>

      <Modal visible={choosing !== null} animationType="slide" transparent onRequestClose={() => setChoosing(null)}>
        <View style={styles.sheetBackdrop}>
          <View style={styles.sheet}>
            <View style={styles.sheetHead}>
              <Text style={styles.pickerTitle}>Choose an artist</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="Close artist chooser" onPress={() => setChoosing(null)} style={styles.closeBtn}>
                <Ionicons name="close" size={22} color={colors.text} />
              </Pressable>
            </View>
            <TextInput
              style={styles.input}
              value={query}
              onChangeText={setQuery}
              placeholder="Search artists"
              placeholderTextColor={colors.textFaint}
              accessibilityLabel="Search artists"
              autoFocus
            />
            <FlatList
              data={matches}
              keyExtractor={(a) => a.id}
              keyboardShouldPersistTaps="handled"
              renderItem={({ item }) => (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Artist ${item.name}`}
                  onPress={() => {
                    if (choosing) setArtistFor((prev) => ({ ...prev, [choosing]: { id: item.id, name: item.name } }));
                    setChoosing(null);
                  }}
                  style={({ pressed }) => [styles.artistRow, pressed && styles.pressed]}
                >
                  <Text style={styles.chosen} numberOfLines={1}>
                    {item.name}
                  </Text>
                  <Text style={styles.cardSub}>{item.album_count} albums</Text>
                </Pressable>
              )}
              ListEmptyComponent={
                <Text style={[styles.cardSub, { padding: spacing.md }]}>
                  {artists.isLoading ? "Loading artists..." : "No matching artists."}
                </Text>
              }
            />
          </View>
        </View>
      </Modal>
    </View>
  );
}

export default function MixesScreen(): React.ReactElement {
  return (
    <LibraryScreen title="Mixes">
      <MixesLibrary />
    </LibraryScreen>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, paddingBottom: 140 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, justifyContent: "space-between" },
  card: {
    width: "48%",
    minHeight: 96,
    backgroundColor: colors.bg2,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    padding: spacing.md,
    gap: spacing.xs,
    marginBottom: spacing.md,
  },
  cardTitle: { fontFamily: fonts.display, fontSize: 22, letterSpacing: 0.5, color: colors.text },
  cardSub: { fontFamily: fonts.ui, fontSize: 12, color: colors.textMuted },
  pressed: { opacity: 0.75 },
  section: { fontFamily: fonts.mono, fontSize: 12, letterSpacing: 2, color: colors.textFaint, marginTop: spacing.lg, marginBottom: spacing.sm },
  pickerRow: { marginBottom: spacing.md },
  pickerTitle: { fontFamily: fonts.uiSemiBold, fontSize: 15, color: colors.text, marginBottom: spacing.xs },
  pickerInputs: { flexDirection: "row", gap: spacing.sm },
  input: {
    flex: 1,
    minHeight: MIN_TOUCH,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    color: colors.text,
    paddingHorizontal: spacing.md,
    fontFamily: fonts.ui,
    fontSize: 15,
  },
  playBtn: {
    minWidth: 72,
    minHeight: MIN_TOUCH,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.pill,
    backgroundColor: colors.bulb,
  },
  playText: { fontFamily: fonts.uiSemiBold, color: colors.background, fontSize: 15 },
  off: { opacity: 0.45 },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  dlBtn: { minWidth: 32, minHeight: 32, alignItems: "flex-end", justifyContent: "center" },
  notice: { fontFamily: fonts.mono, fontSize: 12, color: colors.bulb, marginTop: spacing.sm },
  chooser: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  chosen: { fontFamily: fonts.ui, fontSize: 15, color: colors.text, flexShrink: 1 },
  placeholder: { fontFamily: fonts.ui, fontSize: 15, color: colors.textFaint },
  decades: { gap: spacing.sm, paddingTop: spacing.sm },
  decade: {
    minHeight: 36,
    paddingHorizontal: spacing.md,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    justifyContent: "center",
  },
  decadeOn: { backgroundColor: colors.bulb, borderColor: colors.bulb },
  decadeTxt: { fontFamily: fonts.mono, fontSize: 12, color: colors.text },
  decadeTxtOn: { color: colors.background },
  sheetBackdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: "flex-end" },
  sheet: {
    height: "75%",
    backgroundColor: colors.bg2,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  closeBtn: { minWidth: MIN_TOUCH, minHeight: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
  artistRow: {
    minHeight: MIN_TOUCH,
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
    justifyContent: "center",
  },
});
