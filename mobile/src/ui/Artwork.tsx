import { Ionicons } from "@expo/vector-icons";
import React, { useState } from "react";
import { Image, StyleSheet, View } from "react-native";

import { resolveArtUri } from "@/api/media";
import { useApi } from "@/state/auth";
import { colors, radius } from "@/state/theme";

interface ArtworkProps {
  path?: string | null;
  size: number;
  rounded?: boolean;
  /** Header for authenticated /api/art loads. */
  headers?: Record<string, string>;
}

/** Poster / cover image with a branded placeholder (never a blank box). */
export function Artwork({ path, size, rounded, headers }: ArtworkProps): React.ReactElement {
  const api = useApi();
  const uri = resolveArtUri(path);
  const [failedUri, setFailedUri] = useState<string | null>(null);
  // Server art (/api/art/...) requires the bearer token; remote (TMDB etc.)
  // URLs are public and must not receive it.
  const isServerArt = !!path && !/^https?:\/\//i.test(path);
  const imageHeaders = headers ?? (isServerArt ? api.authHeaders() : undefined);
  const style = {
    width: size,
    height: size,
    borderRadius: rounded ? radius.md : radius.sm,
    backgroundColor: colors.surfaceAlt,
  };
  if (!uri || failedUri === uri) {
    return (
      <View style={[styles.placeholder, style]}>
        <Ionicons name="musical-notes" size={Math.round(size * 0.36)} color={colors.textFaint} />
      </View>
    );
  }
  return (
    <Image
      source={{ uri, headers: imageHeaders }}
      onError={() => setFailedUri(uri)}
      style={style}
      resizeMode="cover"
      accessibilityIgnoresInvertColors
    />
  );
}

const styles = StyleSheet.create({
  placeholder: { alignItems: "center", justifyContent: "center" },
});
