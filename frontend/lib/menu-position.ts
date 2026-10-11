// Pure placement for the player track menu (batch 7 item 10). Given the
// trigger button, the menu size, the viewport and the rects the menu should
// stay off (the track title), it picks a spot: below or above the button, or
// beside it, always clamped inside the viewport. Kept apart from the React
// component so node:test covers it (menu-position.test.ts).
//
// Rule: the menu is right-aligned to the button and clamped horizontally. Each
// candidate (preferred side, the other side, then to the left and right of the
// button, at a few heights that sit clear of the avoid rects) is clamped into
// the viewport, then scored by how much it overlaps the avoid rects (weighted
// heavily) plus the button itself. The lowest score wins; ties go to the
// earlier candidate, so the preferred side is used whenever it is clear.

export type Rect = { left: number; top: number; right: number; bottom: number };
export type Placement = "down" | "up" | "left" | "right";

export type PlaceMenuInput = {
  anchor: Rect;
  size: { width: number; height: number };
  viewport: { width: number; height: number };
  avoid?: Rect[];
  prefer?: "down" | "up";
  gap?: number;
  margin?: number;
};

export type PlaceMenuResult = { left: number; top: number; placement: Placement };

function clamp(v: number, min: number, max: number): number {
  // When the menu is larger than the room, pin it to the start edge.
  return max < min ? min : Math.min(Math.max(v, min), max);
}

function overlapArea(a: Rect, b: Rect): number {
  const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return w > 0 && h > 0 ? w * h : 0;
}

// Covering the title is worse than covering the button, so it costs more.
const AVOID_WEIGHT = 10;

export function placeMenu(input: PlaceMenuInput): PlaceMenuResult {
  const { anchor, size, viewport } = input;
  const avoid = input.avoid ?? [];
  const gap = input.gap ?? 8;
  const margin = input.margin ?? 8;
  const prefer = input.prefer ?? "down";

  const maxLeft = viewport.width - size.width - margin;
  const maxTop = viewport.height - size.height - margin;
  const alignedLeft = clamp(anchor.right - size.width, margin, maxLeft);
  // Heights for a side placement: bottom-aligned with the button, top-aligned
  // with it, and just below or above each avoid rect.
  const sideTops = [
    anchor.bottom - size.height,
    anchor.top,
    ...avoid.map((r) => r.bottom + gap),
    ...avoid.map((r) => r.top - gap - size.height),
  ].map((t) => clamp(t, margin, maxTop));

  const down = { placement: "down" as const, left: alignedLeft, top: clamp(anchor.bottom + gap, margin, maxTop) };
  const up = { placement: "up" as const, left: alignedLeft, top: clamp(anchor.top - gap - size.height, margin, maxTop) };
  const leftX = clamp(anchor.left - gap - size.width, margin, maxLeft);
  const rightX = clamp(anchor.right + gap, margin, maxLeft);
  const lefts = sideTops.map((top) => ({ placement: "left" as const, left: leftX, top }));
  const rights = sideTops.map((top) => ({ placement: "right" as const, left: rightX, top }));

  const candidates = [...(prefer === "up" ? [up, down] : [down, up]), ...lefts, ...rights];

  let best = candidates[0];
  let bestScore = Infinity;
  for (const c of candidates) {
    const rect: Rect = { left: c.left, top: c.top, right: c.left + size.width, bottom: c.top + size.height };
    let score = overlapArea(rect, anchor);
    for (const r of avoid) score += AVOID_WEIGHT * overlapArea(rect, r);
    if (score < bestScore) {
      best = c;
      bestScore = score;
    }
  }
  return best;
}
