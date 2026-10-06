// Music videos artist detail. Hero block matches the music-artist page,
// with a 1:1 release-tile grid below (mirroring albums on the music page).
// Each tile links to the release detail page where the videos live.

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { notFound, useParams } from "next/navigation";
import { ArtOverrideModal, ArtKind, ArtRole } from "@/components/ArtOverrideModal";
import { AuthShell } from "@/components/AuthShell";
import { BackButton } from "@/components/BackButton";
import { Grid, GridEmpty } from "@/components/Grid";
import { MediaCard } from "@/components/MediaCard";
import { apiGet, ApiError } from "@/lib/client-api";
import {
  colorForTitle,
  hueFromString,
  joinMeta,
} from "@/lib/format";
import type {
  MusicVideoArtistDetail,
  MusicVideoRelease,
} from "@/lib/types";

export default function MusicVideoArtistPage() {
  const params = useParams<{ artistId: string }>();
  const artistId = params?.artistId;
  const [data, setData] = useState<MusicVideoArtistDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const [modal, setModal] = useState<{
    kind: ArtKind;
    role: ArtRole;
    id: string;
    title: string;
    hasOverride: boolean;
  } | null>(null);

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
        const d = await apiGet<MusicVideoArtistDetail>(
          `/api/library/music-videos/artists/${artistId}`,
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
          openModal={(m) => setModal(m)}
        />
      )}
      {modal ? (
        <ArtOverrideModal
          open
          entityKind={modal.kind}
          entityId={modal.id}
          role={modal.role}
          title={modal.title}
          hasOverride={modal.hasOverride}
          onClose={() => setModal(null)}
          onApplied={onApplied}
        />
      ) : null}
    </AuthShell>
  );
}

type ModalSpec = {
  kind: ArtKind;
  role: ArtRole;
  id: string;
  title: string;
  hasOverride: boolean;
};

function ArtistHero({
  detail,
  isAdmin,
  openModal,
}: {
  detail: MusicVideoArtistDetail;
  isAdmin: boolean;
  openModal: (m: ModalSpec) => void;
}) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(detail.name),
    ["--ph" as never]: String(hueFromString(detail.name)),
  };
  const releases = useMemo(() => detail.releases ?? [], [detail.releases]);
  const meta = joinMeta([
    releases.length
      ? `${releases.length} ${releases.length === 1 ? "release" : "releases"}`
      : null,
    detail.video_count
      ? `${detail.video_count} ${detail.video_count === 1 ? "video" : "videos"}`
      : null,
  ]);

  return (
    <section className="detail" style={tint}>
      <div className="backdrop" />
      <div className="body">
        <BackButton href="/music-videos" />
        <div className="poster-card album">
          <div className="keyart-mini" />
          {detail.image_path ? (
            <img className="real-art" src={detail.image_path} alt={detail.name} />
          ) : null}
          {isAdmin ? (
            <button
              type="button"
              className="admin-edit"
              onClick={() =>
                openModal({
                  kind: "artist",
                  role: "thumb",
                  id: detail.id,
                  title: detail.name,
                  hasOverride: Boolean(
                    detail.image_path?.startsWith("/api/art/"),
                  ),
                })
              }
              aria-label="Edit artist image"
            >
              Edit Thumb
            </button>
          ) : null}
        </div>
        <div className="info">
          <h1>{detail.name}</h1>
          {meta ? <MetaRow text={meta} /> : null}

          <div
            className="tracks"
            style={{ marginTop: 28, paddingTop: 28, borderTop: "1px solid var(--line)" }}
          >
            <h3>Releases</h3>
            {releases.length === 0 ? (
              <GridEmpty message="No releases on disk yet." />
            ) : (
              <Grid variant="square">
                {releases.map((r) => (
                  <ReleaseTile
                    key={r.id}
                    artistId={detail.id}
                    release={r}
                  />
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

function ReleaseTile({
  artistId,
  release,
}: {
  artistId: string;
  release: MusicVideoRelease;
}) {
  const subtitle = joinMeta([
    release.release_year ?? null,
    release.video_count
      ? `${release.video_count} ${release.video_count === 1 ? "video" : "videos"}`
      : null,
  ]);
  return (
    <MediaCard
      href={`/music-videos/${artistId}/${release.id}`}
      title={release.title}
      subtitle={subtitle ?? null}
      posterPath={release.cover_path}
      kind="music_video_release"
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
