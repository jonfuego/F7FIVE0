// Shared 3-dot track menu for the player, used by the mini player and Now
// Playing so both surfaces list the same actions in the same order. Items that
// need an id the current track lacks are disabled, not hidden, so the menu
// shape stays stable.
//
// Go to album / Go to artist close Now Playing (via beforeNavigate) and then
// push the route. They never pause, stop, or reset TrackPlayer, so playback
// keeps going. The action logic lives in player/playerMenuActions so it can be
// unit tested without React.
//
// The Android TV bundle resolves PlayerTrackMenu.tv.tsx (a no-op stub) instead
// of this file, so none of these imports reach the TV build. Same pattern as
// the cast stubs (CastButton.tv.tsx).

import { useRouter } from "expo-router";
import { Disc3, Ellipsis, List, Radio, SkipForward, User } from "lucide-react-native";
import React, { useMemo, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import type { LucideIcon } from "lucide-react-native";

import { fetchAutoPlaylistById } from "@/api/queries";
import type { AlbumDetail, SongRow } from "@/api/types";
import { usePlayer } from "@/player/PlayerProvider";
import { createPlayerMenuActions } from "@/player/playerMenuActions";
import { useApi } from "@/state/auth";
import { colors, fonts, MIN_TOUCH, radius, spacing } from "@/state/theme";
import { Icon } from "./Icon";

export interface PlayerTrackMenuProps {
  albumId: string | null;
  artistId: string | null;
  /** Run before a navigation. Now Playing passes router.back to close itself;
   * the mini player has nothing to close and omits it. */
  beforeNavigate?: () => void;
  size?: number;
  color?: string;
}

export function PlayerTrackMenu({
  albumId,
  artistId,
  beforeNavigate,
  size = 24,
  color = colors.text,
}: PlayerTrackMenuProps): React.ReactElement {
  const router = useRouter();
  const api = useApi();
  const { playNext, addToQueue } = usePlayer();
  const [open, setOpen] = useState(false);

  const actions = useMemo(
    () =>
      createPlayerMenuActions({
        albumId,
        artistId,
        navigate: (path) => router.push(path as never),
        closeNowPlaying: () => beforeNavigate?.(),
        loadAlbumSongs: async () => {
          if (!albumId) return [];
          try {
            const detail = await api.json<AlbumDetail>(`/api/albums/${albumId}`);
            return detail.tracks.map((t) => ({
              id: t.id,
              title: t.title,
              track_number: t.track_number,
              disc_number: t.disc_number,
              duration_sec: t.duration_sec,
              album_id: detail.id,
              album_title: detail.title,
              cover_path: detail.cover_path,
              artist_id: detail.artist_id,
              artist_name: detail.artist_name ?? "",
              media_files: t.media_files,
            }));
          } catch {
            return [];
          }
        },
        loadArtistRadio: async () => {
          if (!artistId) return [];
          return fetchAutoPlaylistById(api, "artist-radio", artistId).catch(() => []);
        },
        playNext,
        addToQueue,
      }),
    [albumId, artistId, api, router, playNext, addToQueue, beforeNavigate],
  );

  const items: { label: string; icon: LucideIcon; onPress: () => void; disabled: boolean }[] = [
    { label: "Play album next", icon: SkipForward, onPress: () => void actions.playAlbumNext(), disabled: !albumId },
    { label: "Go to album", icon: Disc3, onPress: actions.goToAlbum, disabled: !albumId },
    { label: "Go to artist", icon: User, onPress: actions.goToArtist, disabled: !artistId },
    { label: "Artist radio", icon: Radio, onPress: () => void actions.artistRadio(), disabled: !artistId },
    { label: "Add album to queue", icon: List, onPress: () => void actions.addAlbumToQueue(), disabled: !albumId },
  ];

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Track actions"
        onPress={() => setOpen(true)}
        hitSlop={8}
        style={styles.trigger}
      >
        <Icon icon={Ellipsis} size={size} color={color} />
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)}>
          <View style={styles.menu}>
            {items.map((it) => (
              <Pressable
                key={it.label}
                accessibilityRole="button"
                accessibilityLabel={it.label}
                accessibilityState={{ disabled: it.disabled }}
                disabled={it.disabled}
                style={({ pressed }) => [styles.item, pressed && !it.disabled && styles.pressed]}
                onPress={() => {
                  setOpen(false);
                  it.onPress();
                }}
              >
                <Icon
                  icon={it.icon}
                  size={18}
                  color={it.disabled ? colors.textFaint : colors.textMuted}
                />
                <Text style={[styles.label, it.disabled && styles.labelDisabled]}>{it.label}</Text>
              </Pressable>
            ))}
          </View>
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  trigger: { minWidth: MIN_TOUCH, minHeight: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
  backdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: "center", alignItems: "center" },
  menu: {
    minWidth: 240,
    backgroundColor: colors.bg3,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    paddingVertical: spacing.xs,
  },
  item: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    minHeight: MIN_TOUCH,
  },
  pressed: { backgroundColor: colors.surfaceHi },
  label: { fontFamily: fonts.uiMedium, fontSize: 15, color: colors.text },
  labelDisabled: { color: colors.textFaint },
});
