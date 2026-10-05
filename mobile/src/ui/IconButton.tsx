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
  /** Square control (radius.md) instead of the default pill. Used by the
   * play/pause control so it matches the square-cap Lucide icons. */
  square?: boolean;
  /** Explicit control size in dp (width and height). Defaults to the MIN_TOUCH
   * box. Kept within the 44 to 56 dp range for the play control. */
  diameter?: number;
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
  square,
  diameter,
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
        square && styles.square,
        diameter != null && {
          width: diameter,
          height: diameter,
          minWidth: diameter,
          minHeight: diameter,
        },
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
  // Square play/pause control (crit: not radius.pill).
  square: { borderRadius: radius.md },
  pressed: { opacity: 0.6 },
  disabled: { opacity: 0.35 },
  // Visible focus ring for TV / keyboard D-pad navigation.
  focused: { borderWidth: 2, borderColor: colors.accent, backgroundColor: colors.surfaceAlt },
});
