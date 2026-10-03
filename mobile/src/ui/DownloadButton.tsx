import { CheckCircle, CloudOff, Download, XCircle } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text } from "react-native";

import { useDownloads, type EnqueueOptions } from "@/download/DownloadProvider";
import { colors, MIN_TOUCH, radius, spacing } from "@/state/theme";
import { Icon } from "./Icon";

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
    ? CloudOff
    : status === "done"
      ? CheckCircle
      : status === "downloading" || status === "queued"
        ? XCircle
        : Download;

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
      <Icon icon={icon} size={compact ? 22 : 18} color={status === "done" ? colors.accent : colors.text} />
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
  focused: { borderWidth: 2, borderColor: colors.accent },
  pressed: { opacity: 0.7 },
});
