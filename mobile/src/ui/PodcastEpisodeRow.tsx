import { Check, CheckCheck, HardDriveDownload, Play } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { PodcastEpisodeRow as EpisodeRow, PodcastShowRef } from "@/api/types";
import { episodeEntry } from "@/download/podcastEntries";
import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { DownloadButton } from "./DownloadButton";
import { Icon } from "./Icon";
import { episodeStateLabel, progressFraction } from "./podcastState";

interface Props {
  ep: EpisodeRow;
  show: PodcastShowRef;
  subscribed: boolean;
  onPlay: () => void;
  onTogglePlayed: () => void;
  /** Ask the server to download the episode into its podcasts library. */
  onServerDownload?: () => void;
}

function dateText(iso?: string | null): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  return new Date(t).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function durationText(sec?: number | null): string {
  if (!sec || sec <= 0) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/** One episode on a show screen: title, date, length and the person's own state,
 * Play or Resume, the device download, mark played, and (for a follower) "save
 * to the server". A video episode is listed but not played. The description is
 * plain text and is not shown here. */
export function PodcastEpisodeRow({ ep, show, subscribed, onPlay, onTogglePlayed, onServerDownload }: Props): React.ReactElement {
  const played = ep.state.kind === "played";
  const fraction = progressFraction(ep.state, ep.duration_sec);
  const meta = [dateText(ep.published_at), durationText(ep.duration_sec)].filter(Boolean).join(" · ");
  const entry = episodeEntry(ep, show);
  return (
    <View style={styles.row}>
      <Text style={[styles.title, played && styles.dim]} numberOfLines={2}>
        {ep.title}
      </Text>
      {meta ? <Text style={styles.meta}>{meta}</Text> : null}
      <View style={styles.stateLine}>
        <Text style={[styles.state, ep.state.kind === "new" && styles.stateNew]}>
          {episodeStateLabel(ep.state, ep.duration_sec)}
        </Text>
        {ep.has_file ? <Text style={styles.badge}>on server</Text> : null}
        {ep.is_video ? <Text style={styles.meta}>Video podcasts aren&apos;t supported yet</Text> : null}
      </View>
      {ep.state.kind === "in_progress" ? (
        <View style={styles.bar}>
          <View style={[styles.barFill, { width: `${Math.round(fraction * 100)}%` }]} />
        </View>
      ) : null}
      <View style={styles.actions}>
        <Pressable
          onPress={onPlay}
          disabled={ep.is_video}
          accessibilityRole="button"
          accessibilityLabel={`${ep.state.kind === "in_progress" ? "Resume" : "Play"} ${ep.title}`}
          style={({ pressed, focused }) => [styles.play, ep.is_video && styles.off, focused && styles.focused, pressed && styles.pressed]}
        >
          <Icon icon={Play} size={16} color={colors.background} fill />
          <Text style={styles.playTxt}>{ep.state.kind === "in_progress" ? "Resume" : "Play"}</Text>
        </Pressable>
        {ep.is_video ? null : <DownloadButton mediaFileId={entry.mediaFileId} title={entry.title} opts={entry.opts} compact />}
        <Pressable
          onPress={onTogglePlayed}
          accessibilityRole="button"
          accessibilityLabel={played ? `Mark ${ep.title} unplayed` : `Mark ${ep.title} played`}
          style={({ pressed }) => [styles.icon, pressed && styles.pressed]}
        >
          <Icon icon={played ? CheckCheck : Check} size={22} color={played ? colors.accent : colors.text} />
        </Pressable>
        {subscribed && !ep.has_file && !ep.is_video && onServerDownload ? (
          <Pressable
            onPress={onServerDownload}
            accessibilityRole="button"
            accessibilityLabel={`Save ${ep.title} to the server`}
            style={({ pressed }) => [styles.icon, pressed && styles.pressed]}
          >
            <Icon icon={HardDriveDownload} size={22} color={colors.text} />
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
    gap: spacing.xs,
  },
  title: { ...typography.body, color: colors.text, fontWeight: "600" },
  dim: { color: colors.textMuted },
  meta: { ...typography.caption },
  stateLine: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" },
  state: { ...typography.caption, color: colors.textMuted },
  stateNew: { color: colors.accent },
  badge: {
    ...typography.caption,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
  },
  bar: { height: 3, borderRadius: radius.pill, backgroundColor: colors.surfaceAlt, marginTop: 2 },
  barFill: { height: 3, borderRadius: radius.pill, backgroundColor: colors.accent },
  actions: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.xs },
  play: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
  },
  playTxt: { color: colors.background, fontWeight: "700" },
  icon: { width: MIN_TOUCH, height: MIN_TOUCH, alignItems: "center", justifyContent: "center", borderRadius: radius.pill },
  off: { opacity: 0.4 },
  focused: { borderWidth: 2, borderColor: colors.text },
  pressed: { opacity: 0.7 },
});
