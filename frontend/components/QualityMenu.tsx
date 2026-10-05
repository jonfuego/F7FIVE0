// Quality gear for the video player. It used to live in the top-right overlay
// of Player.tsx, right next to the watch page's "Close player" X, which was too
// easy to hit by accident. It now sits in the VideoTransport controls row near
// fullscreen, so its menu opens upward (bottom-full) from the bar.
//
// Two shapes, one dispatcher. Multi-rendition HLS switches hls.js levels in the
// browser; a CPU-only server sends one rendition per stream, so each choice
// restarts the stream at that height. Player decides which (and whether to show
// one at all) and hands the descriptor down through the watch page.

"use client";

import { useEffect, useRef, useState } from "react";
import type { Level } from "hls.js";
import { Check, Settings } from "lucide-react";
import { Icon } from "@/components/Icon";

export type QualityControlData =
  | {
      kind: "hls";
      levels: Level[];
      loadedLevel: number;
      userLevel: number;
      onSelect: (index: number) => void;
    }
  | {
      kind: "server";
      heights: number[];
      current: number;
      onSelect: (height: number) => void;
    };

/** Dispatcher: render the gear that matches the descriptor, or nothing. */
export function QualityControl({ data }: { data: QualityControlData | null }) {
  if (!data) return null;
  if (data.kind === "hls") {
    return (
      <QualityMenu
        levels={data.levels}
        loadedLevel={data.loadedLevel}
        userLevel={data.userLevel}
        onSelect={data.onSelect}
      />
    );
  }
  return (
    <ServerQualityMenu heights={data.heights} current={data.current} onSelect={data.onSelect} />
  );
}

function QualityMenu({
  levels,
  loadedLevel,
  userLevel,
  onSelect,
}: {
  levels: Level[];
  loadedLevel: number;
  userLevel: number;
  onSelect: (index: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  // Build entries indexed by their position in hls.levels (stable for
  // `hls.currentLevel`), sorted by height descending for display.
  const entries = levels
    .map((lv, i) => ({ index: i, height: lv.height ?? 0, bitrate: lv.bitrate ?? 0 }))
    .sort((a, b) => b.height - a.height || b.bitrate - a.bitrate);

  const activeLevel = levels[loadedLevel];
  const autoLabel = activeLevel?.height ? `Auto (${activeLevel.height}p)` : "Auto";
  const buttonLabel =
    userLevel === -1
      ? autoLabel
      : levels[userLevel]?.height
        ? `${levels[userLevel].height}p`
        : `Level ${userLevel}`;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-md bg-black/60 px-2.5 py-1 text-xs font-medium text-neutral-100 backdrop-blur-sm transition hover:bg-black/75"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Quality"
      >
        <GearIcon />
        <span className="hidden sm:inline">{buttonLabel}</span>
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute bottom-full right-0 mb-1 min-w-[9rem] overflow-hidden rounded-md border border-neutral-800 bg-neutral-950/95 text-sm shadow-lg backdrop-blur-sm"
        >
          <MenuItem
            label={autoLabel}
            selected={userLevel === -1}
            onClick={() => {
              onSelect(-1);
              setOpen(false);
            }}
          />
          <div className="border-t border-neutral-900" />
          {entries.map((e) => (
            <MenuItem
              key={e.index}
              label={e.height ? `${e.height}p` : `Level ${e.index}`}
              selected={userLevel === e.index}
              onClick={() => {
                onSelect(e.index);
                setOpen(false);
              }}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** Quality picker for CPU-only servers: each choice restarts the stream at
 * that height (one encode at a time), rather than switching hls.js levels. */
function ServerQualityMenu({
  heights,
  current,
  onSelect,
}: {
  heights: number[];
  current: number;
  onSelect: (height: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const shown = heights.includes(current) ? current : heights[0];

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-md bg-black/60 px-2.5 py-1 text-xs font-medium text-neutral-100 backdrop-blur-sm transition hover:bg-black/75"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Quality"
      >
        <GearIcon />
        <span className="hidden sm:inline">{`${shown}p`}</span>
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute bottom-full right-0 mb-1 min-w-[9rem] overflow-hidden rounded-md border border-neutral-800 bg-neutral-950/95 text-sm shadow-lg backdrop-blur-sm"
        >
          {heights.map((h) => (
            <MenuItem
              key={h}
              label={`${h}p`}
              selected={h === shown}
              onClick={() => {
                setOpen(false);
                if (h !== shown) onSelect(h);
              }}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function MenuItem({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={selected}
      onClick={onClick}
      className={`flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left transition hover:bg-neutral-900 ${
        selected ? "text-hive-text" : "text-neutral-200"
      }`}
    >
      <span>{label}</span>
      {selected ? <CheckIcon /> : null}
    </button>
  );
}

function GearIcon() {
  return <Icon icon={Settings} size={14} aria-hidden="true" />;
}

function CheckIcon() {
  return <Icon icon={Check} size={12} aria-hidden="true" />;
}
