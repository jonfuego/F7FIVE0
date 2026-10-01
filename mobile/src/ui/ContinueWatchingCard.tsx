import { Ionicons } from "@expo/vector-icons";
import React, { useState } from "react";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";

import { resolveArtUri } from "@/api/media";
import { useApi } from "@/state/auth";
import { colors, fonts, radius, spacing } from "@/state/theme";

interface ContinueWatchingCardProps {
  title: string;
  subtitle?: string | null;
  artPath?: string | null;
  positionSec?: number | null;
  durationSec?: number | null;
  width: number;
  onPress: () => void;
  /** TV: take initial D-pad focus (first card on the browse screen). */
  hasTVPreferredFocus?: boolean;
}

function remaining(positionSec?: number | null, durationSec?: number | null): string | null {
  if (!durationSec || durationSec <= 0 || positionSec == null) return null;
  const left = Math.max(0, durationSec - positionSec);
  const m = Math.round(left / 60);
  if (m <= 0) return "Almost done";
  if (m < 60) return `${m} min left`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m left`;
}

/** Wide 16:9 resume tile for the Home Continue Watching rail, ported from
 * frontend/components/ContinueWatchingCard.tsx: a play overlay, a
 * remaining-time badge, and a thin progress bar showing how far in you are. */
export function ContinueWatchingCard({
  title,
  subtitle,
  artPath,
  positionSec,
  durationSec,
  width,
  onPress,
  hasTVPreferredFocus,
}: ContinueWatchingCardProps): React.ReactElement {
  const api = useApi();
  const uri = resolveArtUri(artPath);
  const [failed, setFailed] = useState(false);
  const height = Math.round((width * 9) / 16);
  const isServerArt = !!artPath && !/^https?:\/\//i.test(artPath);
  const headers = isServerArt ? api.authHeaders() : undefined;
  const pct = durationSec && durationSec > 0 && positionSec != null
    ? Math.max(0, Math.min(1, positionSec / durationSec))
    : 0;
  const left = remaining(positionSec, durationSec);
  const frame = { width, height };

  return (
    <Pressable
      onPress={onPress}
      hasTVPreferredFocus={hasTVPreferredFocus}
      accessibilityRole="button"
      accessibilityLabel={left ? `${title}, ${left}` : title}
      style={({ pressed, focused }) => [{ width }, focused && styles.focused, pressed && styles.pressed]}
    >
      {({ focused }) => (
      <>
      <View style={[styles.frame, frame, focused && styles.frameFocused]}>
        {uri && !failed ? (
          <Image
            source={{ uri, headers }}
            onError={() => setFailed(true)}
            style={[styles.art, frame]}
            resizeMode="cover"
            accessibilityIgnoresInvertColors
          />
        ) : (
          <View style={[styles.placeholder, frame]}>
            <Ionicons name="play-circle-outline" size={44} color={colors.textFaint} />
          </View>
        )}
        <View style={styles.overlay}>
          <Ionicons name="play" size={22} color={colors.background} />
        </View>
        {left ? <Text style={styles.badge}>{left}</Text> : null}
        {pct > 0 ? (
          <View style={styles.progressTrack}>
            <View style={[styles.progressFill, { width: `${pct * 100}%` }]} />
          </View>
        ) : null}
      </View>
      <Text style={styles.title} numberOfLines={1}>
        {title}
      </Text>
      {subtitle ? (
        <Text style={styles.subtitle} numberOfLines={1}>
          {subtitle}
        </Text>
      ) : null}
      </>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  frame: { borderRadius: radius.sm, overflow: "hidden", backgroundColor: colors.surfaceAlt },
  art: { position: "absolute", left: 0, top: 0 },
  placeholder: { alignItems: "center", justifyContent: "center" },
  focused: { transform: [{ scale: 1.04 }] },
  frameFocused: { borderWidth: 2, borderColor: colors.bulb },
  pressed: { opacity: 0.8 },
  overlay: {
    position: "absolute",
    alignSelf: "center",
    top: "50%",
    marginTop: -20,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.bulb,
    alignItems: "center",
    justifyContent: "center",
  },
  badge: {
    position: "absolute",
    left: 6,
    bottom: 6,
    fontFamily: fonts.mono,
    fontSize: 11,
    color: colors.text,
    textShadowColor: "rgba(0,0,0,0.9)",
    textShadowRadius: 4,
  },
  progressTrack: { position: "absolute", left: 0, right: 0, bottom: 0, height: 3, backgroundColor: "rgba(0,0,0,0.5)" },
  progressFill: { height: 3, backgroundColor: colors.bulb },
  title: { fontFamily: fonts.uiSemiBold, fontSize: 14, color: colors.text, marginTop: spacing.xs },
  subtitle: { fontFamily: fonts.mono, fontSize: 11, color: colors.textFaint },
});
