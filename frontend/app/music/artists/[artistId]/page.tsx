// Music artist detail. Hero with the display name,
// origin line, About panel (Wikipedia bio), links chips, Shuffle artist
// + Start radio actions, and a 1:1 album grid below. Existing admin
// thumb-edit affordance for the artist tile preserved.

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { notFound, useParams, useRouter } from "next/navigation";
import EditOverridesModal, {
  algorithmicSortHint,
} from "@/components/EditOverridesModal";
import { ArtistMergeDialog } from "@/components/ArtistMergeDialog";
import { AuthShell } from "@/components/AuthShell";
import { BackButton } from "@/components/BackButton";
import { AlbumTileMenu } from "@/components/AlbumTileMenu";
import { Grid, GridEmpty } from "@/components/Grid";
import { MediaCard } from "@/components/MediaCard";
import { apiGet, apiPost, ApiError } from "@/lib/client-api";
import { loadOverride } from "@/lib/overrides";
import {
  colorForTitle,
  hueFromString,
  joinMeta,
} from "@/lib/format";
import { countryName } from "@/lib/iso-country";
import { albumToQueueItems, useQueue, type QueueItem } from "@/lib/queue";
import type { Album, AlbumDetail, MusicArtistDetail, OverrideOut } from "@/lib/types";

type EditInitial = OverrideOut & { algorithmic_sort_hint: string };

const BIO_WORD_LIMIT = 200;

export default function MusicArtistPage() {
  const params = useParams<{ artistId: string }>();
  const router = useRouter();
  const artistId = params?.artistId;
  const [data, setData] = useState<MusicArtistDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const [editInitial, setEditInitial] = useState<EditInitial | null>(null);
  const [editLoading, setEditLoading] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

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
    if (!artistId) return;
    let cancelled = false;
    (async () => {
      try {
        const d = await apiGet<MusicArtistDetail>(
          `/api/library/artists/${artistId}`,
        );
        if (!cancelled) setData(d);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setMissing(true);
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load artist");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [artistId, reloadTick]);

  const onApplied = useCallback(() => setReloadTick((t) => t + 1), []);

  const openEdit = useCallback(async () => {
    if (!data) return;
    setEditLoading(true);
    setEditError(null);
    try {
      // apiGet refreshes an expired session once and retries; anything
      // still failing is shown next to the button instead of nothing.
      const res = await loadOverride<OverrideOut>(apiGet, "artist", data.id);
      if (!res.ok) {
        setEditError(res.error);
        return;
      }
      setEditInitial({
        ...res.data,
        algorithmic_sort_hint: algorithmicSortHint(data.name),
      });
    } finally {
      setEditLoading(false);
    }
  }, [data]);

  if (missing) notFound();

  return (
    <AuthShell>
      {error ? (
        <div
          style={{
            margin: "16px 64px",
            padding: "12px 16px",
            border: "1px solid var(--danger)",
            borderRadius: 4,
            color: "var(--danger)",
            fontFamily: "var(--mono)",
            fontSize: 12,
          }}
        >
          {error}
        </div>
      ) : data === null ? (
        <ArtistSkeleton />
      ) : (
        <ArtistHero
          detail={data}
          isAdmin={isAdmin}
          onEdit={openEdit}
          editBusy={editLoading}
          editError={editError}
          onMerged={() => router.push("/music")}
          onUndone={onApplied}
        />
      )}
      {editInitial && data ? (
        <EditOverridesModal
          open
          kind="artist"
          entityId={data.id}
          initial={editInitial}
          onClose={() => setEditInitial(null)}
          onApplied={onApplied}
        />
      ) : null}
    </AuthShell>
  );
}

function ArtistHero({
  detail,
  isAdmin,
  onEdit,
  editBusy,
  editError,
  onMerged,
  onUndone,
}: {
  detail: MusicArtistDetail;
  isAdmin: boolean;
  onEdit: () => void;
  editBusy: boolean;
  editError: string | null;
  // After a merge the source artist is gone, so the caller navigates away.
  onMerged: () => void;
  // After an undo the restored artist exists again; the caller reloads.
  onUndone: () => void;
}) {
  const [mergeOpen, setMergeOpen] = useState(false);
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(detail.name),
    ["--ph" as never]: String(hueFromString(detail.name)),
  };
  const originLine = formatOriginLine(detail);
  const meta = joinMeta([
    detail.artist_type,
    detail.album_count
      ? `${detail.album_count} ${detail.album_count === 1 ? "album" : "albums"}`
      : null,
  ]);
  return (
    <section className="detail" style={tint}>
      <div className="backdrop" />
      <div className="body">
        <BackButton href="/music" />
        <div className="poster-card album">
          <div className="keyart-mini" />
          {detail.image_path ? (
            <img className="real-art" src={detail.image_path} alt={detail.name} />
          ) : null}
        </div>
        <div className="info">
          <div className="kicker">
            {isAdmin ? (
              <>
                <button
                  type="button"
                  onClick={onEdit}
                  disabled={editBusy}
                  className="admin-edit"
                  style={{ position: "static", opacity: 1, marginLeft: "auto" }}
                  aria-label="Edit artist metadata"
                >
                  {editBusy ? "Loading..." : "Edit"}
                </button>
                <button
                  type="button"
                  onClick={() => setMergeOpen(true)}
                  className="admin-edit"
                  style={{ position: "static", opacity: 1, marginLeft: 8 }}
                  aria-label="Merge this artist into another"
                >
                  Merge into...
                </button>
              </>
            ) : null}
            {isAdmin && editError ? (
              <span
                role="alert"
                style={{ color: "var(--danger)", fontFamily: "var(--mono)", fontSize: 12, marginLeft: 8 }}
              >
                {editError}
              </span>
            ) : null}
          </div>
          <h1>{detail.name}</h1>
          {isAdmin ? (
            <UndoMergePanel artistId={detail.id} onUndone={onUndone} />
          ) : null}
          {mergeOpen ? (
            <ArtistMergeDialog
              sourceId={detail.id}
              sourceName={detail.name}
              onClose={() => setMergeOpen(false)}
              onMerged={() => {
                setMergeOpen(false);
                onMerged();
              }}
            />
          ) : null}
          {meta ? <MetaRow text={meta} /> : null}
          {originLine ? <div className="origin-line">{originLine}</div> : null}
          <ArtistMixActions artistId={detail.id} />
          <AboutPanel bioText={detail.bio_text} bioSource={detail.bio_source} />


          <div
            className="tracks"
            style={{ marginTop: 28, paddingTop: 28, borderTop: "1px solid var(--line)" }}
          >
            <h3>Discography</h3>
            {detail.albums.length === 0 ? (
              <GridEmpty message="No albums on file for this artist." />
            ) : (
              <Grid>
                {detail.albums.map((a) => (
                  <DiscoTile key={a.id} album={a} />
                ))}
              </Grid>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function MetaRow({ text }: { text: string }) {
  return (
    <div className="meta">
      {text.split(" • ").map((part, i, arr) => (
        <span key={i}>
          {part}
          {i < arr.length - 1 ? <span aria-hidden style={{ margin: "0 0", color: "var(--ink-3)" }}>•</span> : null}
        </span>
      ))}
    </div>
  );
}

function formatOriginLine(detail: MusicArtistDetail): string | null {
  const parts: string[] = [];
  const country = countryName(detail.country);
  if (country) parts.push(country);
  if (detail.formed_year) parts.push(`Formed ${detail.formed_year}`);
  if (detail.disbanded_year) parts.push(`Disbanded ${detail.disbanded_year}`);
  return parts.length ? parts.join(" • ") : null;
}

function AboutPanel({
  bioText,
  bioSource,
}: {
  bioText: string | null;
  bioSource: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!bioText) return null;
  const words = bioText.split(/\s+/);
  const truncated = words.length > BIO_WORD_LIMIT;
  const visible =
    expanded || !truncated
      ? bioText
      : words.slice(0, BIO_WORD_LIMIT).join(" ") + "…";
  return (
    <section
      style={{
        marginTop: 28,
        paddingTop: 28,
        borderTop: "1px solid var(--line-soft)",
      }}
    >
      <h4
        style={{
          fontFamily: "var(--mono)",
          fontSize: 10,
          letterSpacing: "0.24em",
          textTransform: "uppercase",
          color: "var(--hive-text)",
          margin: "0 0 14px",
        }}
      >
        About
      </h4>
      <p
        className="blurb"
        style={{
          whiteSpace: "pre-line",
          maxWidth: "70ch",
          marginBottom: 12,
        }}
      >
        {visible}
      </p>
      {truncated ? (
        <button
          type="button"
          className="read-more"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Show less ←" : "Read more →"}
        </button>
      ) : null}
      {bioSource && bioSource !== "none" ? (
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10,
            letterSpacing: "0.16em",
            color: "var(--ink-4)",
            marginTop: 8,
          }}
        >
          Source: {bioSource === "wikipedia" ? "Wikipedia" : bioSource}
        </div>
      ) : null}
    </section>
  );
}

function ArtistMixActions({ artistId }: { artistId: string }) {
  const { playAlbum } = useQueue();
  const [busy, setBusy] = useState<"shuffle" | "radio" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchAndPlay = useCallback(
    async (mode: "shuffle" | "radio") => {
      const path =
        mode === "shuffle"
          ? `/api/library/auto-playlist/by-artist/${encodeURIComponent(artistId)}?limit=100`
          : `/api/library/auto-playlist/artist-radio/${encodeURIComponent(artistId)}?limit=100`;
      setBusy(mode);
      setError(null);
      try {
        const data = await apiGet<{ items: QueueItem[] }>(path);
        if (!Array.isArray(data?.items) || data.items.length === 0) {
          setError("Nothing playable for this artist.");
          return;
        }
        playAlbum(data.items, { shuffle: false });
      } catch (err) {
        setError(
          err instanceof ApiError
            ? `Failed (${err.status}).`
            : err instanceof Error
              ? err.message
              : "Failed",
        );
      } finally {
        setBusy(null);
      }
    },
    [artistId, playAlbum],
  );

  return (
    <div className="ctas" style={{ marginTop: 12 }}>
      <button
        type="button"
        className="btn play"
        disabled={busy !== null}
        onClick={() => fetchAndPlay("shuffle")}
      >
        <span className="tri" />
        {busy === "shuffle" ? "..." : "Shuffle Artist"}
      </button>
      <button
        type="button"
        className="btn ghost"
        disabled={busy !== null}
        onClick={() => fetchAndPlay("radio")}
      >
        {busy === "radio" ? "..." : "Artist radio"}
      </button>
      {error ? (
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            color: "var(--danger)",
          }}
        >
          {error}
        </span>
      ) : null}
    </div>
  );
}

// Admin-only. Lists the artists that were merged into this one and offers an
// Undo for each, which removes the alias and restores the source artist with
// the albums and tracks that moved.
function UndoMergePanel({
  artistId,
  onUndone,
}: {
  artistId: string;
  onUndone: () => void;
}) {
  type MergeRow = { merge_id: string; source_name: string; albums: number };
  const [merges, setMerges] = useState<MergeRow[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await apiGet<MergeRow[]>(
          `/api/admin/artists/${encodeURIComponent(artistId)}/merges`,
        );
        if (!cancelled) setMerges(rows);
      } catch {
        if (!cancelled) setMerges([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [artistId]);

  async function undo(mergeId: string) {
    setBusy(mergeId);
    setError(null);
    try {
      await apiPost(`/api/admin/artists/merges/${encodeURIComponent(mergeId)}/undo`, {});
      setMerges((rows) => (rows ? rows.filter((r) => r.merge_id !== mergeId) : rows));
      onUndone();
    } catch (err) {
      setError(
        err instanceof ApiError ? `Undo failed (${err.status}).` : "Undo failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  if (!merges || merges.length === 0) return null;
  return (
    <div
      style={{
        marginTop: 12,
        fontFamily: "var(--grotesk)",
        fontSize: 13,
        color: "var(--ink-2)",
      }}
    >
      <div style={{ marginBottom: 6 }}>Merged in:</div>
      {merges.map((m) => (
        <div
          key={m.merge_id}
          style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}
        >
          <span>
            {m.source_name} ({m.albums} {m.albums === 1 ? "album" : "albums"})
          </span>
          <button
            type="button"
            className="admin-edit"
            style={{ position: "static", opacity: 1 }}
            disabled={busy === m.merge_id}
            onClick={() => undo(m.merge_id)}
          >
            {busy === m.merge_id ? "Undoing..." : "Undo merge"}
          </button>
        </div>
      ))}
      {error ? (
        <span style={{ color: "var(--danger)", fontFamily: "var(--mono)", fontSize: 12 }}>
          {error}
        </span>
      ) : null}
    </div>
  );
}

// A single discography tile: the standard album MediaCard plus a hover
// play button that resolves the album detail and replaces the queue,
// and the shared tile context menu (Play next / Shuffle / Add all).
function DiscoTile({ album }: { album: Album }) {
  const { playAlbum } = useQueue();

  async function onPlay() {
    try {
      const detail = await apiGet<AlbumDetail>(`/api/library/albums/${album.id}`);
      const items = albumToQueueItems(detail);
      if (items.length > 0) playAlbum(items);
    } catch {
      // best-effort; nothing to play if the detail fetch fails
    }
  }

  return (
    <MediaCard
      href={`/music/${album.id}`}
      title={album.title}
      subtitle={
        album.release_date
          ? String(new Date(album.release_date).getUTCFullYear())
          : null
      }
      posterPath={album.cover_path}
      kind="album"
      onPlay={onPlay}
      overlay={<AlbumTileMenu albumId={album.id} albumTitle={album.title} />}
    />
  );
}

function ArtistSkeleton() {
  return (
    <section className="detail">
      <div className="backdrop" />
      <div className="body">
        <div
          className="poster-card album"
          style={{ background: "var(--surface-2)" }}
        />
        <div className="info">
          <div className="kicker">Loading…</div>
        </div>
      </div>
    </section>
  );
}
