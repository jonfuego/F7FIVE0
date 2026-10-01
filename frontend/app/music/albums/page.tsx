// Music — Albums browse mode. Square 1:1 cover grid sorted by artist
// then chronological within each discography (backend default).

"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { CSSProperties } from "react";
import Link from "next/link";
import { AuthShell } from "@/components/AuthShell";
import { AlbumTileMenu } from "@/components/AlbumTileMenu";
import EditOverridesModal, { algorithmicSortHint } from "@/components/EditOverridesModal";
import { AlphaRail, alphaLetterOf } from "@/components/AlphaRail";
import { Grid, GridEmpty } from "@/components/Grid";
import { apiGet } from "@/lib/client-api";
import { colorForTitle, hueFromString } from "@/lib/format";
import type { Album, OverrideOut } from "@/lib/types";

type EditInitial = OverrideOut & { algorithmic_sort_hint: string };

export default function MusicAlbumsPage() {
  const [albums, setAlbums] = useState<Album[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const [editTarget, setEditTarget] = useState<Album | null>(null);
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

  const onApplied = useCallback(() => setReloadTick((t) => t + 1), []);

  const openCardEdit = useCallback(async (al: Album) => {
    setEditTarget(al);
    try {
      const res = await fetch(`/api/admin/override/album/${al.id}`, {
        cache: "no-store",
      });
      if (!res.ok) return;
      const body = (await res.json()) as OverrideOut;
      setEditInitial({
        ...body,
        algorithmic_sort_hint: algorithmicSortHint(al.title),
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
        const data = await apiGet<Album[]>("/api/library/albums?limit=2000");
        if (!cancelled) setAlbums(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load albums");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadTick]);

  return (
    <AuthShell>
      <h1 className="page-title">Music</h1>

      <div className="filter-bar">
        <span className="lbl">Browse</span>
        <Link href="/music" className="chip">Artists</Link>
        <span className="chip on">Albums</span>
        <Link href="/music/songs" className="chip">Songs</Link>
      </div>

      {error ? (
        <GridEmpty message={error} />
      ) : albums === null ? (
        <Grid variant="square">
          {Array.from({ length: 18 }).map((_, i) => (
            <div
              key={i}
              style={{
                width: "100%",
                aspectRatio: "1/1",
                background: "oklch(0.18 0.012 60)",
                borderRadius: 4,
              }}
            />
          ))}
        </Grid>
      ) : albums.length === 0 ? (
        <GridEmpty message="No albums in the library yet." />
      ) : (
        <Grid variant="square">
          {albums.map((a) => (
            <div
              key={a.id}
              data-alpha-letter={alphaLetterOf(a.artist_name ?? a.title)}
            >
              <AlbumTile
                album={a}
                isAdmin={isAdmin}
                onEdit={() => openCardEdit(a)}
              />
            </div>
          ))}
        </Grid>
      )}
      <AlphaRail resetKey={`albums:${albums ? albums.length : 0}`} />

      {editTarget && editInitial ? (
        <EditOverridesModal
          open
          kind="album"
          entityId={editTarget.id}
          initial={editInitial}
          onClose={closeCardEdit}
          onApplied={onApplied}
        />
      ) : null}
    </AuthShell>
  );
}

function AlbumTile({
  album,
  isAdmin,
  onEdit,
}: {
  album: Album;
  isAdmin?: boolean;
  onEdit?: () => void;
}) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(album.title),
    ["--ph" as never]: String(hueFromString(album.title)),
  };
  const sub = album.artist_name ?? "";
  const artistHref = album.artist_id ? `/music/artists/${album.artist_id}` : null;
  const router = useRouter();

  return (
    <Link
      href={`/music/${album.id}`}
      className="sq-card"
      style={tint}
      aria-label={album.title}
    >
      <div className="cover">
        <div className="keyart-mini" />
        {album.cover_path ? (
          <img
            src={album.cover_path}
            alt={album.title}
            loading="lazy"
            decoding="async"
            className="real-art"
          />
        ) : null}
        <div className="play-spot" aria-hidden>
          <span className="tri" />
        </div>
        <AlbumTileMenu albumId={album.id} albumTitle={album.title} />
        {isAdmin && onEdit ? (
          <button
            type="button"
            className="admin-edit"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onEdit();
            }}
            aria-label={`Edit ${album.title}`}
          >
            Edit
          </button>
        ) : null}
      </div>
      <div className="info">
        <div className="t">{album.title}</div>
        {sub ? (
          <div className="s">
            {artistHref ? (
              <button
                type="button"
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); router.push(artistHref); }}
                style={{ background: "none", border: "none", padding: 0, color: "inherit", font: "inherit", cursor: "pointer", textDecoration: "none" }}
                onMouseEnter={e => (e.currentTarget.style.textDecoration = "underline")}
                onMouseLeave={e => (e.currentTarget.style.textDecoration = "none")}
              >
                {sub}
              </button>
            ) : sub}
          </div>
        ) : null}
      </div>
    </Link>
  );
}
