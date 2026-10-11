// Shared 3-dot track menu for the audio player. Used by the dock mini player
// (MiniPlayer.tsx) and the Now Playing view on /watch, so both surfaces list
// the same actions in the same order. Items that need an id the current track
// lacks are disabled, not hidden, so the menu shape stays stable.
//
// Go to album / Go to artist navigate with the Next router and never touch
// playback: the dock <audio> lives in MiniPlayer and survives the route
// change, so the music keeps playing while Now Playing closes behind the push.

"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { EllipsisVertical } from "lucide-react";
import { Icon } from "@/components/Icon";
import { startArtistRadio } from "@/lib/artist-radio";
import { apiGet } from "@/lib/client-api";
import { albumToQueueItems, useQueue, type QueueItem } from "@/lib/queue";
import type { AlbumDetail } from "@/lib/types";

export function PlayerTrackMenu({
  albumId,
  artistId,
  placement = "down",
  buttonClassName,
  buttonStyle,
  iconSize = 16,
}: {
  albumId: string | null;
  artistId: string | null;
  placement?: "up" | "down";
  buttonClassName?: string;
  buttonStyle?: CSSProperties;
  iconSize?: number;
}) {
  const router = useRouter();
  const { playNextBlock, addToQueue } = useQueue();
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

  async function loadAlbum(): Promise<QueueItem[]> {
    if (!albumId) return [];
    try {
      const detail = await apiGet<AlbumDetail>(`/api/library/albums/${albumId}`);
      return albumToQueueItems(detail);
    } catch {
      return [];
    }
  }

  async function playAlbumNext() {
    setOpen(false);
    const block = await loadAlbum();
    if (block.length > 0) playNextBlock(block);
  }
  async function addAlbum() {
    setOpen(false);
    const block = await loadAlbum();
    if (block.length > 0) addToQueue(block);
  }
  async function artistRadio() {
    setOpen(false);
    await startArtistRadio<QueueItem>(artistId, { get: apiGet, playNextBlock });
  }
  // Navigate only. No pause / stop / queue clear here, so the dock keeps
  // playing while the Now Playing route closes behind the push.
  function goToAlbum() {
    setOpen(false);
    if (!albumId) return;
    router.push(`/music/${albumId}`);
  }
  function goToArtist() {
    setOpen(false);
    if (!artistId) return;
    router.push(`/music/artists/${artistId}`);
  }

  return (
    <div ref={wrapRef} style={{ position: "relative", display: "inline-flex" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Track actions"
        aria-haspopup="menu"
        aria-expanded={open}
        className={buttonClassName}
        style={buttonStyle}
      >
        <Icon icon={EllipsisVertical} size={iconSize} />
      </button>
      {open ? (
        <div role="menu" style={placement === "up" ? menuStyleUp : menuStyleDown}>
          <MenuItem onClick={playAlbumNext} disabled={!albumId}>
            Play album next
          </MenuItem>
          <MenuItem onClick={goToAlbum} disabled={!albumId}>
            Go to album
          </MenuItem>
          <MenuItem onClick={goToArtist} disabled={!artistId}>
            Go to artist
          </MenuItem>
          <MenuItem onClick={artistRadio} disabled={!artistId}>
            Artist radio
          </MenuItem>
          <MenuItem onClick={addAlbum} disabled={!albumId}>
            Add album to queue
          </MenuItem>
        </div>
      ) : null}
    </div>
  );
}

function MenuItem({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      style={{
        ...menuItemStyle,
        opacity: disabled ? 0.4 : 1,
        cursor: disabled ? "default" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

const menuBaseStyle: CSSProperties = {
  position: "absolute",
  right: 0,
  minWidth: 180,
  background: "var(--bg-2)",
  border: "1px solid var(--line)",
  borderRadius: 4,
  fontFamily: "var(--grotesk)",
  fontSize: 13,
  boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
  zIndex: 50,
  overflow: "hidden",
};
const menuStyleUp: CSSProperties = { ...menuBaseStyle, bottom: "calc(100% + 8px)" };
const menuStyleDown: CSSProperties = { ...menuBaseStyle, top: "calc(100% + 8px)" };
const menuItemStyle: CSSProperties = {
  display: "block",
  width: "100%",
  padding: "10px 14px",
  background: "transparent",
  border: "none",
  color: "var(--ink-1)",
  textAlign: "left",
  fontFamily: "inherit",
  fontSize: "inherit",
  whiteSpace: "nowrap",
};
