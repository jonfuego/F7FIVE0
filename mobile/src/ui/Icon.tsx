// Shared icon wrapper for phone and TV. Every icon is a Lucide glyph (via
// lucide-react-native, which renders react-native-svg) drawn the F7FIVE0 way:
// stroke 2.25, square caps, miter joins. Play, pause and skip are filled
// (pass fill). Sizes: 16 dense rows, 18 to 20 buttons and menus, 22 tab bars,
// 28 TV and player. Colors: ink-2 at rest, ink hover/active, hive-text active.

import type { LucideIcon, LucideProps } from "lucide-react-native";
import { colors } from "../state/theme";

type Props = Omit<LucideProps, "fill"> & {
  icon: LucideIcon;
  size?: number;
  color?: string;
  fill?: boolean;
};

export function Icon({ icon: Glyph, size = 22, color = colors.ink2, fill = false, ...rest }: Props) {
  return (
    <Glyph
      size={size}
      color={color}
      strokeWidth={2.25}
      strokeLinecap="square"
      strokeLinejoin="miter"
      fill={fill ? color : "none"}
      {...rest}
    />
  );
}

export default Icon;
