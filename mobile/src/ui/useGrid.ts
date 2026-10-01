import { useWindowDimensions } from "react-native";

import { spacing } from "@/state/theme";

/** Library grid geometry: 4 per row on a phone in portrait (Plex-like density;
 * the web's 2-up posters are too big on a phone), more in landscape / tablets.
 * Leaves room on the right for the A-Z rail. */
export const GRID_GAP = 10;
const RAIL_GUTTER = 18;

export function gridColumns(width: number, height: number): number {
  // Tablets / TVs (short side >= 600dp) get the widest grid; a phone gets
  // 4 in portrait and 6 in landscape.
  if (Math.min(width, height) >= 600) return 7;
  if (width > height) return 6;
  return 4;
}

export function gridItemWidth(width: number, columns: number, withRail = true): number {
  const usable = width - spacing.lg * 2 - (withRail ? RAIL_GUTTER : 0) - GRID_GAP * (columns - 1);
  return Math.floor(usable / columns);
}

export function useGrid(withRail = true): { columns: number; itemWidth: number } {
  const { width, height } = useWindowDimensions();
  const columns = gridColumns(width, height);
  return { columns, itemWidth: gridItemWidth(width, columns, withRail) };
}
