import { Download, List, Play, Radio, Shuffle, SkipForward, type LucideIcon } from "lucide-react-native";
import React from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fonts, MIN_TOUCH, radius, spacing } from "@/state/theme";
import { Icon } from "./Icon";

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
  icon: LucideIcon;
  /** play / skip glyphs render filled. */
  fill?: boolean;
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
    ...(onPlayNow ? [{ label: "Play now", icon: Play, fill: true, onPress: onPlayNow }] : []),
    { label: "Play next", icon: SkipForward, fill: true, onPress: onPlayNext },
    { label: "Add to queue", icon: List, onPress: onAddToQueue },
    { label: "Shuffle", icon: Shuffle, onPress: onShuffle },
    ...(onTrackRadio ? [{ label: "Track radio", icon: Radio, onPress: onTrackRadio }] : []),
    ...(onDownload ? [{ label: "Download", icon: Download, onPress: onDownload }] : []),
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
              <Icon icon={it.icon} size={18} color={colors.textMuted} fill={it.fill} />
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
