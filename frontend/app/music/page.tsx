// Music — square 1:1 album / artist tile grid (aspect-ratio: 1/1 with
// gap: 20px), rendered via the <Grid variant="square"> + .sq-grid /
// .sq-card .cover classes in globals.css. Click an artist to drill into
// their discography at /music/artists/<id>.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AuthShell } from "@/components/AuthShell";
import EditOverridesModal, { algorithmicSortHint } from "@/components/EditOverridesModal";
import { ArtistMergeDialog } from "@/components/ArtistMergeDialog";
import { AlphaRail, alphaLetterOf } from "@/components/AlphaRail";
import { Grid, GridEmpty } from "@/components/Grid";
import { apiGet } from "@/lib/client-api";
import { colorForTitle, hueFromString } from "@/lib/format";
import { emptyLibraryText } from "@/lib/library-scan";
import { useQueue, type QueueItem } from "@/lib/queue";
import { useScanState } from "@/lib/use-scan-state";
import { useScrollRestoration } from "@/lib/scroll-restoration";
import { useViewPref } from "@/lib/use-view-pref";
import type { MusicArtist, OverrideOut } from "@/lib/types";
import { artSized } from "@/lib/art-url";

type EditInitial = OverrideOut & { algorithmic_sort_hint: string };

export default function MusicPage() {
  useScrollRestoration();
  const [artists, setArtists] = useState<MusicArtist[] | null>(null);
  // Saved view: the Music browse tab (Artists / Albums / Songs) is stored on
  // the server per user. Opening Music goes back to the tab you last picked.
  const router = useRouter();
  const [browse, setBrowse, browseLoaded] = useViewPref("music.browse");
  useEffect(() => {
    if (!browseLoaded || browse === "artists") return;
    router.replace(browse === "albums" ? "/music/albums" : "/music/songs");
  }, [browseLoaded, browse, router]);
  const [error, setError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const [editTarget, setEditTarget] = useState<MusicArtist | null>(null);
  const [editInitial, setEditInitial] = useState<EditInitial | null>(null);
  // While a folder scan runs the list reloads every few seconds.
  const scan = useScanState();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/session/me", { cache: "no-store" });
        if (!res.ok) return;
        const me = (await res.json()) as { role?: string };
        if (!cancelled && me?.role === "admin") setIsAdmin(true);
      } catch {
        // non-admin stays hidden
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onApplied = useCallback(() => setReloadTick((t) => t + 1), []);

  const openCardEdit = useCallback(async (a: MusicArtist) => {
    setEditTarget(a);
    try {
      const res = await fetch(`/api/admin/override/artist/${a.id}`, {
        cache: "no-store",
      });
      if (!res.ok) return;
      const body = (await res.json()) as OverrideOut;
      setEditInitial({
        ...body,
        algorithmic_sort_hint: algorithmicSortHint(a.name),
      });
    } catch {
      setEditInitial(null);
    }
  }, []);

  const closeCardEdit = useCallback(() => {
    setEditTarget(null);
    setEditInitial(null);
  }, []);


  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<MusicArtist[]>("/api/library/artists");
        if (!cancelled) setArtists(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load artists");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadTick, scan.ticks]);

  const filtered = useMemo(() => {
    if (!artists) return null;
    return artists;
  }, [artists]);

  return (
    <AuthShell>
      <h1 className="page-title">Music</h1>

      <div className="filter-bar">
        <span className="lbl">Browse</span>
        <span className="chip on">Artists</span>
        <Link href="/music/albums" className="chip" onClick={() => setBrowse("albums")}>Albums</Link>
        <Link href="/music/songs" className="chip" onClick={() => setBrowse("songs")}>Songs</Link>
      </div>

      {error ? (
        <GridEmpty message={error} />
      ) : filtered === null ? (
        <Grid variant="square">
          {Array.from({ length: 18 }).map((_, i) => (
            <div
              key={i}
              style={{
                width: "100%",
                aspectRatio: "1/1",
                background: "var(--surface-2)",
                borderRadius: 4,
              }}
            />
          ))}
        </Grid>
      ) : filtered.length === 0 ? (
        <GridEmpty message={emptyLibraryText("artists", scan.running)} />
      ) : (
        <Grid variant="square">
          {filtered.map((a) => (
            <div key={a.id} data-alpha-letter={alphaLetterOf(a.name)}>
              <ArtistTile
                artist={a}
                isAdmin={isAdmin}
                onEdit={() => openCardEdit(a)}
                onMerged={onApplied}
              />
            </div>
          ))}
        </Grid>
      )}
      <AlphaRail resetKey={`music:${filtered ? filtered.length : 0}`} />

      {editTarget && editInitial ? (
        <EditOverridesModal
          open
          kind="artist"
          entityId={editTarget.id}
          initial={editInitial}
          onClose={closeCardEdit}
          onApplied={onApplied}
        />
      ) : null}
    </AuthShell>
  );
}

function ArtistTile({
  artist,
  isAdmin,
  onEdit,
  onMerged,
}: {
  artist: MusicArtist;
  isAdmin?: boolean;
  onEdit?: () => void;
  onMerged?: () => void;
}) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(artist.name),
    ["--ph" as never]: String(hueFromString(artist.name)),
  };
  const { playAlbum } = useQueue();
  const [menuOpen, setMenuOpen] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
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

  async function loadAutoPlaylist(kind: "by-artist" | "artist-radio"): Promise<QueueItem[]> {
    try {
      const data = await apiGet<{ items: QueueItem[] }>(
        `/api/library/auto-playlist/${kind}/${artist.id}`,
      );
      return Array.isArray(data.items) ? data.items : [];
    } catch {
      return [];
    }
  }

  async function onShuffleArtist(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setMenuOpen(false);
    const items = await loadAutoPlaylist("by-artist");
    if (items.length > 0) playAlbum(items, { shuffle: true });
  }
  async function onArtistRadio(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setMenuOpen(false);
    const items = await loadAutoPlaylist("artist-radio");
    if (items.length > 0) playAlbum(items);
  }
  // Cover play button: the artist page's primary Play action (by-artist
  // auto-playlist straight into the dock), without following the card link.
  async function onPlay(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const items = await loadAutoPlaylist("by-artist");
    if (items.length > 0) playAlbum(items, { shuffle: false });
  }

  return (
    <Link
      href={`/music/artists/${artist.id}`}
      className="sq-card"
      style={tint}
      aria-label={artist.name}
    >
      <div className="cover">
        <div className="keyart-mini" />
        {artist.image_path ? (
          <img
            src={artSized(artist.image_path, 300) ?? artist.image_path}
            alt={artist.name}
            loading="lazy"
            decoding="async"
            className="real-art"
          />
        ) : null}
        <button
          type="button"
          className="play-spot"
          aria-label={`Play ${artist.name}`}
          onClick={onPlay}
        >
          <span className="tri" />
        </button>
        <div ref={menuRef} style={artistMenuAnchorStyle}>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setMenuOpen((v) => !v);
            }}
            aria-label={`${artist.name} actions`}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            style={artistMenuButtonStyle}
          >
            ...
          </button>
          {menuOpen ? (
            <div role="menu" style={artistMenuStyle}>
              <button type="button" role="menuitem" onClick={onShuffleArtist} style={artistMenuItemStyle}>
                Shuffle artist
              </button>
              <button type="button" role="menuitem" onClick={onArtistRadio} style={artistMenuItemStyle}>
                Artist radio
              </button>
              {isAdmin ? (
                <button
                  type="button"
                  role="menuitem"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setMenuOpen(false);
                    setMergeOpen(true);
                  }}
                  style={artistMenuItemStyle}
                >
                  Merge into...
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
        {isAdmin && onEdit ? (
          <button
            type="button"
            className="admin-edit"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onEdit();
            }}
            aria-label={`Edit ${artist.name}`}
          >
            Edit
          </button>
        ) : null}
      </div>
      <div className="info">
        <div className="t">{artist.name}</div>
        <div className="s">
          {artist.album_count} {artist.album_count === 1 ? "album" : "albums"}
        </div>
      </div>
      {mergeOpen ? (
        <ArtistMergeDialog
          sourceId={artist.id}
          sourceName={artist.name}
          onClose={() => setMergeOpen(false)}
          onMerged={() => {
            setMergeOpen(false);
            onMerged?.();
          }}
        />
      ) : null}
    </Link>
  );
}

const artistMenuAnchorStyle: CSSProperties = {
  position: "absolute",
  top: 6,
  right: 6,
  zIndex: 2,
};
const artistMenuButtonStyle: CSSProperties = {
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
const artistMenuStyle: CSSProperties = {
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
const artistMenuItemStyle: CSSProperties = {
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
