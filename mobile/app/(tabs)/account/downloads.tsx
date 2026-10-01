import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React from "react";
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { useDownloads } from "@/download/DownloadProvider";
import { downloadToSong } from "@/download/entries";
import { doneItems, type DownloadItem } from "@/download/queue";
import { usePlayer } from "@/player/PlayerProvider";
import { formatBytes, limitFraction } from "@/download/format";
import { useSetting, SETTINGS } from "@/state/settings";
import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { IconButton } from "@/ui/IconButton";
import { Screen } from "@/ui/Screen";

const LIMIT_OPTIONS = [0, 1024, 5120, 10240, 20480]; // MB (0 = unlimited)

/** Downloads screen (crit 42/43): per-item size + status, total storage,
 * delete, cancel, a storage-limit setting (SETTINGS.storageLimitMb), and play:
 * tap a finished song to play every downloaded song from local files, or a
 * finished movie/episode to watch it from disk. With no network the app opens
 * here. Nothing here stores a URL. */
export default function DownloadsScreen(): React.ReactElement {
  const router = useRouter();
  const { playSongs } = usePlayer();
  const { state, usedBytes, online, cancel, remove, setLimitMb } = useDownloads();

  const play = (it: DownloadItem) => {
    const kind = it.kind ?? "track";
    if (kind === "track") {
      const tracks = doneItems(state, "track");
      const idx = Math.max(0, tracks.findIndex((t) => t.id === it.id));
      void playSongs(tracks.map(downloadToSong), idx);
    } else {
      router.push(`/watch/${it.id}`);
    }
  };
  const [limitMb] = useSetting<number>(SETTINGS.storageLimitMb, 0);
  const frac = limitFraction(usedBytes, limitMb * 1024 * 1024);

  const confirmRemove = (id: string, title: string) => {
    Alert.alert("Delete download", `Remove "${title}" from this device?`, [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: () => void remove(id) },
    ]);
  };

  return (
    <Screen title="Downloads">
      <ScrollView>
        {!online ? (
          <View style={styles.offlineBanner} accessibilityLabel="Offline mode">
            <Ionicons name="cloud-offline" size={18} color={colors.background} />
            <Text style={styles.offlineText}>Offline - playing from downloads</Text>
          </View>
        ) : null}

        <Text style={styles.section}>Storage</Text>
        <Text style={styles.storageLine}>
          {formatBytes(usedBytes)} used{limitMb > 0 ? ` of ${formatBytes(limitMb * 1024 * 1024)}` : " (no limit)"}
        </Text>
        {frac != null ? (
          <View style={styles.bar} accessibilityLabel={`Storage ${Math.round(frac * 100)} percent full`}>
            <View style={[styles.barFill, { width: `${Math.round(frac * 100)}%` }]} />
          </View>
        ) : null}

        <Text style={styles.section}>Storage limit</Text>
        <View style={styles.chipRow}>
          {LIMIT_OPTIONS.map((mb) => {
            const on = limitMb === mb;
            return (
              <Pressable
                key={mb}
                accessibilityRole="button"
                accessibilityLabel={mb === 0 ? "No storage limit" : `Limit ${mb / 1024} gigabytes`}
                onPress={() => setLimitMb(mb)}
                style={[styles.chip, on && styles.chipOn]}
              >
                <Text style={[styles.chipTxt, on && styles.chipTxtOn]}>
                  {mb === 0 ? "None" : `${mb / 1024} GB`}
                </Text>
              </Pressable>
            );
          })}
        </View>

        <Text style={styles.section}>Downloads</Text>
        {state.items.length === 0 ? (
          <Text style={styles.empty}>No downloads yet. Long-press a song or use the download action.</Text>
        ) : (
          state.items.map((it) => (
            <View key={it.id} style={styles.row}>
              <Pressable
                style={styles.rowMeta}
                disabled={it.status !== "done"}
                onPress={() => play(it)}
                accessibilityRole="button"
                accessibilityLabel={it.status === "done" ? `Play download ${it.title}` : `${it.title} ${it.status}`}
              >
                <Text style={styles.rowTitle} numberOfLines={1}>
                  {it.title}
                </Text>
                {it.meta?.artist || it.meta?.group ? (
                  <Text style={styles.rowSub} numberOfLines={1}>
                    {[it.meta?.artist, it.meta?.group ?? it.meta?.album].filter(Boolean).join(" · ")}
                  </Text>
                ) : null}
                <Text style={styles.rowSub}>
                  {it.status === "downloading"
                    ? `${Math.round(it.progress * 100)}% · ${formatBytes(it.bytes)}`
                    : it.status === "done"
                      ? formatBytes(it.bytes)
                      : it.status === "error"
                        ? it.error === "not_available_offline"
                          ? "Not available offline"
                          : `Failed: ${it.error ?? "error"}`
                        : it.status}
                </Text>
                {it.status === "downloading" ? (
                  <View style={styles.rowBar}>
                    <View style={[styles.rowBarFill, { width: `${Math.round(it.progress * 100)}%` }]} />
                  </View>
                ) : null}
              </Pressable>
              {it.status === "downloading" || it.status === "queued" ? (
                <IconButton
                  name="close-circle"
                  onPress={() => cancel(it.id)}
                  accessibilityLabel={`Cancel download of ${it.title}`}
                  color={colors.danger}
                />
              ) : (
                <IconButton
                  name="trash"
                  onPress={() => confirmRemove(it.id, it.title)}
                  accessibilityLabel={`Delete download of ${it.title}`}
                  color={colors.danger}
                />
              )}
            </View>
          ))
        )}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  offlineBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.bulb,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  offlineText: { color: colors.background, fontWeight: "700" },
  section: { ...typography.label, marginTop: spacing.lg, marginBottom: spacing.sm },
  storageLine: { ...typography.body },
  bar: { height: 8, borderRadius: radius.pill, backgroundColor: colors.surfaceAlt, marginTop: spacing.sm },
  barFill: { height: 8, borderRadius: radius.pill, backgroundColor: colors.accent },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: {
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.line,
    justifyContent: "center",
  },
  chipOn: { backgroundColor: colors.bulb, borderColor: colors.bulb },
  chipTxt: { color: colors.text, fontWeight: "600" },
  chipTxtOn: { color: colors.background },
  empty: { ...typography.body, color: colors.textMuted },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: MIN_TOUCH + 12, paddingVertical: spacing.sm },
  rowMeta: { flex: 1 },
  rowTitle: { ...typography.body },
  rowSub: { ...typography.caption },
  rowBar: { height: 4, borderRadius: radius.pill, backgroundColor: colors.surfaceAlt, marginTop: spacing.xs },
  rowBarFill: { height: 4, borderRadius: radius.pill, backgroundColor: colors.accent },
});
