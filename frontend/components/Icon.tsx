// Shared icon wrapper. Every icon in the web app is a Lucide glyph drawn the
// F7FIVE0 way: stroke 2.25, square caps, miter joins. Play, pause and skip are
// filled (pass fill). Sizes: 16 dense rows, 18 to 20 buttons and menus,
// 22 tab bars, 28 player. Colors come from the surrounding text color
// (ink-2 at rest, ink on hover, hive-text active) via currentColor.

import type { LucideIcon, LucideProps } from "lucide-react";

type Props = Omit<LucideProps, "fill" | "ref"> & {
  icon: LucideIcon;
  size?: number;
  fill?: boolean;
};

export function Icon({ icon: Glyph, size = 20, fill = false, ...rest }: Props) {
  return (
    <Glyph
      size={size}
      strokeWidth={2.25}
      strokeLinecap="square"
      strokeLinejoin="miter"
      fill={fill ? "currentColor" : "none"}
      aria-hidden={rest["aria-label"] ? undefined : true}
      {...rest}
    />
  );
}

export default Icon;
