// Album detail. Hero with the display title, meta
// row (artist · year · type), tagline-style disambiguation, primary Play
// album + Shuffle + Add-to-queue actions, links chips, technical metadata
// for the first track's file, and the full track list.

"use client";

import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import Link from "next/link";
import { notFound, useParams } from "next/navigation";
import { AuthShell } from "@/components/AuthShell";
import { BackButton } from "@/components/BackButton";
import { apiGet, ApiError } from "@/lib/client-api";
import {
  colorForTitle,
  formatDuration,
  hueFromString,
  joinMeta,
} from "@/lib/format";
import {
  albumToQueueItems,
  trackToQueueItem,
  useQueue,
  type QueueItem,
} from "@/lib/queue";
import type { AlbumDetail, Track } from "@/lib/types";

type DiscGroup = { disc: number; tracks: Track[] };

export default function AlbumDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [album, setAlbum] = useState<AlbumDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<AlbumDetail>(`/api/library/albums/${id}`);
        if (!cancelled) setAlbum(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setMissing(true);
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load album");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

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
      ) : album === null ? (
        <AlbumSkeleton />
      ) : (
        <AlbumHero album={album} />
      )}
    </AuthShell>
  );
}

function AlbumHero({ album }: { album: AlbumDetail }) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(album.title),
    ["--ph" as never]: String(hueFromString(album.title)),
  };
  const year = album.release_date ? album.release_date.slice(0, 4) : null;
  const groups = useMemo(() => groupByDisc(album.tracks), [album.tracks]);
  const queueItems = useMemo(() => albumToQueueItems(album), [album]);
  const { playAlbum, addToQueue } = useQueue();

  const meta = joinMeta([
    year,
    album.album_type ?? "Album",
    album.tracks.length ? `${album.tracks.length} tracks` : null,
    album.mb_rating != null ? `★ ${album.mb_rating.toFixed(1)}` : null,
  ]);
  const playableCount = queueItems.length;

  return (
    <section className="detail" style={tint}>
      <div className="backdrop" />
      <div className="body">
        <BackButton href="/music" />
        <div className="poster-card album">
          <div className="keyart-mini" />
          {album.cover_path ? (
            <img className="real-art" src={album.cover_path} alt={album.title} />
          ) : null}
        </div>
        <div className="info">
          {album.album_type ? (
            <div className="type-badge">{album.album_type}</div>
          ) : null}
          <h1>{album.title}</h1>
          {album.artist_name ? (
            <div className="artist-link-row">
              {album.artist_id ? (
                <Link
                  href={`/music/artists/${album.artist_id}`}
                  style={{ color: "var(--ink-2)", textDecoration: "none" }}
                  onMouseEnter={e => (e.currentTarget.style.textDecoration = "underline")}
                  onMouseLeave={e => (e.currentTarget.style.textDecoration = "none")}
                >
                  {album.artist_name}
                </Link>
              ) : <span>{album.artist_name}</span>}
            </div>
          ) : null}
          {album.disambiguation ? (
            <div className="disambiguation">{album.disambiguation}</div>
          ) : null}
          {meta ? <MetaRow text={meta} /> : null}
          {album.label ? (
            <div className="origin-line">Released by {album.label}</div>
          ) : null}
          <div className="ctas">
            {playableCount > 0 ? (
              <>
                <button
                  type="button"
                  className="btn play"
                  onClick={() => playAlbum(queueItems, { shuffle: false })}
                >
                  <span className="tri" /> Play
                </button>
                <button
                  type="button"
                  className="btn ghost"
                  onClick={() => playAlbum(queueItems, { shuffle: true })}
                >
                  Shuffle
                </button>
                <button
                  type="button"
                  className="btn ghost"
                  onClick={() => addToQueue(queueItems)}
                >
                  + Queue
                </button>
              </>
            ) : (
              <button type="button" className="btn play" disabled>
                Not on disk
              </button>
            )}
          </div>

          <div className="tracks">
            <h3>Tracks</h3>
            {groups.length === 0 ? (
              <div
                style={{
                  padding: 12,
                  fontFamily: "var(--mono)",
                  fontSize: 12,
                  color: "var(--ink-3)",
                }}
              >
                No tracks on disk yet.
              </div>
            ) : (
              groups.map((g) => (
                <DiscSection
                  key={g.disc}
                  album={album}
                  group={g}
                  showHeading={groups.length > 1}
                />
              ))
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
        <span key={i} className={part.startsWith("★") ? "stars" : undefined}>
          {part}
          {i < arr.length - 1 ? <span aria-hidden style={{ margin: "0 0", color: "var(--ink-3)" }}>•</span> : null}
        </span>
      ))}
    </div>
  );
}

function DiscSection({
  album,
  group,
  showHeading,
}: {
  album: AlbumDetail;
  group: DiscGroup;
  showHeading: boolean;
}) {
  return (
    <div>
      {showHeading ? (
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--ink-3)",
            margin: "16px 0 8px",
          }}
        >
          Disc {group.disc}
        </div>
      ) : null}
      {group.tracks.map((t, i) => (
        <TrackRow key={t.id} album={album} track={t} index={i} />
      ))}
    </div>
  );
}

function TrackRow({
  album,
  track,
  index,
}: {
  album: AlbumDetail;
  track: Track;
  index: number;
}) {
  const primary = track.media_files[0];
  const number = track.track_number ?? index + 1;
  const duration = formatDuration(track.duration_sec);
  const { playNow } = useQueue();
  const queueItem: QueueItem | null = useMemo(
    () => trackToQueueItem(track, album),
    [track, album],
  );

  function onPlay() {
    if (queueItem) playNow(queueItem);
  }

  return (
    <button
      type="button"
      className="track"
      onClick={primary ? onPlay : undefined}
      disabled={!primary}
      style={{
        width: "100%",
        textAlign: "left",
        cursor: primary ? "pointer" : "default",
      }}
    >
      <div className="num">{String(number).padStart(2, "0")}</div>
      <div className="body">
        <div className="t">{track.title}</div>
      </div>
      <div className="right">
        <div>{duration || "—"}</div>
      </div>
    </button>
  );
}

function groupByDisc(tracks: Track[]): DiscGroup[] {
  const by = new Map<number, Track[]>();
  for (const t of tracks) {
    const disc = t.disc_number ?? 1;
    const arr = by.get(disc);
    if (arr) arr.push(t);
    else by.set(disc, [t]);
  }
  const out: DiscGroup[] = [];
  for (const [disc, arr] of by.entries()) {
    arr.sort((a, b) => (a.track_number ?? 0) - (b.track_number ?? 0));
    out.push({ disc, tracks: arr });
  }
  out.sort((a, b) => a.disc - b.disc);
  return out;
}

function AlbumSkeleton() {
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
