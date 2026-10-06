// Music videos release detail. Hero block matches the album detail page,
// with a 16:9 video grid below. When the release has more than one disc
// the videos are grouped under DISC NN headings.
//
// Admin Edit affordance is now release-scoped: clicking Edit opens the
// unified Edit Overrides modal for the release entity. Per-video thumb
// edit is paused this round; a follow-up handoff will surface that
// affordance again without remounting ArtOverrideModal at the page level.

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import Link from "next/link";
import { notFound, useParams } from "next/navigation";
import EditOverridesModal, {
  algorithmicSortHint,
} from "@/components/EditOverridesModal";
import { AuthShell } from "@/components/AuthShell";
import { BackButton } from "@/components/BackButton";
import { Grid, GridEmpty } from "@/components/Grid";
import { apiGet, ApiError } from "@/lib/client-api";
import { loadOverride } from "@/lib/overrides";
import {
  colorForTitle,
  formatDuration,
  hueFromString,
  joinMeta,
} from "@/lib/format";
import type {
  MusicVideo,
  MusicVideoReleaseDetail,
  OverrideOut,
} from "@/lib/types";

type EditInitial = OverrideOut & { algorithmic_sort_hint: string };

export default function MusicVideoReleasePage() {
  const params = useParams<{ artistId: string; releaseId: string }>();
  const artistId = params?.artistId;
  const releaseId = params?.releaseId;
  const [data, setData] = useState<MusicVideoReleaseDetail | null>(null);
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
    if (!releaseId) return;
    let cancelled = false;
    (async () => {
      try {
        const d = await apiGet<MusicVideoReleaseDetail>(
          `/api/library/music-videos/releases/${releaseId}`,
        );
        if (!cancelled) setData(d);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setMissing(true);
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load release");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [releaseId, reloadTick]);

  const onApplied = useCallback(() => setReloadTick((t) => t + 1), []);

  const openEdit = useCallback(async () => {
    if (!data) return;
    setEditLoading(true);
    setEditError(null);
    try {
      // apiGet refreshes an expired session once and retries; anything
      // still failing is shown next to the button instead of nothing.
      const res = await loadOverride<OverrideOut>(apiGet, "music_video_release", data.id);
      if (!res.ok) {
        setEditError(res.error);
        return;
      }
      setEditInitial({
        ...res.data,
        algorithmic_sort_hint: algorithmicSortHint(data.title),
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
        <ReleaseSkeleton />
      ) : (
        <ReleaseHero
          detail={data}
          artistId={artistId ?? ""}
          isAdmin={isAdmin}
          onEdit={openEdit}
          editBusy={editLoading}
          editError={editError}
        />
      )}
      {editInitial && data ? (
        <EditOverridesModal
          open
          kind="music_video_release"
          entityId={data.id}
          initial={editInitial}
          onClose={() => setEditInitial(null)}
          onApplied={onApplied}
        />
      ) : null}
    </AuthShell>
  );
}

function ReleaseHero({
  detail,
  artistId,
  isAdmin,
  onEdit,
  editBusy,
  editError,
}: {
  detail: MusicVideoReleaseDetail;
  artistId: string;
  isAdmin: boolean;
  onEdit: () => void;
  editBusy: boolean;
  editError: string | null;
}) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(detail.title),
    ["--ph" as never]: String(hueFromString(detail.title)),
  };
  const meta = joinMeta([
    detail.release_year ?? null,
    detail.video_count
      ? `${detail.video_count} ${detail.video_count === 1 ? "video" : "videos"}`
      : null,
    detail.disc_count > 1
      ? `${detail.disc_count} discs`
      : null,
  ]);
  const groupedByDisc = useMemo(() => {
    const buckets = new Map<number, MusicVideo[]>();
    for (const v of detail.videos) {
      const list = buckets.get(v.disc_number) ?? [];
      list.push(v);
      buckets.set(v.disc_number, list);
    }
    return [...buckets.entries()].sort(([a], [b]) => a - b);
  }, [detail.videos]);

  return (
    <section className="detail" style={tint}>
      <div className="backdrop" />
      <div className="body">
        <BackButton href={`/music-videos/${artistId}`} />
        <div className="poster-card album">
          <div className="keyart-mini" />
          {detail.cover_path ? (
            <img className="real-art" src={detail.cover_path} alt={detail.title} />
          ) : null}
        </div>
        <div className="info">
          <div className="kicker">
            {isAdmin ? (
              <button
                type="button"
                onClick={onEdit}
                disabled={editBusy}
                className="admin-edit"
                style={{ position: "static", opacity: 1, marginLeft: "auto" }}
                aria-label="Edit release metadata"
              >
                {editBusy ? "Loading..." : "Edit"}
              </button>
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
          <h1>{detail.title}</h1>
          <div className="meta" style={{ color: "var(--ink-2)" }}>
            {artistId ? (
              <Link href={`/music-videos/${artistId}`} style={{ color: "inherit", textDecoration: "none" }}
                onMouseEnter={e => (e.currentTarget.style.textDecoration = "underline")}
                onMouseLeave={e => (e.currentTarget.style.textDecoration = "none")}
              >{detail.artist_name}</Link>
            ) : <span>{detail.artist_name}</span>}
          </div>
          {meta ? <MetaRow text={meta} /> : null}

          <div
            className="tracks"
            style={{ marginTop: 28, paddingTop: 28, borderTop: "1px solid var(--line)" }}
          >
            {detail.videos.length === 0 ? (
              <GridEmpty message="No videos on disk yet." />
            ) : detail.disc_count > 1 ? (
              groupedByDisc.map(([disc, videos]) => (
                <div key={disc} style={{ marginBottom: 32 }}>
                  <h3
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: 11,
                      letterSpacing: "0.18em",
                      textTransform: "uppercase",
                      color: "var(--ink-3)",
                      margin: "0 0 12px",
                    }}
                  >
                    {`Disc ${String(disc).padStart(2, "0")}`}
                  </h3>
                  <Grid>
                    {videos.map((v) => (
                      <VideoTile key={v.id} video={v} />
                    ))}
                  </Grid>
                </div>
              ))
            ) : (
              <Grid>
                {detail.videos.map((v) => (
                  <VideoTile key={v.id} video={v} />
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

function VideoTile({ video }: { video: MusicVideo }) {
  const playable = Boolean(video.media_file_id);
  const subtitle = joinMeta([video.year, formatDuration(video.duration_sec)]);
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(video.title),
    ["--ph" as never]: String(hueFromString(video.title)),
  };

  const inner = (
    <>
      <div
        className="frame"
        style={{ aspectRatio: "16/9", borderRadius: 6 }}
      >
        <div className="keyart-mini" />
        {video.thumb_path ? (
          <img
            src={video.thumb_path}
            alt={video.title}
            loading="lazy"
            decoding="async"
            className="real-art"
          />
        ) : null}
        {!playable ? (
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: "var(--scrim)",
              display: "grid",
              placeItems: "center",
              fontFamily: "var(--mono)",
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--ink-2)",
              zIndex: 3,
            }}
          >
            Not on disk
          </div>
        ) : null}
      </div>
      <div className="info">
        <div className="t">{video.title}</div>
        {subtitle ? <div className="s">{subtitle}</div> : null}
      </div>
    </>
  );

  return playable ? (
    <Link
      href={`/watch/${video.media_file_id}`}
      className="poster"
      style={{ ...tint, width: "auto" }}
      aria-label={video.title}
    >
      {inner}
    </Link>
  ) : (
    <div
      className="poster"
      style={{ ...tint, width: "auto", opacity: 0.6, cursor: "default" }}
      aria-label={video.title}
    >
      {inner}
    </div>
  );
}

function ReleaseSkeleton() {
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
