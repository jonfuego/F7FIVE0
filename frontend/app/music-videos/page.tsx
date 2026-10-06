// Music videos — 1:1 artist tile grid (aspect-ratio: 1/1), rendered via
// <Grid variant="square"> + .sq-grid / .sq-card .cover classes in
// globals.css. Tile Edit affordance opens the unified
// EditOverridesModal (General / Details / Art / Fix Match / Refresh).

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import Link from "next/link";
import EditOverridesModal, { algorithmicSortHint } from "@/components/EditOverridesModal";
import { AuthShell } from "@/components/AuthShell";
import { AlphaRail, alphaLetterOf } from "@/components/AlphaRail";
import { Grid, GridEmpty } from "@/components/Grid";
import { apiGet } from "@/lib/client-api";
import { colorForTitle, hueFromString } from "@/lib/format";
import { useScrollRestoration } from "@/lib/scroll-restoration";
import type { MusicVideoArtist, OverrideOut } from "@/lib/types";
import { useViewPref } from "@/lib/use-view-pref";

type EditInitial = OverrideOut & { algorithmic_sort_hint: string };

export default function MusicVideosPage() {
  useScrollRestoration();
  const [artists, setArtists] = useState<MusicVideoArtist[] | null>(null);
  // Saved view: artist order, stored on the server per user.
  const [mvSort, setMvSort] = useViewPref("musicvideos.sort");
  const [error, setError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const [editTarget, setEditTarget] = useState<MusicVideoArtist | null>(null);
  const [editInitial, setEditInitial] = useState<EditInitial | null>(null);

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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<MusicVideoArtist[]>(
          "/api/library/music-videos/artists",
        );
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
  }, [reloadTick]);

  const openCardEdit = useCallback(async (a: MusicVideoArtist) => {
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

  const onApplied = useCallback(() => setReloadTick((t) => t + 1), []);

  const filtered = useMemo(() => {
    if (!artists) return null;
    if (mvSort === "videos") {
      return artists.slice().sort((a, b) => b.video_count - a.video_count || a.name.localeCompare(b.name));
    }
    return artists;
  }, [artists, mvSort]);

  return (
    <AuthShell>
      <h1 className="page-title">Music Videos</h1>

      <div className="filter-bar">
        <span className="lbl">Browse</span>
        <span className="chip on">Artists</span>
      </div>
      <div className="filter-bar">
        <span className="lbl">Sort</span>
        <button
          type="button"
          className={`chip ${mvSort === "name" ? "on" : ""}`}
          onClick={() => setMvSort("name")}
        >
          Name
        </button>
        <button
          type="button"
          className={`chip ${mvSort === "videos" ? "on" : ""}`}
          onClick={() => setMvSort("videos")}
        >
          Most videos
        </button>
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
        <GridEmpty message="No music videos yet. An admin can run a scan from /admin." />
      ) : (
        <Grid variant="square">
          {filtered.map((a) => (
            <div key={a.id} data-alpha-letter={alphaLetterOf(a.name)}>
              <ArtistTile
                artist={a}
                isAdmin={isAdmin}
                onEdit={() => openCardEdit(a)}
              />
            </div>
          ))}
        </Grid>
      )}

      <AlphaRail resetKey={`music-videos:${filtered ? filtered.length : 0}`} />

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
}: {
  artist: MusicVideoArtist;
  isAdmin: boolean;
  onEdit: () => void;
}) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(artist.name),
    ["--ph" as never]: String(hueFromString(artist.name)),
  };
  return (
    <Link
      href={`/music-videos/${artist.id}`}
      className="sq-card"
      style={tint}
      aria-label={artist.name}
    >
      <div className="cover">
        <div className="keyart-mini" />
        {artist.image_path ? (
          <img
            src={artist.image_path}
            alt={artist.name}
            loading="lazy"
            decoding="async"
            className="real-art"
          />
        ) : null}
        <div className="play-spot" aria-hidden>
          <span className="tri" />
        </div>
        {isAdmin ? (
          <button
            type="button"
            className="admin-edit"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onEdit();
            }}
            aria-label={`Edit thumb for ${artist.name}`}
          >
            Edit
          </button>
        ) : null}
      </div>
      <div className="info">
        <div className="t">{artist.name}</div>
        <div className="s">
          {artist.video_count} {artist.video_count === 1 ? "video" : "videos"}
        </div>
      </div>
    </Link>
  );
}
