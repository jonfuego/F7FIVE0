import { Ionicons } from "@expo/vector-icons";
import React, { useCallback } from "react";
import { Pressable, View } from "react-native";
import CastContext, {
  CastButton as RNCastButton,
  CastState,
  useCastState,
} from "react-native-google-cast";

import { colors, MIN_TOUCH } from "@/state/theme";

// Cast icon button (phone only; the TV build uses CastButton.tv.tsx).
//
// The library's own <CastButton> (MediaRouteButton) only opens its chooser once
// PASSIVE discovery has surfaced a device, so on real networks a tap did nothing
// until then. We instead open the chooser with CastContext.showCastDialog(),
// which runs an ACTIVE scan (like the YouTube cast button), so nearby receivers
// appear right away. IMPORTANT: on Android showCastDialog() only works if a
// MediaRouteButton is present in the tree, so we render one hidden (1x1, opacity
// 0, non-interactive) next to our visible icon. Session connect + the media
// hand-off are handled by useCast().
export function CastButton({
  size = 24,
  tintColor = colors.text,
}: {
  size?: number;
  tintColor?: string;
}): React.ReactElement {
  const state = useCastState();
  const active = state === CastState.CONNECTED || state === CastState.CONNECTING;

  const onPress = useCallback(() => {
    void CastContext.showCastDialog().catch(() => {});
  }, []);

  return (
    <View style={{ width: MIN_TOUCH, height: MIN_TOUCH, alignItems: "center", justifyContent: "center" }}>
      {/* Hidden MediaRouteButton: required on Android for showCastDialog() to
          work. Kept 1x1 + transparent + non-interactive so it never shows or
          steals the tap, but it still registers with the Cast framework. */}
      <RNCastButton
        pointerEvents="none"
        style={{ position: "absolute", width: 1, height: 1, opacity: 0 }}
      />
      <Pressable
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel="Cast"
        hitSlop={8}
        style={{ width: MIN_TOUCH, height: MIN_TOUCH, alignItems: "center", justifyContent: "center" }}
      >
        <Ionicons
          name={active ? "tv" : "tv-outline"}
          size={size}
          color={active ? colors.accent : tintColor}
        />
      </Pressable>
    </View>
  );
}
