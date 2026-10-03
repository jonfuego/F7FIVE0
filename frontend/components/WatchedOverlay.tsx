// Small visual indicators layered on top of Poster. Kept separate from
// MediaCard so the ContinueWatching card and any future card variants can
// reuse the same geometry.
//
// WatchedOverlay is a check badge in the top-right corner.
// ProgressBarOverlay is a thin hive bar at the bottom , same visual as
// the ContinueWatching card but dimmed so a library-grid tile doesn't
// scream for attention.

import { Check } from "lucide-react";
import { Icon } from "@/components/Icon";

export function WatchedOverlay() {
  return (
    <div
      aria-label="Watched"
      title="Watched"
      className="pointer-events-none absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-full bg-hive text-on-hive shadow ring-1 ring-focus"
    >
      <Icon icon={Check} size={14} />
    </div>
  );
}

export function ProgressBarOverlay({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="pointer-events-none absolute inset-x-2 bottom-2 overflow-hidden rounded-full bg-neutral-900/70">
      <div
        className="h-1 bg-hive"
        style={{ width: `${clamped}%` }}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={clamped}
      />
    </div>
  );
}
