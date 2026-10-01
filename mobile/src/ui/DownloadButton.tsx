import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Pressable, StyleSheet, Text } from "react-native";

import { useDownloads, type EnqueueOptions } from "@/download/DownloadProvider";
import { colors, MIN_TOUCH, radius, spacing } from "@/state/theme";

interface DownloadButtonProps {
  mediaFileId: string;
  title: string;
  opts: EnqueueOptions;
  /** Icon-only (episode rows) instead of a labeled pill (movie detail). */
  compact?: boolean;
}

/** Download / status control for one media file (spec J). Shows Download,
 * progress, Downloaded, or "Not available offline" when the server can't offer
 * the file (video that can't direct-play with download transcodes off). */
export function DownloadButton({ mediaFileId, title, opts, compact }: DownloadButtonProps): React.ReactElement {
  const { state, enqueue, cancel } = useDownloads();
  const item = state.items.find((i) => i.id === mediaFileId);
  const status = item?.status;
  const unavailable = status === "error" && item?.error === "not_available_offline";

  const label = unavailable
    ? "Not available offline"
    : status === "done"
      ? "Downloaded"
      : status === "downloading"
        ? `Downloading ${Math.round((item?.progress ?? 0) * 100)}%`
        : status === "queued"
          ? "Queued"
          : status === "error"
            ? "Retry download"
            : "Download";
  const icon = unavailable
    ? "cloud-offline-outline"
    : status === "done"
      ? "checkmark-circle"
      : status === "downloading" || status === "queued"
        ? "close-circle-outline"
        : "download-outline";

  const onPress = () => {
    if (status === "downloading" || status === "queued") cancel(mediaFileId);
    else if (status !== "done" && !unavailable) enqueue(mediaFileId, title, opts);
  };

  return (
    <Pressable
      onPress={onPress}
      disabled={status === "done" || unavailable}
      accessibilityRole="button"
      accessibilityLabel={`${label}: ${title}`}
      style={({ pressed, focused }) => [
        compact ? styles.icon : styles.pill,
        focused && styles.focused,
        pressed && styles.pressed,
      ]}
    >
      <Ionicons name={icon} size={compact ? 22 : 18} color={status === "done" ? colors.bulb : colors.text} />
      {compact ? null : <Text style={styles.txt}>{label}</Text>}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.line,
  },
  icon: { width: MIN_TOUCH, height: MIN_TOUCH, alignItems: "center", justifyContent: "center", borderRadius: radius.pill },
  txt: { fontSize: 16, fontWeight: "600", color: colors.text },
  focused: { borderWidth: 2, borderColor: colors.bulb },
  pressed: { opacity: 0.7 },
});
