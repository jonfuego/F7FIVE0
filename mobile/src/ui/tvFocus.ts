// Shared Android TV / tvOS focus treatment from the design system. On focus an
// element scales to 1.06 and draws a 4px focus ring at 4px offset, over the hard
// HIVE offset. Unfocused captions drop to 60%. Everything on TV sits at 24px or
// larger. Use tvFocusStyle(focused) inside a Pressable style callback, or read
// the constants directly.
import type { ViewStyle } from "react-native";

import { colors } from "../state/theme";

export const TV_FOCUS = {
  /** Focused poster/button scale. */
  scale: 1.06,
  /** Focus ring width in px (TV uses 4; phone uses 2). */
  ringWidth: 4,
  /** Focus ring offset in px. */
  ringOffset: 4,
  /** Ring color: the focus token (white on dark). */
  ringColor: colors.focus,
  /** The HIVE offset distance behind a focused tile. */
  hiveOffset: 6,
  /** Captions on unfocused items sit at 60%. */
  unfocusedCaptionOpacity: 0.6,
} as const;

/** Border + transform for a focusable TV tile. Pair the border with a matching
 * transparent border in the rest state so layout does not jump on focus. */
export function tvFocusStyle(focused: boolean): ViewStyle {
  return {
    transform: [{ scale: focused ? TV_FOCUS.scale : 1 }],
    borderWidth: TV_FOCUS.ringWidth,
    borderColor: focused ? TV_FOCUS.ringColor : "transparent",
  };
}
