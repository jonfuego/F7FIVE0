// Home — the marquee. Hero featured film + three rails:
// Continue Watching, Recent Arrivals, Mixes preview. Hero pulls
// whatever /api/library/recent surfaces first per the design spec.

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { AuthShell } from "@/components/AuthShell";
import { ContinueWatchingCard } from "@/components/ContinueWatchingCard";
import { MediaCard } from "@/components/MediaCard";
import { Row } from "@/components/Row";
import { apiGet, apiPost } from "@/lib/client-api";
import { colorForTitle, hueFromString, joinMeta } from "@/lib/format";
import { heroSubtitleParts, pickFeatured } from "@/lib/featured";
import { heroEmptyMessage, resolveHeroState } from "@/lib/hero-state";
import { resolveHeroPlay } from "@/lib/play-action";
import {
  pickProgressFor, statusForFile, useProgressMap,
} from "@/lib/progress";
import { albumToQueueItems, useQueue, type QueueItem } from "@/lib/queue";
import { useScrollRestoration } from "@/lib/scroll-restoration";
import { groupBySeason } from "@/lib/seasons";
import type {
  AlbumDetail, ContinueWatchingItem, MovieDetail, RecentItem,
  RecentMusicVideo, SeriesDetail,
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
  // Drives the empty-hero copy: admins get a nudge to Admin, members don't.
  const [isAdmin, setIsAdmin] = useState(false);

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

  // Load (and reload, on retry) the home rails. Resets to the loading state
  // first so a retry after an error puts the hero back on the skeleton while
  // it re-fetches instead of leaving the error banner up.
  const [reloadKey, setReloadKey] = useState(0);
  const retry = useCallback(() => {
    setState({
      continueWatching: null,
      recent: null,
      recentMusicVideos: null,
      error: null,
    });
    setReloadKey((k) => k + 1);
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
  }, [reloadKey]);

  const heroState = resolveHeroState(state.recent, state.error);
  const featured = pickFeatured(state.recent);
  const recentTail = useMemo(
    () => (state.recent ? state.recent.filter((it) => it !== featured) : []),
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
      {heroState.type === "loading" ? (
        <HeroSkeleton />
      ) : heroState.type === "error" ? (
        <HeroError message={heroState.message} onRetry={retry} />
      ) : featured ? (
        <Hero item={featured} continueWatching={state.continueWatching} />
      ) : (
        // Loaded but nothing to feature: never fall back to the skeleton.
        <HeroEmpty message={heroEmptyMessage(isAdmin)} />
      )}

      {/* Continue Watching / Listening disappear entirely when empty; an
          empty rail at the top of the page is just noise. */}
      {continueVideo && continueVideo.length > 0 ? (
        <Row title="Continue Watching" seeAllHref="/movies" variant="continue">
          {continueVideo.map((item) => (
            <ContinueWatchingCard key={item.media_file_id} item={item} />
          ))}
        </Row>
      ) : null}

      {continueAudio && continueAudio.length > 0 ? (
        <Row title="Continue Listening" seeAllHref="/music" variant="continue">
          {continueAudio.map((item) => (
            <ContinueWatchingCard key={item.media_file_id} item={item} />
          ))}
        </Row>
      ) : null}

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

function Hero({
  item,
  continueWatching,
}: {
  item: RecentItem;
  continueWatching: ContinueWatchingItem[] | null;
}) {
  const router = useRouter();
  const { playAlbum } = useQueue();
  // Resolving the playable media file (movie file, series on-deck / first
  // episode) needs a detail fetch, so Play shows a brief busy state and
  // guards against double taps.
  const [playBusy, setPlayBusy] = useState(false);
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(item.title),
    ["--ph" as never]: String(hueFromString(item.title)),
  };
  const [artistId, setArtistId] = useState<string | null>(null);
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
    apiGet<{
      overview?: string | null;
      backdrop_path?: string | null;
      artist_id?: string | null;
    }>(
      `/api/library/${path}`,
    )
      .then((data) => {
        if (cancelled) return;
        setOverview(data.overview ?? null);
        setBackdrop(data.backdrop_path ?? null);
        setArtistId(item.kind === "album" ? data.artist_id ?? null : null);
      })
      .catch(() => {
        if (cancelled) return;
        setOverview(null);
        setBackdrop(null);
        setArtistId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [item.kind, item.id]);

  // Hero Play. An album starts in the dock and stays on the page; a movie
  // or series resolves its playable file and navigates to /watch, the same
  // route the detail pages use (the watch page resumes). The kind-to-action
  // decision lives in resolveHeroPlay (pure, unit-tested).
  async function onPlay() {
    if (playBusy) return;
    setPlayBusy(true);
    try {
      if (item.kind === "album") {
        const detail = await apiGet<AlbumDetail>(`/api/library/albums/${item.id}`);
        const items = albumToQueueItems(detail);
        if (items.length > 0) playAlbum(items, { shuffle: false });
        return;
      }
      const mediaFileId = await resolveVideoFileId(item, continueWatching);
      const action = resolveHeroPlay(item.kind, mediaFileId);
      if (action.type === "watch") router.push(action.href);
    } catch {
      // Best-effort: a failed resolve leaves the page unchanged.
    } finally {
      setPlayBusy(false);
    }
  }

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
        <div className="band">
          <h1 className={item.title.length > 22 ? "long" : undefined}>
            {item.title}
          </h1>
          <div className="meta">
            {heroSubtitleParts(item, artistId).map((part, i) => (
              <span key={i}>
                {i > 0 ? <span className="dot" aria-hidden>•</span> : null}
                {part.href ? <Link href={part.href}>{part.text}</Link> : part.text}
              </span>
            ))}
          </div>
          {overview ? <p className="blurb">{overview}</p> : null}
          <div className="ctas">
            <button
              type="button"
              className="btn play"
              onClick={onPlay}
              disabled={playBusy}
              aria-label={`Play ${item.title}`}
            >
              <span className="tri" /> Play
            </button>
            <Link className="btn ghost" href={detailHref(item.kind, item.id)}>
              + Details
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

// Resolve the media file id to play for a video hero item. Movies use the
// first file; series prefer the On Deck episode (from the already-loaded
// continue-watching list), falling back to the first episode on disk.
async function resolveVideoFileId(
  item: RecentItem,
  continueWatching: ContinueWatchingItem[] | null,
): Promise<string | null> {
  if (item.kind === "movie") {
    const detail = await apiGet<MovieDetail>(`/api/library/movies/${item.id}`);
    return detail.media_files[0]?.id ?? null;
  }
  if (item.kind === "series") {
    const onDeck = continueWatching?.find(
      (it) => it.kind === "series" && it.id === item.id,
    );
    if (onDeck?.media_file_id) return onDeck.media_file_id;
    const detail = await apiGet<SeriesDetail>(`/api/library/series/${item.id}`);
    for (const group of groupBySeason(detail.episodes)) {
      for (const ep of group.episodes) {
        if (ep.media_files.length > 0) return ep.media_files[0].id;
      }
    }
  }
  return null;
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

// Shown when the recent call settled with nothing to feature: an empty
// library, not a load that is still running. Admins get a nudge toward
// Admin; members get a plain line (copy from heroEmptyMessage).
function HeroEmpty({ message }: { message: string }) {
  return (
    <section className="hero">
      <div className="keyart" />
      <div className="content">
        <h1 style={{ opacity: 0.4 }}>F7FIVE0</h1>
        <p className="blurb">{message}</p>
      </div>
    </section>
  );
}

// Shown when the recent call failed. Says so and offers a retry that
// re-fetches the home rails.
function HeroError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <section className="hero">
      <div className="keyart" />
      <div className="content">
        <h1 style={{ opacity: 0.4 }}>F7FIVE0</h1>
        <p className="blurb">Could not load your library. {message}</p>
        <div className="ctas">
          <button type="button" className="btn play" onClick={onRetry}>
            Retry
          </button>
        </div>
      </div>
    </section>
  );
}

// Home Mixes rail. The whole card no longer navigates: "Open Mix" links to
// /mixes, and Play fetches this mix's auto-playlist and starts it in the
// dock (same wiring the /mixes playbills use), staying on the page.
const MIX_PREVIEW_URL: Record<string, string> = {
  "recently-added": "/api/library/auto-playlist/recently-added?limit=100",
  "most-played": "/api/library/auto-playlist/most-played?limit=100&window=all",
  "continue-listening": "/api/library/auto-playlist/continue-listening?limit=50",
  random: "/api/library/auto-playlist/random?limit=100",
};

function MixPreviewCard({ kind, tag, title, sub }: { kind: string; tag: string; title: string; sub: string }) {
  const { playAlbum } = useQueue();
  const [busy, setBusy] = useState(false);

  async function onPlay() {
    if (busy) return;
    const url = MIX_PREVIEW_URL[kind];
    if (!url) return;
    setBusy(true);
    try {
      const data = await apiGet<{ items: QueueItem[] }>(url);
      if (Array.isArray(data?.items) && data.items.length > 0) {
        playAlbum(data.items, { shuffle: false });
      }
    } catch {
      // Best-effort: a failed fetch leaves the page and dock unchanged.
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
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
          <Link href="/mixes">Open Mix</Link>
          <button
            type="button"
            className="play"
            onClick={onPlay}
            disabled={busy}
            aria-label={`Play ${title}`}
            style={{ background: "none", border: "none", cursor: "pointer", font: "inherit", color: "inherit", padding: 0 }}
          >
            <span className="tri" /> Play
          </button>
        </div>
      </div>
    </div>
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
