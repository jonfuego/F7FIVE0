// Shared per-tile album context menu. Lives over an album cover as a
// small kebab button that opens a four-item menu acting on the album:
// Play now, Play next, Shuffle, Add all to queue. Fetches album detail
// on demand and maps it through albumToQueueItems before handing the
// block to the queue. Used by both /music/albums and the artist page
// discography grid so the menu markup lives in one place.

"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { apiGet } from "@/lib/client-api";
import { albumToQueueItems, useQueue, type QueueItem } from "@/lib/queue";
import type { AlbumDetail } from "@/lib/types";

export function AlbumTileMenu({
  albumId,
  albumTitle,
}: {
  albumId: string;
  albumTitle: string;
}) {
  const { playAlbum, playNextBlock, addToQueue } = useQueue();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (!menuRef.current) return;
      if (!menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  async function loadItems(): Promise<QueueItem[]> {
    try {
      const detail = await apiGet<AlbumDetail>(`/api/library/albums/${albumId}`);
      return albumToQueueItems(detail);
    } catch {
      return [];
    }
  }

  async function onPlayNow(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setMenuOpen(false);
    const items = await loadItems();
    if (items.length > 0) playAlbum(items);
  }
  async function onPlayNext(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setMenuOpen(false);
    const items = await loadItems();
    if (items.length > 0) playNextBlock(items);
  }
  async function onShuffleAlbum(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setMenuOpen(false);
    const items = await loadItems();
    if (items.length > 0) playAlbum(items, { shuffle: true });
  }
  async function onAddAll(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setMenuOpen(false);
    const items = await loadItems();
    if (items.length > 0) addToQueue(items);
  }

  return (
    <div ref={menuRef} style={tileMenuAnchorStyle}>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setMenuOpen((v) => !v);
        }}
        aria-label={`${albumTitle} actions`}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        style={tileMenuButtonStyle}
      >
        ...
      </button>
      {menuOpen ? (
        <div role="menu" style={tileMenuStyle}>
          <button type="button" role="menuitem" onClick={onPlayNow} style={tileMenuItemStyle}>
            Play now
          </button>
          <button type="button" role="menuitem" onClick={onPlayNext} style={tileMenuItemStyle}>
            Play next
          </button>
          <button type="button" role="menuitem" onClick={onShuffleAlbum} style={tileMenuItemStyle}>
            Shuffle
          </button>
          <button type="button" role="menuitem" onClick={onAddAll} style={tileMenuItemStyle}>
            Add all to queue
          </button>
        </div>
      ) : null}
    </div>
  );
}

const tileMenuAnchorStyle: CSSProperties = {
  position: "absolute",
  top: 6,
  right: 6,
  zIndex: 2,
};
const tileMenuButtonStyle: CSSProperties = {
  background: "rgba(0,0,0,0.55)",
  color: "#fff",
  border: "1px solid rgba(255,255,255,0.15)",
  borderRadius: 4,
  width: 28,
  height: 24,
  fontFamily: "var(--mono)",
  fontSize: 14,
  lineHeight: 1,
  cursor: "pointer",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
};
const tileMenuStyle: CSSProperties = {
  position: "absolute",
  top: "calc(100% + 4px)",
  right: 0,
  minWidth: 170,
  background: "var(--bg-2)",
  border: "1px solid var(--line)",
  borderRadius: 4,
  fontFamily: "var(--grotesk)",
  fontSize: 13,
  boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
  zIndex: 3,
};
const tileMenuItemStyle: CSSProperties = {
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
