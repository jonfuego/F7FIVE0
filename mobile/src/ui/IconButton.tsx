import type { LucideIcon } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet } from "react-native";

import { colors, MIN_TOUCH, radius } from "@/state/theme";
import { Icon } from "./Icon";

interface IconButtonProps {
  icon: LucideIcon;
  onPress: () => void;
  accessibilityLabel: string;
  size?: number;
  color?: string;
  disabled?: boolean;
  fill?: boolean;
}

/** Icon-only button. Always >= 44x44 dp and always has an accessibilityLabel
 * (usability bar). */
export function IconButton({
  icon,
  onPress,
  accessibilityLabel,
  size = 26,
  color = colors.text,
  disabled,
  fill,
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
      <Icon icon={icon} size={size} color={color} fill={fill} />
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
