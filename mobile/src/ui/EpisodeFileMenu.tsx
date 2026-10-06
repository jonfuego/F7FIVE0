import { Info, MoreVertical } from "lucide-react-native";
import React, { useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import type { MediaFile } from "@/api/types";
import { colors, fonts, MIN_TOUCH, radius, spacing } from "@/state/theme";
import { fileInfoRows } from "./fileInfo";
import { Icon } from "./Icon";
import { IconButton } from "./IconButton";

/** 3-dot menu on an episode row. Its "File info" action shows that
 * episode's own file (codec, bitrate, container, resolution, audio, size,
 * path). Used by the show screen and the season screen. */
export function EpisodeFileMenu({ file, label }: { file: MediaFile; label: string }): React.ReactElement {
  const [view, setView] = useState<"closed" | "menu" | "info">("closed");
  const close = () => setView("closed");

  return (
    <>
      <IconButton
        icon={MoreVertical}
        size={20}
        color={colors.textMuted}
        accessibilityLabel={`${label} actions`}
        onPress={() => setView("menu")}
      />
      <Modal visible={view !== "closed"} transparent animationType="fade" onRequestClose={close}>
        <Pressable style={styles.backdrop} onPress={close}>
          {view === "menu" ? (
            <View style={styles.menu}>
              <Text style={styles.title} numberOfLines={1}>
                {label}
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="File info"
                style={({ pressed }) => [styles.item, pressed && styles.pressed]}
                onPress={() => setView("info")}
              >
                <Icon icon={Info} size={18} color={colors.textMuted} />
                <Text style={styles.itemLabel}>File info</Text>
              </Pressable>
            </View>
          ) : (
            <Pressable style={styles.sheet} onPress={() => undefined} accessibilityLabel={`File info: ${label}`}>
              <Text style={styles.sheetTitle}>File info</Text>
              <Text style={styles.title} numberOfLines={2}>
                {label}
              </Text>
              <ScrollView>
                {fileInfoRows(file).map((r) => (
                  <View key={r.label} style={styles.row}>
                    <Text style={styles.rowLabel}>{r.label}</Text>
                    <Text style={[styles.rowValue, r.label === "File path" && styles.path]} selectable>
                      {r.value}
                    </Text>
                  </View>
                ))}
              </ScrollView>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Close"
                onPress={close}
                style={({ pressed }) => [styles.closeBtn, pressed && styles.pressed]}
              >
                <Text style={styles.itemLabel}>Close</Text>
              </Pressable>
            </Pressable>
          )}
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: "center", alignItems: "center", padding: spacing.lg },
  menu: {
    minWidth: 220,
    backgroundColor: colors.bg3,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    paddingVertical: spacing.xs,
  },
  sheet: {
    width: "100%",
    maxWidth: 480,
    maxHeight: "85%",
    backgroundColor: colors.bg3,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  sheetTitle: { fontFamily: fonts.uiMedium, fontSize: 13, fontWeight: "700", color: colors.hiveText, textTransform: "uppercase", letterSpacing: 1.5 },
  title: { fontFamily: fonts.mono, fontSize: 11, color: colors.textFaint, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  item: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.lg, minHeight: MIN_TOUCH },
  pressed: { backgroundColor: colors.surfaceHi },
  itemLabel: { fontFamily: fonts.uiMedium, fontSize: 15, color: colors.text },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
  },
  rowLabel: { fontSize: 13, color: colors.textFaint },
  rowValue: { fontSize: 13, color: colors.text, flexShrink: 1, textAlign: "right" },
  path: { fontSize: 11 },
  closeBtn: { minHeight: MIN_TOUCH, alignItems: "center", justifyContent: "center", borderRadius: radius.md, marginTop: spacing.sm },
});
