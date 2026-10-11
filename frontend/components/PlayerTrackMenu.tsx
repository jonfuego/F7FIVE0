// Shared 3-dot track menu for the audio player. Used by the dock mini player
// (MiniPlayer.tsx) and the Now Playing view on /watch, so both surfaces list
// the same actions in the same order. Items that need an id the current track
// lacks are disabled, not hidden, so the menu shape stays stable.
//
// Go to album / Go to artist navigate with the Next router and never touch
// playback: the dock <audio> lives in MiniPlayer and survives the route
// change, so the music keeps playing while Now Playing closes behind the push.
//
// The popup is portaled to <body> and positioned with position: fixed from the
// button's rect (lib/menu-position.ts), so no player ancestor can clip it or
// stack above it. It has an opaque background and a z-index above the player
// view, and it stays off any element matching `avoidSelector` (the track title).

"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { EllipsisVertical } from "lucide-react";
import { Icon } from "@/components/Icon";
import { startArtistRadio } from "@/lib/artist-radio";
import { apiGet } from "@/lib/client-api";
import { placeMenu, type Rect } from "@/lib/menu-position";
import { albumToQueueItems, useQueue, type QueueItem } from "@/lib/queue";
import type { AlbumDetail } from "@/lib/types";

export function PlayerTrackMenu({
  albumId,
  artistId,
  placement = "down",
  avoidSelector,
  buttonClassName,
  buttonStyle,
  iconSize = 16,
}: {
  albumId: string | null;
  artistId: string | null;
  placement?: "up" | "down";
  // CSS selector for elements the menu must not cover (the track title).
  avoidSelector?: string;
  buttonClassName?: string;
  buttonStyle?: CSSProperties;
  iconSize?: number;
}) {
  const router = useRouter();
  const { playNextBlock, addToQueue } = useQueue();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  // Fixed-position spot for the open menu; null until it has been measured.
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      const t = e.target as Node;
      if (wrapRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Measure the button, the menu and the title, then place the menu. Runs before
  // paint (the menu renders hidden until placed) and again on resize.
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const btn = wrapRef.current;
      const menu = menuRef.current;
      if (!btn || !menu) return;
      const a = btn.getBoundingClientRect();
      const m = menu.getBoundingClientRect();
      const avoid: Rect[] = avoidSelector
        ? Array.from(document.querySelectorAll(avoidSelector)).map((el) => el.getBoundingClientRect())
        : [];
      const spot = placeMenu({
        anchor: a,
        size: { width: m.width, height: m.height },
        viewport: { width: window.innerWidth, height: window.innerHeight },
        avoid,
        prefer: placement,
      });
      setPos({ left: spot.left, top: spot.top });
    }
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, placement, avoidSelector]);

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
        onClick={() => {
          // Drop the old spot so the menu is measured fresh and stays hidden until placed.
          setPos(null);
          setOpen((v) => !v);
        }}
        aria-label="Track actions"
        aria-haspopup="menu"
        aria-expanded={open}
        className={buttonClassName}
        style={buttonStyle}
      >
        <Icon icon={EllipsisVertical} size={iconSize} />
      </button>
      {open
        ? createPortal(
            <div
              ref={menuRef}
              role="menu"
              style={{
                ...menuStyle,
                left: pos?.left ?? 0,
                top: pos?.top ?? 0,
                visibility: pos ? "visible" : "hidden",
              }}
            >
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
            </div>,
            document.body,
          )
        : null}
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

// Opaque on purpose. The old `var(--bg-2)` is not a token: the v3 design tokens
// define --bg and --surface-1..3 only, so the variable was undefined, the
// declaration was invalid at computed-value time and the menu painted with no
// background. --surface-2 is a solid colour (#181818 dark); the literal is the
// fallback so the menu can never go transparent. z-index 400 sits above the
// player view (.np is 100) and its queue panel.
const menuStyle: CSSProperties = {
  position: "fixed",
  minWidth: 180,
  background: "var(--surface-2, #181818)",
  border: "1px solid var(--line, #2c2c2c)",
  borderRadius: 4,
  fontFamily: "var(--font-sans)",
  fontSize: 13,
  boxShadow: "var(--shadow-overlay, 0 16px 48px 0 rgba(0,0,0,0.8))",
  zIndex: 400,
  overflow: "hidden",
};
const menuItemStyle: CSSProperties = {
  display: "block",
  width: "100%",
  padding: "10px 14px",
  background: "transparent",
  border: "none",
  color: "var(--ink, #ffffff)",
  textAlign: "left",
  fontFamily: "inherit",
  fontSize: "inherit",
  whiteSpace: "nowrap",
};
