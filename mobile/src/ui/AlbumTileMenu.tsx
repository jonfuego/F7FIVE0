import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fonts, MIN_TOUCH, radius, spacing } from "@/state/theme";

export interface AlbumTileMenuProps {
  visible: boolean;
  title?: string;
  onPlayNow?: () => void;
  onPlayNext: () => void;
  onAddToQueue: () => void;
  onShuffle: () => void;
  /** Optional "Track radio" action for single-song menus (crit 48). */
  onTrackRadio?: () => void;
  /** Optional "Download" action (crit 42). */
  onDownload?: () => void;
  onClose: () => void;
}

interface Item {
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  onPress?: () => void;
}

/** Context menu for album tiles, album detail and song rows, ported from
 * frontend/components/AlbumTileMenu.tsx: Play now / Play next / Add to queue /
 * Shuffle. Actions are wired to the track-player queue by the caller. */
export function AlbumTileMenu({
  visible,
  title,
  onPlayNow,
  onPlayNext,
  onAddToQueue,
  onShuffle,
  onTrackRadio,
  onDownload,
  onClose,
}: AlbumTileMenuProps): React.ReactElement {
  const items: Item[] = [
    ...(onPlayNow ? [{ label: "Play now", icon: "play" as const, onPress: onPlayNow }] : []),
    { label: "Play next", icon: "play-forward", onPress: onPlayNext },
    { label: "Add to queue", icon: "list", onPress: onAddToQueue },
    { label: "Shuffle", icon: "shuffle", onPress: onShuffle },
    ...(onTrackRadio ? [{ label: "Track radio", icon: "radio" as const, onPress: onTrackRadio }] : []),
    ...(onDownload ? [{ label: "Download", icon: "download" as const, onPress: onDownload }] : []),
  ];

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose}>
        <View style={styles.menu}>
          {title ? (
            <Text style={styles.title} numberOfLines={1}>
              {title}
            </Text>
          ) : null}
          {items.map((it) => (
            <Pressable
              key={it.label}
              accessibilityRole="button"
              accessibilityLabel={it.label}
              style={({ pressed }) => [styles.item, pressed && styles.pressed]}
              onPress={() => {
                it.onPress?.();
                onClose();
              }}
            >
              <Ionicons name={it.icon} size={18} color={colors.textMuted} />
              <Text style={styles.label}>{it.label}</Text>
            </Pressable>
          ))}
        </View>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: "center", alignItems: "center" },
  menu: {
    minWidth: 220,
    backgroundColor: colors.bg3,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    paddingVertical: spacing.xs,
  },
  title: {
    fontFamily: fonts.mono,
    fontSize: 11,
    color: colors.textFaint,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
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
});
