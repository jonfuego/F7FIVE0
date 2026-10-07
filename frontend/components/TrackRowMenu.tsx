// Shared per-track 3-dot menu for music track rows. One kebab button that
// opens a three-item menu acting on a single track: Play now, Play next, Add
// to queue. The caller passes the track already mapped to a QueueItem (null
// when the track has no playable file, which disables the menu) so this file
// stays agnostic about where the row came from. Used by the album page track
// rows (/music/[id]) and the flat songs index (/music/songs) so the menu
// markup and action wiring live in one place.

"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { EllipsisVertical } from "lucide-react";
import { Icon } from "@/components/Icon";
import { useQueue, type QueueItem } from "@/lib/queue";

export function TrackRowMenu({
  item,
  label,
}: {
  // The track as a QueueItem, or null when it has no playable file (menu
  // renders disabled).
  item: QueueItem | null;
  // Accessible name for the kebab button, e.g. the track title.
  label: string;
}) {
  const { playNow, playNext, addToQueue } = useQueue();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const playable = item !== null;

  function onPlayNow(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setOpen(false);
    if (item) playNow(item);
  }
  function onPlayNext(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setOpen(false);
    if (item) playNext(item);
  }
  function onAddToQueue(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setOpen(false);
    if (item) addToQueue([item]);
  }

  return (
    <div ref={wrapRef} style={anchorStyle}>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-label={`${label} actions`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={!playable}
        style={{ ...buttonStyle, opacity: playable ? 1 : 0.4, cursor: playable ? "pointer" : "default" }}
      >
        <Icon icon={EllipsisVertical} size={16} />
      </button>
      {open && playable ? (
        <div role="menu" style={menuStyle}>
          <button type="button" role="menuitem" onClick={onPlayNow} style={menuItemStyle}>
            Play now
          </button>
          <button type="button" role="menuitem" onClick={onPlayNext} style={menuItemStyle}>
            Play next
          </button>
          <button type="button" role="menuitem" onClick={onAddToQueue} style={menuItemStyle}>
            Add to queue
          </button>
        </div>
      ) : null}
    </div>
  );
}

const anchorStyle: CSSProperties = {
  position: "relative",
  display: "inline-flex",
  flex: "0 0 auto",
};
const buttonStyle: CSSProperties = {
  background: "transparent",
  border: "none",
  color: "var(--ink-3)",
  padding: "4px 8px",
  lineHeight: 1,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
};
const menuStyle: CSSProperties = {
  position: "absolute",
  top: "calc(100% + 4px)",
  right: 0,
  minWidth: 160,
  background: "var(--bg-2)",
  border: "1px solid var(--line)",
  borderRadius: 4,
  fontFamily: "var(--grotesk)",
  fontSize: 13,
  boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
  zIndex: 5,
  overflow: "hidden",
};
const menuItemStyle: CSSProperties = {
  display: "block",
  width: "100%",
  padding: "8px 12px",
  background: "transparent",
  border: "none",
  color: "var(--ink-1)",
  textAlign: "left",
  cursor: "pointer",
  fontFamily: "inherit",
  fontSize: "inherit",
};
