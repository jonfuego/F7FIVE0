import { ChevronDown, ChevronUp, Repeat, Shuffle, Trash2, Volume2, X } from "lucide-react-native";
import React from "react";
import { FlatList, Modal, Pressable, StyleSheet, Text, View } from "react-native";

import { usePlayer } from "@/player/PlayerProvider";
import { colors, fonts, MIN_TOUCH, radius, spacing } from "@/state/theme";
import { Icon } from "./Icon";

export interface QueuePanelProps {
  visible: boolean;
  onClose: () => void;
}

/** Up Next queue, ported from frontend/components/QueuePanel.tsx: jump-to,
 * remove, clear, reorder (TrackPlayer.move via the up/down handles), shuffle,
 * and repeat off/all/one. Reachable from now-playing. */
export function QueuePanel({ visible, onClose }: QueuePanelProps): React.ReactElement {
  const player = usePlayer();
  // queueVersion is read so the list re-renders after in-place mutations.
  const { activeIndex, metas } = player.getQueueItems();
  void player.queueVersion;

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.header}>
            <Text style={styles.title}>Up Next</Text>
            <View style={styles.headerActions}>
              <Pressable
                onPress={() => void player.toggleShuffle()}
                accessibilityRole="button"
                accessibilityLabel="Shuffle queue"
                style={styles.headerBtn}
              >
                <Icon icon={Shuffle} size={20} color={player.shuffleOn ? colors.accent : colors.textMuted} />
              </Pressable>
              <Pressable
                onPress={() => void player.cycleRepeat()}
                accessibilityRole="button"
                accessibilityLabel={`Repeat ${player.repeatMode}`}
                style={styles.headerBtn}
              >
                <Icon
                  icon={Repeat}
                  size={20}
                  color={player.repeatMode !== "off" ? colors.accent : colors.textMuted}
                />
                {player.repeatMode === "one" ? <Text style={styles.one}>1</Text> : null}
              </Pressable>
              <Pressable
                onPress={() => void player.clearQueue()}
                accessibilityRole="button"
                accessibilityLabel="Clear queue"
                style={styles.headerBtn}
              >
                <Icon icon={Trash2} size={20} color={colors.textMuted} />
              </Pressable>
              <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close queue" style={styles.headerBtn}>
                <Icon icon={ChevronDown} size={22} color={colors.text} />
              </Pressable>
            </View>
          </View>

          <FlatList
            data={metas}
            keyExtractor={(m, i) => `${m.mediaFileId}-${i}`}
            extraData={player.queueVersion}
            renderItem={({ item, index }) => {
              const isActive = index === activeIndex;
              return (
                <View style={[styles.row, isActive && styles.active]}>
                  <Pressable
                    style={styles.rowMain}
                    onPress={() => void player.jumpTo(index)}
                    accessibilityRole="button"
                    accessibilityLabel={`Play ${item.title}`}
                  >
                    {isActive ? (
                      <Icon icon={Volume2} size={16} color={colors.accent} style={styles.playing} />
                    ) : null}
                    <View style={styles.rowText}>
                      <Text style={styles.rowTitle} numberOfLines={1}>
                        {item.title}
                      </Text>
                      {item.artist ? (
                        <Text style={styles.rowSub} numberOfLines={1}>
                          {item.artist}
                        </Text>
                      ) : null}
                    </View>
                  </Pressable>
                  <Pressable
                    disabled={index <= 0}
                    onPress={() => void player.moveTrack(index, index - 1)}
                    accessibilityLabel="Move up"
                    style={styles.iconBtn}
                  >
                    <Icon icon={ChevronUp} size={18} color={index <= 0 ? colors.textFaint : colors.textMuted} />
                  </Pressable>
                  <Pressable
                    disabled={index >= metas.length - 1}
                    onPress={() => void player.moveTrack(index, index + 1)}
                    accessibilityLabel="Move down"
                    style={styles.iconBtn}
                  >
                    <Icon
                      icon={ChevronDown}
                      size={18}
                      color={index >= metas.length - 1 ? colors.textFaint : colors.textMuted}
                    />
                  </Pressable>
                  <Pressable
                    disabled={isActive}
                    onPress={() => void player.removeAt(index)}
                    accessibilityLabel="Remove from queue"
                    style={styles.iconBtn}
                  >
                    <Icon icon={X} size={18} color={isActive ? colors.textFaint : colors.danger} />
                  </Pressable>
                </View>
              );
            }}
            ListEmptyComponent={<Text style={styles.empty}>The queue is empty.</Text>}
          />
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: "flex-end" },
  sheet: {
    maxHeight: "80%",
    backgroundColor: colors.bg2,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingBottom: spacing.xl,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
  },
  title: { fontFamily: fonts.display, fontSize: 24, letterSpacing: 1, color: colors.text },
  headerActions: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  headerBtn: { minWidth: MIN_TOUCH, minHeight: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
  one: { position: "absolute", top: 6, right: 6, fontFamily: fonts.mono, fontSize: 9, color: colors.accent },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xs,
  },
  active: { backgroundColor: "rgba(236,229,216,0.08)" },
  rowMain: { flex: 1, flexDirection: "row", alignItems: "center", minHeight: MIN_TOUCH },
  playing: { marginRight: spacing.sm },
  rowText: { flex: 1 },
  rowTitle: { fontFamily: fonts.uiMedium, fontSize: 15, color: colors.text },
  rowSub: { fontFamily: fonts.mono, fontSize: 11, color: colors.textFaint },
  iconBtn: { width: 34, height: MIN_TOUCH, alignItems: "center", justifyContent: "center" },
  empty: { fontFamily: fonts.ui, color: colors.textMuted, textAlign: "center", padding: spacing.xl },
});
