import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Pressable, StyleSheet } from "react-native";

import { colors, MIN_TOUCH, radius } from "@/state/theme";

interface IconButtonProps {
  name: React.ComponentProps<typeof Ionicons>["name"];
  onPress: () => void;
  accessibilityLabel: string;
  size?: number;
  color?: string;
  disabled?: boolean;
}

/** Icon-only button. Always >= 44x44 dp and always has an accessibilityLabel
 * (usability bar). */
export function IconButton({
  name,
  onPress,
  accessibilityLabel,
  size = 26,
  color = colors.text,
  disabled,
}: IconButtonProps): React.ReactElement {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      hitSlop={8}
      style={({ pressed, focused }) => [
        styles.btn,
        focused && styles.focused,
        pressed && styles.pressed,
        disabled && styles.disabled,
      ]}
    >
      <Ionicons name={name} size={size} color={color} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    minWidth: MIN_TOUCH,
    minHeight: MIN_TOUCH,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.pill,
  },
  pressed: { opacity: 0.6 },
  disabled: { opacity: 0.35 },
  // Visible focus ring for TV / keyboard D-pad navigation.
  focused: { borderWidth: 2, borderColor: colors.accent, backgroundColor: colors.surfaceAlt },
});
