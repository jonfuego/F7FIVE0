// Home — the marquee. Hero featured film + three rails:
// Continue Watching, Recent Arrivals, Mixes preview. Hero pulls
// whatever /api/library/recent surfaces first per the design spec.

"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { AuthShell } from "@/components/AuthShell";
import { ContinueWatchingCard } from "@/components/ContinueWatchingCard";
import { MediaCard } from "@/components/MediaCard";
import { Row } from "@/components/Row";
import { apiGet, apiPost } from "@/lib/client-api";
import { colorForTitle, hueFromString, joinMeta } from "@/lib/format";
import {
  pickProgressFor, statusForFile, useProgressMap,
} from "@/lib/progress";
import { useScrollRestoration } from "@/lib/scroll-restoration";
import type {
  ContinueWatchingItem, RecentItem, RecentMusicVideo,
} from "@/lib/types";

const ROW_LIMIT = 20;

const MIX_PREVIEW: Array<{ kind: string; tag: string; title: string; sub: string }> = [
  { kind: "recently-added", tag: "Fresh", title: "Recently Added", sub: "What's new in the library, freshest first." },
  { kind: "most-played", tag: "Top Spins", title: "Most Played", sub: "What you've listened to the most." },
  { kind: "continue-listening", tag: "Pick Up", title: "Continue Listening", sub: "Audio you started but didn't finish." },
  { kind: "random", tag: "Wildcard", title: "Random", sub: "A hundred random tracks, anything goes." },
];

type State = {
  continueWatching: ContinueWatchingItem[] | null;
  recent: RecentItem[] | null;
  recentMusicVideos: RecentMusicVideo[] | null;
  error: string | null;
};

export default function Home() {
  useScrollRestoration();
  const [state, setState] = useState<State>({
    continueWatching: null,
    recent: null,
    recentMusicVideos: null,
    error: null,
  });
  const progress = useProgressMap();
  // New-arrivals badge: items added since the last home visit. We read the
  // count first, then stamp "seen" so the next visit measures from now.
  const [newCount, setNewCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const badge = await apiGet<{ count: number }>("/api/library/recent/badge");
        if (!cancelled) setNewCount(badge.count);
      } catch {
        /* badge is best-effort; ignore failures */
      }
      try {
        await apiPost("/api/library/recent/seen", {});
      } catch {
        /* ignore */
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
        const [continueWatching, recent, recentMusicVideos] = await Promise.all([
          apiGet<ContinueWatchingItem[]>(
            `/api/library/continue-watching?limit=${ROW_LIMIT}`,
          ),
          apiGet<RecentItem[]>(`/api/library/recent?limit=${ROW_LIMIT}`),
          apiGet<RecentMusicVideo[]>(
            `/api/library/music-videos/recent?limit=12`,
          ),
        ]);
        if (cancelled) return;
        setState({ continueWatching, recent, recentMusicVideos, error: null });
      } catch (err) {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          error: err instanceof Error ? err.message : "Failed to load library",
        }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const featured = state.recent && state.recent.length > 0 ? state.recent[0] : null;
  const recentTail = useMemo(
    () => (state.recent ? state.recent.slice(featured ? 1 : 0) : []),
    [state.recent, featured],
  );
  // Split continue-watching into video (movie + series) and audio (album)
  // so the home page surfaces a dedicated Continue Listening rail.
  const continueVideo = useMemo(
    () =>
      state.continueWatching
        ? state.continueWatching.filter((it) => it.kind !== "album")
        : null,
    [state.continueWatching],
  );
  const continueAudio = useMemo(
    () =>
      state.continueWatching
        ? state.continueWatching.filter((it) => it.kind === "album")
        : null,
    [state.continueWatching],
  );

  return (
    <AuthShell>
      {state.error ? (
        <div
          style={{
            margin: "16px 64px",
            padding: "12px 16px",
            border: "1px solid var(--danger)",
            borderRadius: 4,
            color: "var(--danger)",
            fontFamily: "var(--mono)",
            fontSize: 12,
            letterSpacing: "0.06em",
          }}
        >
          {state.error}
        </div>
      ) : null}

      {featured ? <Hero item={featured} /> : <HeroSkeleton />}

      <Row
        title="Continue Watching"
        seeAllHref="/movies"
        variant="continue"
        isEmpty={!!continueVideo && continueVideo.length === 0}
        emptyMessage="Nothing in progress right now."
      >
        {continueVideo
          ? continueVideo.map((item) => (
              <ContinueWatchingCard key={item.media_file_id} item={item} />
            ))
          : null}
      </Row>

      <Row
        title="Continue Listening"
        seeAllHref="/music"
        variant="continue"
        isEmpty={!!continueAudio && continueAudio.length === 0}
        emptyMessage="Nothing in progress right now."
      >
        {continueAudio
          ? continueAudio.map((item) => (
              <ContinueWatchingCard key={item.media_file_id} item={item} />
            ))
          : null}
      </Row>

      <Row
        title="Recent Arrivals"
        kicker={newCount > 0 ? (newCount > 99 ? "99+ new" : `${newCount} new`) : undefined}
        seeAllHref="/movies"
        isEmpty={!!state.recent && state.recent.length === 0}
        emptyMessage="No new arrivals."
      >
        {recentTail.map((r) => {
          const href = detailHref(r.kind, r.id);
          return (
            <MediaCard
              key={`${r.kind}:${r.id}`}
              href={href}
              title={r.title}
              subtitle={r.subtitle ?? (r.year ? String(r.year) : null)}
              posterPath={r.poster_path}
              kind={r.kind === "album" ? "album" : r.kind === "series" ? "series" : "movie"}
              status={statusForFile(undefined)}
              progressPct={progressBarFromMap(progress, r.kind, r.id)}
            />
          );
        })}
      </Row>

      {state.recentMusicVideos && state.recentMusicVideos.length > 0 ? (
        <Row
          title="Recently Added Music Videos"
          kicker="Fresh"
          seeAllHref="/music-videos"
        >
          {state.recentMusicVideos.map((mv) => (
            <RecentMusicVideoTile key={mv.id} mv={mv} />
          ))}
        </Row>
      ) : null}

      <Row title="Mixes" seeAllHref="/mixes">
        {MIX_PREVIEW.map((m) => (
          <MixPreviewCard key={m.kind} kind={m.kind} tag={m.tag} title={m.title} sub={m.sub} />
        ))}
      </Row>
    </AuthShell>
  );
}

function RecentMusicVideoTile({ mv }: { mv: RecentMusicVideo }) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(mv.title),
    ["--ph" as never]: String(hueFromString(mv.title)),
  };
  const subtitle = joinMeta([mv.artist_name, mv.release_title]);
  return (
    <Link
      href={`/watch/${mv.media_file_id}`}
      className="poster"
      style={{ ...tint, width: "auto" }}
      aria-label={mv.title}
    >
      <div
        className="frame"
        style={{ aspectRatio: "16/9", borderRadius: 6 }}
      >
        <div className="keyart-mini" />
        {mv.thumb_path ? (
          <img
            src={mv.thumb_path}
            alt={mv.title}
            loading="lazy"
            decoding="async"
            className="real-art"
          />
        ) : null}
      </div>
      <div className="info">
        <div className="t">{mv.title}</div>
        {subtitle ? <div className="s">{subtitle}</div> : null}
      </div>
    </Link>
  );
}

function progressBarFromMap(
  _progress: ReturnType<typeof useProgressMap>,
  _kind: RecentItem["kind"],
  _id: string,
): number | undefined {
  // Recent endpoint doesn't surface media_file_ids in this response, so
  // a per-tile progress bar would require a separate lookup. Skipped on
  // the recent rail; the dedicated Continue Watching rail above already
  // covers in-progress titles.
  void _progress;
  return undefined;
}

function Hero({ item }: { item: RecentItem }) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(item.title),
    ["--ph" as never]: String(hueFromString(item.title)),
  };
  const meta = joinMeta([
    item.year,
    item.subtitle,
    item.kind === "series" ? "Series" : item.kind === "album" ? "Album" : null,
  ]);
  // Pull the synopsis from the matching detail endpoint on mount. Falls
  // back to no blurb if the detail call fails or the row has no
  // overview text. Cheap second call, runs once per featured change.
  const [overview, setOverview] = useState<string | null>(null);
  // Detail rows carry the 16:9 backdrop. Prefer it over the 2:3 poster
  // for the wide hero frame so portrait compositions don't crop to the
  // figure's midsection. Albums have no backdrop and stay on poster.
  const [backdrop, setBackdrop] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const path = item.kind === "movie"
      ? `movies/${item.id}`
      : item.kind === "series"
        ? `series/${item.id}`
        : `albums/${item.id}`;
    apiGet<{ overview?: string | null; backdrop_path?: string | null }>(
      `/api/library/${path}`,
    )
      .then((data) => {
        if (cancelled) return;
        setOverview(data.overview ?? null);
        setBackdrop(data.backdrop_path ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        setOverview(null);
        setBackdrop(null);
      });
    return () => {
      cancelled = true;
    };
  }, [item.kind, item.id]);
  return (
    <section className="hero" style={tint}>
      <div className="keyart" />
      {backdrop || item.poster_path ? (
        <img
          className="keyart-img"
          src={backdrop ?? item.poster_path ?? ""}
          alt=""
          aria-hidden
        />
      ) : null}
      <div className="content">
        <h1>{item.title}</h1>
        {meta ? <div className="meta">{splitMeta(meta)}</div> : null}
        {overview ? <p className="blurb">{overview}</p> : null}
        <div className="ctas">
          <Link className="btn play" href={detailHref(item.kind, item.id)}>
            <span className="tri" /> Play
          </Link>
          <Link className="btn ghost" href={detailHref(item.kind, item.id)}>
            + Details
          </Link>
        </div>
      </div>
    </section>
  );
}

function splitMeta(meta: string) {
  return meta.split(" • ").map((part, i, arr) => (
    <span key={i}>
      {part}
      {i < arr.length - 1 ? <span aria-hidden style={{ margin: "0 12px", color: "var(--ink-3)" }}>•</span> : null}
    </span>
  ));
}

function HeroSkeleton() {
  return (
    <section className="hero">
      <div className="keyart" />
      <div className="content">
        <h1 style={{ opacity: 0.4 }}>F7FIVE0</h1>
      </div>
    </section>
  );
}

function MixPreviewCard({ kind, tag, title, sub }: { kind: string; tag: string; title: string; sub: string }) {
  return (
    <Link
      href="/mixes"
      className="playbill"
      style={{
        flex: "0 0 auto",
        width: 320,
        scrollSnapAlign: "start",
      }}
      data-kind={kind}
    >
      <div className="pb-art">
        <div className="big-num" />
      </div>
      <div className="pb-body">
        <div className="pb-tag">{tag}</div>
        <h3>{title}</h3>
        <p className="pb-sub">{sub}</p>
        <div className="pb-foot">
          <span>Open Mix</span>
          <span className="play"><span className="tri" /> Play</span>
        </div>
      </div>
    </Link>
  );
}

function detailHref(kind: RecentItem["kind"], id: string): string {
  switch (kind) {
    case "movie":
      return `/movies/${id}`;
    case "series":
      return `/series/${id}`;
    case "album":
      return `/music/${id}`;
  }
}
