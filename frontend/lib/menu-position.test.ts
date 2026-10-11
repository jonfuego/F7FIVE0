// node:test coverage for the player menu placement.
//
// Run: node --test frontend/lib/menu-position.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { placeMenu, type Rect } from "./menu-position.ts";

const vp = { width: 400, height: 700 };
const size = { width: 180, height: 100 };

function rectOf(p: { left: number; top: number }): Rect {
  return { left: p.left, top: p.top, right: p.left + size.width, bottom: p.top + size.height };
}
function overlaps(a: Rect, b: Rect): boolean {
  return Math.min(a.right, b.right) > Math.max(a.left, b.left) && Math.min(a.bottom, b.bottom) > Math.max(a.top, b.top);
}
function inside(r: Rect): boolean {
  return r.left >= 0 && r.top >= 0 && r.right <= vp.width && r.bottom <= vp.height;
}

test("dock menu prefers up and stays above the button", () => {
  const anchor = { left: 340, top: 640, right: 380, bottom: 680 };
  const p = placeMenu({ anchor, size, viewport: vp, prefer: "up" });
  assert.equal(p.placement, "up");
  assert.ok(rectOf(p).bottom <= anchor.top);
  assert.ok(inside(rectOf(p)));
});

test("dock menu flips down when there is no room above", () => {
  const anchor = { left: 340, top: 20, right: 380, bottom: 60 };
  const p = placeMenu({ anchor, size, viewport: vp, prefer: "up" });
  assert.equal(p.placement, "down");
  assert.ok(rectOf(p).top >= anchor.bottom);
});

test("full player: opens below the button and clears the title", () => {
  const title = { left: 20, top: 400, right: 380, bottom: 470 };
  const anchor = { left: 320, top: 500, right: 376, bottom: 556 };
  const p = placeMenu({ anchor, size, viewport: vp, avoid: [title], prefer: "down" });
  assert.equal(p.placement, "down");
  assert.equal(overlaps(rectOf(p), title), false);
  assert.ok(inside(rectOf(p)));
});

test("full player: no room below and up would hit the title, so it goes beside the button", () => {
  const title = { left: 20, top: 520, right: 380, bottom: 585 };
  const anchor = { left: 320, top: 640, right: 376, bottom: 690 };
  const p = placeMenu({ anchor, size, viewport: vp, avoid: [title], prefer: "down" });
  assert.equal(p.placement, "left");
  assert.equal(overlaps(rectOf(p), title), false);
  assert.equal(overlaps(rectOf(p), anchor), false);
  assert.ok(inside(rectOf(p)));
});

test("the menu is clamped inside the viewport horizontally", () => {
  const anchor = { left: 4, top: 300, right: 40, bottom: 340 };
  const p = placeMenu({ anchor, size, viewport: vp, prefer: "down" });
  assert.ok(p.left >= 8);
  assert.ok(inside(rectOf(p)));
});

test("a menu taller than the viewport is pinned to the top margin", () => {
  const tall = { width: 180, height: 900 };
  const anchor = { left: 320, top: 300, right: 376, bottom: 340 };
  const p = placeMenu({ anchor, size: tall, viewport: vp });
  assert.equal(p.top, 8);
});

test("with no avoid rects the preferred side wins", () => {
  const anchor = { left: 320, top: 300, right: 376, bottom: 340 };
  assert.equal(placeMenu({ anchor, size, viewport: vp, prefer: "down" }).placement, "down");
  assert.equal(placeMenu({ anchor, size, viewport: vp, prefer: "up" }).placement, "up");
});

test("full player on a short window: sits beside the button below the title, not over it", () => {
  const short = { width: 1280, height: 720 };
  const bigMenu = { width: 180, height: 199 };
  const title = { left: 510, top: 461, right: 770, bottom: 503 };
  const anchor = { left: 636, top: 527, right: 692, bottom: 583 };
  const p = placeMenu({ anchor, size: bigMenu, viewport: short, avoid: [title], prefer: "down" });
  const r = { left: p.left, top: p.top, right: p.left + bigMenu.width, bottom: p.top + bigMenu.height };
  assert.equal(overlaps(r, title), false);
  assert.equal(overlaps(r, anchor), false);
  assert.ok(r.left >= 0 && r.top >= 0 && r.right <= short.width && r.bottom <= short.height);
});
