// Series detail. Marquee hero + episode list table grouped by season.
// Existing AdminRescanButton, mark-watched, and Edit-poster / Edit-
// backdrop affordances preserved.

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
import { apiGet, apiPost, ApiError } from "@/lib/client-api";
import { loadOverride } from "@/lib/overrides";
import {
  colorForTitle,
  formatBytes,
  formatDuration,
  hueFromString,
  joinMeta,
} from "@/lib/format";
import { useProgressMap } from "@/lib/progress";
import type { Episode, MediaFile, Me, OverrideOut, SeriesDetail } from "@/lib/types";

type Grouped = { season: number; episodes: Episode[] };
type EditInitial = OverrideOut & { algorithmic_sort_hint: string };

export default function SeriesDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [series, setSeries] = useState<SeriesDetail | null>(null);
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
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<SeriesDetail>(`/api/library/series/${id}`);
        if (!cancelled) setSeries(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setMissing(true);
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load series");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, reloadTick]);

  const onApplied = useCallback(() => setReloadTick((t) => t + 1), []);

  const openEdit = useCallback(async () => {
    if (!series) return;
    setEditLoading(true);
    setEditError(null);
    try {
      // apiGet refreshes an expired session once and retries; anything
      // still failing is shown next to the button instead of nothing.
      const res = await loadOverride<OverrideOut>(apiGet, "series", series.id);
      if (!res.ok) {
        setEditError(res.error);
        return;
      }
      setEditInitial({
        ...res.data,
        algorithmic_sort_hint: algorithmicSortHint(series.title),
      });
    } finally {
      setEditLoading(false);
    }
  }, [series]);

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
      ) : series === null ? (
        <SeriesSkeleton />
      ) : (
        <SeriesHero
          series={series}
          isAdmin={isAdmin}
          onEdit={openEdit}
          editBusy={editLoading}
          editError={editError}
        />
      )}
      {editInitial && series ? (
        <EditOverridesModal
          open
          kind="series"
          entityId={series.id}
          initial={editInitial}
          onClose={() => setEditInitial(null)}
          onApplied={onApplied}
        />
      ) : null}
    </AuthShell>
  );
}

function SeriesHero({
  series,
  isAdmin,
  onEdit,
  editBusy,
  editError,
}: {
  series: SeriesDetail;
  isAdmin: boolean;
  onEdit: () => void;
  editBusy: boolean;
  editError: string | null;
}) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(series.title),
    ["--ph" as never]: String(hueFromString(series.title)),
  };
  const grouped = useMemo(() => groupBySeason(series.episodes), [series.episodes]);
  const epCount = series.episodes.length;
  const meta = joinMeta([
    series.year,
    `${grouped.length} ${grouped.length === 1 ? "season" : "seasons"}`,
    `${epCount} ${epCount === 1 ? "episode" : "episodes"}`,
  ]);

  // Aggregate technical details from the first available episode's first file.
  const sampleFile = useMemo(() => {
    for (const e of series.episodes) {
      if (e.media_files.length > 0) return e.media_files[0];
    }
    return null;
  }, [series.episodes]);

  const totalSize = useMemo(() => {
    let bytes = 0;
    for (const e of series.episodes) {
      for (const f of e.media_files) {
        if (f.size_bytes) bytes += f.size_bytes;
      }
    }
    return bytes;
  }, [series.episodes]);

  return (
    <section className="detail" style={tint}>
      <div className="backdrop">
        <Backdrop src={series.backdrop_path} alt="" />
      </div>
      <div className="body">
        <div className="poster-card">
          <div className="keyart-mini" />
          {series.poster_path ? (
            <img className="real-art" src={series.poster_path} alt={series.title} />
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
                aria-label="Edit series metadata"
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
          <h1>{series.title}</h1>
          {meta ? <MetaRow text={meta} /> : null}
          {series.overview ? <p className="blurb">{series.overview}</p> : null}
          <div className="ctas">
            {findFirstEpisodeFile(grouped) ? (
              <Link
                className="btn play"
                href={`/watch/${findFirstEpisodeFile(grouped)!.id}`}
              >
                <span className="tri" /> Play
              </Link>
            ) : (
              <button type="button" className="btn play" disabled>
                Not on disk
              </button>
            )}
            <AdminRescanButton series={series} />
            <Link className="btn ghost" href="/series">
              ← Back
            </Link>
          </div>

          {sampleFile ? (
            // Mono technical block: codec, bitrate, container, file size,
            // file path. font-sans is wired to var(--mono).
            <div className="cards font-sans">
              <div className="card">
                <h4>File Information</h4>
                <div className="row"><span>Codec</span><span>{sampleFile.video_codec?.toUpperCase() ?? "—"}</span></div>
                <div className="row"><span>Bitrate</span><span>{sampleFile.bitrate_kbps ? `${(sampleFile.bitrate_kbps / 1000).toFixed(1)} Mbps` : "—"}</span></div>
                <div className="row"><span>Container</span><span>{sampleFile.container?.toUpperCase() ?? "—"}</span></div>
                <div className="row"><span>Resolution</span><span>{sampleFile.width && sampleFile.height ? `${sampleFile.width}×${sampleFile.height}` : "—"}</span></div>
                <div className="row"><span>Audio</span><span>{sampleFile.audio_codec?.toUpperCase() ?? "—"}</span></div>
                <div className="row"><span>File size</span><span>{formatBytes(totalSize)}</span></div>
                <div className="row"><span>File path</span><span style={{ fontSize: 11 }}>{sampleFile.path}</span></div>
              </div>
            </div>
          ) : null}

          {grouped.length === 0 ? (
            <div
              style={{
                marginTop: 28,
                padding: 16,
                border: "1px dashed var(--line)",
                borderRadius: 4,
                color: "var(--ink-3)",
                fontFamily: "var(--mono)",
                fontSize: 12,
              }}
            >
              No episodes on disk yet.
            </div>
          ) : (
            grouped.map((g, idx) => <SeasonSection key={g.season} group={g} defaultOpen={idx === 0} />)
          )}
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

function findFirstEpisodeFile(groups: Grouped[]): MediaFile | null {
  for (const g of groups) {
    for (const e of g.episodes) {
      if (e.media_files.length > 0) return e.media_files[0];
    }
  }
  return null;
}

function SeasonSection({
  group,
  defaultOpen,
}: {
  group: Grouped;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const title = group.season === 0 ? "Specials" : `Season ${group.season}`;
  return (
    <section className="episodes">
      <h3 onClick={() => setOpen((o) => !o)} style={{ cursor: "pointer" }}>
        {title} · {group.episodes.length} ep{group.episodes.length === 1 ? "" : "s"}
      </h3>
      {open
        ? group.episodes.map((ep) => <EpisodeRow key={ep.id} ep={ep} />)
        : null}
    </section>
  );
}

function EpisodeRow({ ep }: { ep: Episode }) {
  const primary = ep.media_files[0];
  const progress = useProgressMap();
  const row = primary ? progress?.get(primary.id) : undefined;
  const [watched, setWatched] = useState<boolean | null>(null);
  const effective = watched ?? Boolean(row?.completed_at);
  useEffect(() => {
    if (progress && watched === null && primary) {
      setWatched(Boolean(row?.completed_at));
    }
  }, [progress, primary, row, watched]);

  const pct =
    row?.duration_sec && row.duration_sec > 0
      ? Math.round((row.position_sec / row.duration_sec) * 100)
      : null;

  const rowContent = (
    <>
      <div className="num">{String(ep.episode_number).padStart(2, "0")}</div>
      <div className="body">
        <div className="t">{ep.title ?? `Episode ${ep.episode_number}`}</div>
        {ep.overview ? <div className="s">{ep.overview}</div> : null}
      </div>
      <div className="right">
        <div>{primary?.duration_sec ? formatDuration(primary.duration_sec) : "—"}</div>
        {pct !== null && pct > 0 && pct < 100 ? (
          <div className="pb">
            <div style={{ width: `${pct}%` }} />
          </div>
        ) : null}
        {effective ? (
          <span style={{ color: "var(--hive-text)", fontSize: 10 }}>watched</span>
        ) : null}
      </div>
    </>
  );

  if (!primary) {
    return <div className="ep" style={{ opacity: 0.5 }}>{rowContent}</div>;
  }

  return (
    <div className="ep">
      <Link
        href={`/watch/${primary.id}`}
        style={{ display: "contents" }}
        aria-label={`Play ${ep.title ?? `episode ${ep.episode_number}`}`}
      >
        {rowContent}
      </Link>
      <span style={{ display: "none" }}>
        <MarkWatchedButton
          mediaFileId={primary.id}
          isWatched={effective}
          onChanged={setWatched}
        />
      </span>
    </div>
  );
}

function AdminRescanButton({ series }: { series: SeriesDetail }) {
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/session/me", { cache: "no-store" });
        if (!res.ok) {
          if (!cancelled) setIsAdmin(false);
          return;
        }
        const me = (await res.json()) as Me | null;
        if (!cancelled) setIsAdmin(me?.role === "admin");
      } catch {
        if (!cancelled) setIsAdmin(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Folder-scanned shows have no Sonarr link; the scheduled folder scan
  // picks up their changes, so there is nothing to trigger here.
  if (!isAdmin || series.sonarr_id === null) return null;

  const disabled = busy || series.sonarr_id === null;
  const title =
    series.sonarr_id === null
      ? "This series isn't linked to Sonarr."
      : "Ask Sonarr to rescan the folder, then refresh F7FIVE0.";

  async function onClick() {
    if (disabled) return;
    setBusy(true);
    setStatus(null);
    try {
      await apiPost(`/api/admin/library/series/${series.id}/rescan`, {});
      setStatus("Rescan queued.");
    } catch (err) {
      if (err instanceof ApiError && err.detail === "series_not_linked_to_sonarr") {
        setStatus("Not linked to Sonarr.");
      } else {
        setStatus(err instanceof Error ? err.message : "Rescan failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="btn ghost"
      style={{ padding: "10px 18px", fontSize: 13 }}
    >
      {busy ? "Rescanning…" : status ?? "Rescan folder"}
    </button>
  );
}

function groupBySeason(episodes: Episode[]): Grouped[] {
  const by = new Map<number, Episode[]>();
  for (const ep of episodes) {
    const arr = by.get(ep.season_number);
    if (arr) arr.push(ep);
    else by.set(ep.season_number, [ep]);
  }
  const groups: Grouped[] = [];
  for (const [season, eps] of by.entries()) {
    eps.sort((a, b) => a.episode_number - b.episode_number);
    groups.push({ season, episodes: eps });
  }
  groups.sort((a, b) => {
    if (a.season === 0) return 1;
    if (b.season === 0) return -1;
    return a.season - b.season;
  });
  return groups;
}

function SeriesSkeleton() {
  return (
    <section className="detail">
      <div className="backdrop" />
      <div className="body">
        <div
          className="poster-card"
          style={{ background: "var(--surface-2)" }}
        />
        <div className="info">
          <div className="kicker">Loading…</div>
        </div>
      </div>
    </section>
  );
}
