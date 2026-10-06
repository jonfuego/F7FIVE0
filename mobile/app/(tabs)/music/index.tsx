import { useRouter } from "expo-router";
import React, { useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text } from "react-native";

import { fetchMixSongs, MIXES, useAlbums, useArtists } from "@/api/queries";
import { usePlayer } from "@/player/PlayerProvider";
import { useApi } from "@/state/auth";
import { colors, fonts, radius, spacing } from "@/state/theme";
import { useViewPref } from "@/state/viewPrefs";
import { HubScreen } from "@/ui/HubScreen";
import { MarqueeHeader } from "@/ui/MarqueeHeader";
import { Rail } from "@/ui/Rail";
import { Tile } from "@/ui/Tile";
import { AlbumsLibrary } from "./albums";
import { ArtistsLibrary } from "./artists";
import { MixesLibrary } from "./mixes";
import { SongsLibrary } from "./songs";

const RAIL_TILE = 104;

/** Music "All" view: shelves of new albums, artists and one-tap mixes, each
 * with SEE ALL into its grid (Plexamp-style landing). */
function MusicAll({ select }: { select: (key: string) => void }): React.ReactElement {
  const router = useRouter();
  const api = useApi();
  const { playSongs } = usePlayer();
  const albums = useAlbums();
  const artists = useArtists();
  const [busy, setBusy] = useState<string | null>(null);

  const newAlbums = useMemo(
    () =>
      [...(albums.data ?? [])]
        .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))
        .slice(0, 20),
    [albums.data],
  );
  const featured = useMemo(
    () => (artists.data ?? []).filter((a) => !!a.image_path).slice(0, 20),
    [artists.data],
  );

  const playMix = async (id: string) => {
    if (busy) return;
    setBusy(id);
    try {
      const rows = await fetchMixSongs(api, id);
      if (rows.length > 0) await playSongs(rows, 0);
    } finally {
      setBusy(null);
    }
  };

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Rail title="New Albums" onSeeAll={() => select("albums")}>
        {newAlbums.map((a) => (
          <Tile
            key={a.id}
            title={a.title}
            subtitle={a.artist_name}
            artPath={a.cover_path}
            size={RAIL_TILE}
            compact
            showSubtitle
            onPress={() => router.push(`/music/album/${a.id}`)}
          />
        ))}
      </Rail>
      <Rail title="Featured Artists" onSeeAll={() => select("artists")}>
        {featured.map((a) => (
          <Tile
            key={a.id}
            title={a.name}
            subtitle={`${a.album_count} albums`}
            artPath={a.image_path}
            size={RAIL_TILE}
            compact
            showSubtitle
            onPress={() => router.push(`/music/artist/${a.id}`)}
          />
        ))}
      </Rail>
      <Rail title="Your Mixes" onSeeAll={() => select("mixes")}>
        {MIXES.map((m) => (
          <Pressable
            key={m.id}
            onPress={() => void playMix(m.id)}
            accessibilityRole="button"
            accessibilityLabel={`Play ${m.title} mix`}
            style={({ pressed, focused }) => [styles.mix, focused && styles.mixFocused, pressed && styles.pressed]}
          >
            <Text style={styles.mixTitle} numberOfLines={2}>
              {m.title}
            </Text>
            <Text style={styles.mixSub} numberOfLines={2}>
              {busy === m.id ? "Loading..." : m.subtitle}
            </Text>
          </Pressable>
        ))}
      </Rail>
    </ScrollView>
  );
}

const MUSIC_TABS = ["all", "artists", "albums", "songs", "mixes"];
function isMusicTab(v: unknown): v is string {
  return typeof v === "string" && MUSIC_TABS.includes(v);
}

/** Music tab: web-style BROWSE chips (All / Artists / Albums / Songs / Mixes).
 * "All" shows shelves; each other chip shows that library inline. The chosen
 * chip is a saved view on the server, per user. */
export default function MusicHome(): React.ReactElement {
  const [tab, setTab] = useViewPref("hub:music", "all", isMusicTab);
  return (
    <HubScreen
      header={<MarqueeHeader />}
      selected={tab}
      onSelect={setTab}
      sections={[
        { key: "all", label: "All", title: "Music", render: (select) => <MusicAll select={select} /> },
        { key: "artists", label: "Artists", title: "Music", render: () => <ArtistsLibrary /> },
        { key: "albums", label: "Albums", title: "Music", render: () => <AlbumsLibrary /> },
        { key: "songs", label: "Songs", title: "Music", render: () => <SongsLibrary /> },
        { key: "mixes", label: "Mixes", title: "Mixes", render: () => <MixesLibrary /> },
      ]}
    />
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 140 },
  mix: {
    width: 150,
    minHeight: 96,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.bg2,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    gap: spacing.xs,
  },
  mixFocused: { borderColor: colors.accent, borderWidth: 2 },
  pressed: { opacity: 0.75 },
  mixTitle: { fontFamily: fonts.display, fontSize: 20, letterSpacing: 0.5, color: colors.text },
  mixSub: { fontFamily: fonts.ui, fontSize: 11, color: colors.textMuted },
});
