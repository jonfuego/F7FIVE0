import { LinearGradient } from "expo-linear-gradient";
import React, { useState } from "react";
import { Image, StyleSheet, View } from "react-native";

import { resolveArtUri } from "@/api/media";
import { useApi } from "@/state/auth";
import { colors } from "@/state/theme";

interface BackdropProps {
  path?: string | null;
  /** Rendered height of the hero. */
  height: number;
  children?: React.ReactNode;
}

/** Full-bleed backdrop hero for movie / show / artist detail, ported from
 * frontend/components/Backdrop.tsx. Fades to the app background at the bottom so
 * title + actions sit legibly over the key art. */
export function Backdrop({ path, height, children }: BackdropProps): React.ReactElement {
  const api = useApi();
  const uri = resolveArtUri(path);
  const [failed, setFailed] = useState(false);
  const isServerArt = !!path && !/^https?:\/\//i.test(path);
  const headers = isServerArt ? api.authHeaders() : undefined;

  return (
    <View style={[styles.wrap, { height }]}>
      {uri && !failed ? (
        <Image
          source={{ uri, headers }}
          onError={() => setFailed(true)}
          style={[styles.img, { height }]}
          resizeMode="cover"
          accessibilityIgnoresInvertColors
        />
      ) : (
        <View style={[styles.img, { height, backgroundColor: colors.surface }]} />
      )}
      <LinearGradient
        colors={["transparent", "rgba(11,6,4,0.4)", colors.background]}
        locations={[0, 0.6, 1]}
        style={[styles.fade, { height }]}
      />
      {children ? <View style={styles.content}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { width: "100%", position: "relative" },
  img: { width: "100%", position: "absolute", left: 0, top: 0 },
  fade: { width: "100%", position: "absolute", left: 0, top: 0 },
  content: { flex: 1, justifyContent: "flex-end" },
});
