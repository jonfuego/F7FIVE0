import { Ellipsis, List, Play, SkipForward } from "lucide-react-native";
import React, { useMemo, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";

import type { SongRow } from "@/api/types";
import { colors, fonts, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { Artwork } from "./Artwork";
import { Icon } from "./Icon";
import { createTrackRowMenuActions, type TrackRowMenuDeps } from "./trackRowMenuActions";

interface TrackRowProps {
  title: string;
  subtitle?: string | null;
  artPath?: string | null;
  active?: boolean;
  onPress: () => void;
  onLongPress?: () => void;
  // When provided, the row shows a 3-dot (Ellipsis) action that opens a menu
  // with Play now / Play next / Add to queue, acting on this track. Omit it to
  // render a plain row (e.g. the queue panel, where rows aren't track menus).
  menu?: {
    song: SongRow;
    playSongs: TrackRowMenuDeps["playSongs"];
    playNext: TrackRowMenuDeps["playNext"];
    addToQueue: TrackRowMenuDeps["addToQueue"];
  };
}

export function TrackRow({
  title,
  subtitle,
  artPath,
  active,
  onPress,
  onLongPress,
  menu,
}: TrackRowProps): React.ReactElement {
  const [menuOpen, setMenuOpen] = useState(false);
  const actions = useMemo(
    () => (menu ? createTrackRowMenuActions(menu) : null),
    [menu],
  );

  return (
    <View style={styles.wrap}>
      <Pressable
        onPress={onPress}
        onLongPress={onLongPress}
        accessibilityRole="button"
        accessibilityLabel={subtitle ? `${title}, ${subtitle}` : title}
        style={({ pressed, focused }) => [
          styles.row,
          active && styles.active,
          focused && styles.focused,
          pressed && styles.pressed,
        ]}
      >
        <Artwork path={artPath} size={48} rounded />
        <View style={styles.meta}>
          <Text style={[styles.title, active && styles.activeText]} numberOfLines={1}>
            {title}
          </Text>
          {subtitle ? (
            <Text style={styles.subtitle} numberOfLines={1}>
              {subtitle}
            </Text>
          ) : null}
        </View>
      </Pressable>
      {menu ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${title} actions`}
          onPress={() => setMenuOpen(true)}
          style={styles.kebab}
        >
          <Icon icon={Ellipsis} size={20} color={colors.textMuted} />
        </Pressable>
      ) : null}
      {menu && actions ? (
        <Modal
          visible={menuOpen}
          transparent
          animationType="fade"
          onRequestClose={() => setMenuOpen(false)}
        >
          <Pressable style={styles.backdrop} onPress={() => setMenuOpen(false)}>
            <View style={styles.menu}>
              <Text style={styles.menuTitle} numberOfLines={1}>
                {title}
              </Text>
              <MenuRow
                label="Play now"
                icon={Play}
                fill
                onPress={() => {
                  void actions.playNow();
                  setMenuOpen(false);
                }}
              />
              <MenuRow
                label="Play next"
                icon={SkipForward}
                fill
                onPress={() => {
                  void actions.playNext();
                  setMenuOpen(false);
                }}
              />
              <MenuRow
                label="Add to queue"
                icon={List}
                onPress={() => {
                  void actions.addToQueue();
                  setMenuOpen(false);
                }}
              />
            </View>
          </Pressable>
        </Modal>
      ) : null}
    </View>
  );
}

function MenuRow({
  label,
  icon,
  fill,
  onPress,
}: {
  label: string;
  icon: React.ComponentProps<typeof Icon>["icon"];
  fill?: boolean;
  onPress: () => void;
}): React.ReactElement {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => [styles.item, pressed && styles.itemPressed]}
      onPress={onPress}
    >
      <Icon icon={icon} size={18} color={colors.textMuted} fill={fill} />
      <Text style={styles.itemLabel}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: "row", alignItems: "center" },
  row: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    minHeight: MIN_TOUCH + 12,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
  },
  active: { backgroundColor: colors.surfaceAlt },
  pressed: { opacity: 0.7 },
  focused: { borderWidth: 2, borderColor: colors.accent },
  meta: { flex: 1 },
  title: { ...typography.body },
  activeText: { color: colors.accent, fontWeight: "700" },
  subtitle: { ...typography.caption },
  kebab: { minWidth: MIN_TOUCH, minHeight: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
  backdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: "center", alignItems: "center" },
  menu: {
    minWidth: 220,
    backgroundColor: colors.bg3,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    paddingVertical: spacing.xs,
  },
  menuTitle: {
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
  itemPressed: { backgroundColor: colors.surfaceHi },
  itemLabel: { fontFamily: fonts.uiMedium, fontSize: 15, color: colors.text },
});
