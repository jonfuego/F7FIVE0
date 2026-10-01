// Movie detail. Full-bleed item-color hero, Bebas title, meta row,
// description, primary Play + secondary actions, cast row, directors
// line, technical metadata block in mono.

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import Link from "next/link";
import { notFound, useParams } from "next/navigation";
import EditOverridesModal, {
  algorithmicSortHint,
} from "@/components/EditOverridesModal";
import { AuthShell } from "@/components/AuthShell";
import { Backdrop } from "@/components/Backdrop";
import { MarkWatchedButton } from "@/components/MarkWatchedButton";
import { apiGet, ApiError } from "@/lib/client-api";
import {
  colorForTitle,
  formatBytes,
  formatRuntime,
  hueFromString,
  joinMeta,
} from "@/lib/format";
import { useProgressMap } from "@/lib/progress";
import type { CastMember, MediaFile, MovieDetail, OverrideOut } from "@/lib/types";

const TMDB_PROFILE_BASE = "https://image.tmdb.org/t/p/w185";
const CAST_LIMIT = 8;

type EditInitial = OverrideOut & { algorithmic_sort_hint: string };

export default function MovieDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [movie, setMovie] = useState<MovieDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const [editInitial, setEditInitial] = useState<EditInitial | null>(null);
  const [editLoading, setEditLoading] = useState(false);

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
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<MovieDetail>(`/api/library/movies/${id}`);
        if (!cancelled) setMovie(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setMissing(true);
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load movie");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, reloadTick]);

  const onApplied = useCallback(() => setReloadTick((t) => t + 1), []);

  const openEdit = useCallback(async () => {
    if (!movie) return;
    setEditLoading(true);
    try {
      const res = await fetch(`/api/admin/override/movie/${movie.id}`, {
        cache: "no-store",
      });
      if (!res.ok) return;
      const body = (await res.json()) as OverrideOut;
      setEditInitial({
        ...body,
        algorithmic_sort_hint: algorithmicSortHint(movie.title),
      });
    } finally {
      setEditLoading(false);
    }
  }, [movie]);

  if (missing) notFound();

  return (
    <AuthShell>
      {error ? (
        <div
          style={{
            margin: "16px 64px",
            padding: "12px 16px",
            border: "1px solid oklch(0.40 0.20 25 / 0.4)",
            borderRadius: 4,
            color: "oklch(0.85 0.10 25)",
            fontFamily: "var(--mono)",
            fontSize: 12,
          }}
        >
          {error}
        </div>
      ) : movie === null ? (
        <DetailSkeleton />
      ) : (
        <MovieHero
          movie={movie}
          isAdmin={isAdmin}
          onEdit={openEdit}
          editBusy={editLoading}
        />
      )}
      {editInitial && movie ? (
        <EditOverridesModal
          open
          kind="movie"
          entityId={movie.id}
          initial={editInitial}
          onClose={() => setEditInitial(null)}
          onApplied={onApplied}
        />
      ) : null}
    </AuthShell>
  );
}

function MovieHero({
  movie,
  isAdmin,
  onEdit,
  editBusy,
}: {
  movie: MovieDetail;
  isAdmin: boolean;
  onEdit: () => void;
  editBusy: boolean;
}) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(movie.title),
    ["--ph" as never]: String(hueFromString(movie.title)),
  };
  const runtime = formatRuntime(movie.runtime_min);
  const rating =
    movie.tmdb_rating != null
      ? `★ ${movie.tmdb_rating.toFixed(1)}`
      : null;
  const meta = joinMeta([movie.year, runtime, rating]);
  const primary = movie.media_files[0] ?? null;
  const playHref = primary ? `/watch/${primary.id}` : null;
  const sortedCast = useMemo(
    () =>
      [...(movie.cast ?? [])]
        .sort((a, b) => (a.order ?? 999) - (b.order ?? 999))
        .slice(0, CAST_LIMIT),
    [movie.cast],
  );
  const directors = (movie.directors ?? [])
    .map((d) => d.name)
    .filter((n): n is string => Boolean(n));

  return (
    <section className="detail" style={tint}>
      <div className="backdrop">
        <Backdrop src={movie.backdrop_path} alt="" />
      </div>
      <div className="body">
        <div className="poster-card">
          <div className="keyart-mini" />
          {movie.poster_path ? (
            <img className="real-art" src={movie.poster_path} alt={movie.title} />
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
                aria-label="Edit movie metadata"
              >
                {editBusy ? "Loading..." : "Edit"}
              </button>
            ) : null}
          </div>
          <h1>{movie.title}</h1>
          {movie.tagline ? <div className="tagline">{movie.tagline}</div> : null}
          {meta ? <MetaRow text={meta} /> : null}
          {movie.overview ? <Blurb text={movie.overview} /> : null}
          <div className="ctas">
            {playHref ? (
              <Link className="btn play" href={playHref}>
                <span className="tri" /> Play
              </Link>
            ) : (
              <button type="button" className="btn play" disabled>
                Not on disk
              </button>
            )}
            {primary ? (
              <FileWatchedButton fileId={primary.id} />
            ) : null}
            <Link className="btn ghost" href="/movies">
              ← Back
            </Link>
          </div>
          {directors.length ? (
            <div className="credit-line">
              <b>Directed by</b> {directors.join(", ")}
            </div>
          ) : null}
          {sortedCast.length ? <CastRow cast={sortedCast} /> : null}

          {primary ? <TechnicalCard file={primary} /> : null}
          <ActivityCard file={primary} />
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

function Blurb({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const words = text.split(/\s+/);
  const truncated = words.length > 80;
  const visible = expanded || !truncated ? text : words.slice(0, 80).join(" ") + "…";
  return (
    <>
      <p className="blurb">{visible}</p>
      {truncated ? (
        <button
          type="button"
          className="read-more"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Show less ←" : "Read more →"}
        </button>
      ) : null}
    </>
  );
}

function CastRow({ cast }: { cast: CastMember[] }) {
  return (
    <div className="cast-row">
      {cast.map((c, i) => (
        <span key={`${c.name ?? "?"}-${i}`} className="person">
          <b>{c.name ?? "—"}</b>
          {c.character ? <> · <span>{c.character}</span></> : null}
        </span>
      ))}
    </div>
  );
}

function TechnicalCard({ file }: { file: MediaFile }) {
  return (
    <div className="cards font-mono">
      <div className="card">
        <h4>File Information</h4>
        <div className="row"><span>Codec</span><span>{file.video_codec?.toUpperCase() ?? "—"}</span></div>
        <div className="row"><span>Bitrate</span><span>{file.bitrate_kbps ? `${(file.bitrate_kbps / 1000).toFixed(1)} Mbps` : "—"}</span></div>
        <div className="row"><span>Container</span><span>{file.container?.toUpperCase() ?? "—"}</span></div>
        <div className="row"><span>Resolution</span><span>{file.width && file.height ? `${file.width}×${file.height}` : "—"}</span></div>
        <div className="row"><span>Audio</span><span>{file.audio_codec?.toUpperCase() ?? "—"}</span></div>
        <div className="row"><span>File size</span><span>{formatBytes(file.size_bytes)}</span></div>
        <div className="row"><span>File path</span><span style={{ fontSize: 11 }}>{file.path}</span></div>
      </div>
    </div>
  );
}

function ActivityCard({ file }: { file: MediaFile | null }) {
  const progress = useProgressMap();
  const row = file ? progress?.get(file.id) : undefined;
  const lastPlayed = row ? new Date(row.updated_at).toLocaleString() : null;
  const completed = row?.completed_at ? new Date(row.completed_at).toLocaleString() : null;
  return (
    <div className="cards" style={{ marginTop: 28 }}>
      <div className="card">
        <h4>Activity</h4>
        <div className="row"><span>Status</span><span>{completed ? "Watched" : row ? "In progress" : "—"}</span></div>
        <div className="row"><span>Last touched</span><span>{lastPlayed ?? "—"}</span></div>
        <div className="row"><span>Completed</span><span>{completed ?? "—"}</span></div>
      </div>
    </div>
  );
}

function FileWatchedButton({ fileId }: { fileId: string }) {
  const progress = useProgressMap();
  const row = progress?.get(fileId);
  const [watched, setWatched] = useState<boolean | null>(null);
  const effective = watched ?? Boolean(row?.completed_at);
  useEffect(() => {
    if (progress && watched === null) setWatched(Boolean(row?.completed_at));
  }, [progress, row, watched]);
  return (
    <span className="btn ghost" style={{ padding: 0 }}>
      <MarkWatchedButton
        mediaFileId={fileId}
        isWatched={effective}
        onChanged={setWatched}
        size="md"
      />
    </span>
  );
}

function CastImg({ member }: { member: CastMember }) {
  if (!member.profile_path) return null;
  return (
    <img
      src={`${TMDB_PROFILE_BASE}${member.profile_path}`}
      alt={member.name ?? ""}
      style={{
        width: 32,
        height: 32,
        borderRadius: 999,
        objectFit: "cover",
        marginRight: 8,
        verticalAlign: "middle",
      }}
      loading="lazy"
    />
  );
}
void CastImg;

function DetailSkeleton() {
  return (
    <section className="detail">
      <div className="backdrop" />
      <div className="body">
        <div
          className="poster-card"
          style={{
            background: "oklch(0.18 0.012 60)",
          }}
        />
        <div className="info">
          <div className="kicker">Loading…</div>
          <h1 style={{ opacity: 0.4 }}>F7FIVE0</h1>
        </div>
      </div>
    </section>
  );
}
