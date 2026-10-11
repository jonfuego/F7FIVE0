// Movies — genre chip filter row above the 2:3 poster wall. Grid is
// CSS `repeat(auto-fill, minmax(180px, 1fr))` with `gap: 24px`, rendered
// by the <Grid> component via the .grid-wall class in globals.css.
// Admin Edit affordance on each tile opens the unified
// EditOverridesModal (General / Details / Art / Fix Match / Refresh).

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import EditOverridesModal, { algorithmicSortHint } from "@/components/EditOverridesModal";
import { AuthShell } from "@/components/AuthShell";
import { AlphaRail, alphaLetterOf } from "@/components/AlphaRail";
import { Grid, GridEmpty } from "@/components/Grid";
import { MediaCard } from "@/components/MediaCard";
import { apiGet } from "@/lib/client-api";
import { pickProgressFor, statusForFile, useProgressMap } from "@/lib/progress";
import { emptyLibraryText } from "@/lib/library-scan";
import { useScanState } from "@/lib/use-scan-state";
import { getList, pickListLoad, setList } from "@/lib/list-cache";
import { useScrollRestoration } from "@/lib/scroll-restoration";
import { useViewPref } from "@/lib/use-view-pref";
import type { Movie, OverrideOut } from "@/lib/types";

type EditInitial = OverrideOut & { algorithmic_sort_hint: string };

const PAGE_LIMIT = 20000;
const LIST_KEY = "movies";
// Tiles this far down the wall load their poster at once instead of waiting for
// the lazy-loading observer; the rest stay lazy. About two screens of a wide window.
const EAGER_POSTERS = 24;

const MOVIE_SORTS = [
  { key: "title", label: "Title" },
  { key: "year", label: "Year" },
  { key: "rating", label: "Rating" },
] as const;

export default function MoviesPage() {
  useScrollRestoration();
  // The last list stays in memory (lib/list-cache.ts), so coming back to this
  // page paints the tiles at once and the posters come straight from the
  // browser's cache; the list is fetched again only when it is old.
  const [movies, setMovies] = useState<Movie[] | null>(
    () => getList<Movie[]>(LIST_KEY)?.data ?? null,
  );
  const [error, setError] = useState<string | null>(null);
  // Genre and sort are saved views: stored on the server per user, so they
  // follow you across web, phone and TV (lib/use-view-pref.ts).
  const [genre, setGenre] = useViewPref("movies.genre");
  const [sort, setSort] = useViewPref("movies.sort");
  const [isAdmin, setIsAdmin] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const [editTarget, setEditTarget] = useState<Movie | null>(null);
  const [editInitial, setEditInitial] = useState<EditInitial | null>(null);
  const progress = useProgressMap();
  // While a folder scan runs the list reloads every few seconds, so movies
  // show up as the scan finds them.
  const scan = useScanState();

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
    // The copy in memory was already painted by the state initializer above.
    // An edit or a folder scan tick always refetches; a plain visit refetches
    // only when that copy is old.
    const cached = getList<Movie[]>(LIST_KEY);
    const plan = pickListLoad(cached, { force: reloadTick > 0 || scan.ticks > 0 });
    if (!plan.fetch) return;
    (async () => {
      try {
        const data = await apiGet<Movie[]>(`/api/library/movies?limit=${PAGE_LIMIT}`);
        setList(LIST_KEY, data);
        if (!cancelled) setMovies(data);
      } catch (err) {
        if (!cancelled && !cached) {
          setError(err instanceof Error ? err.message : "Failed to load movies");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadTick, scan.ticks]);

  const onApplied = useCallback(() => setReloadTick((t) => t + 1), []);

  const openCardEdit = useCallback(async (m: Movie) => {
    setEditTarget(m);
    try {
      const res = await fetch(`/api/admin/override/movie/${m.id}`, {
        cache: "no-store",
      });
      if (!res.ok) return;
      const body = (await res.json()) as OverrideOut;
      setEditInitial({
        ...body,
        algorithmic_sort_hint: algorithmicSortHint(m.title),
      });
    } catch {
      setEditInitial(null);
    }
  }, []);

  const closeCardEdit = useCallback(() => {
    setEditTarget(null);
    setEditInitial(null);
  }, []);

  const genres = useMemo(() => {
    const set = new Set<string>();
    movies?.forEach((m) => {
      m.genres?.forEach((g) => {
        if (g && typeof g === "string") set.add(g);
      });
    });
    return ["All", ...Array.from(set).sort()];
  }, [movies]);

  // A saved genre the library no longer has falls back to All.
  const activeGenre = genres.includes(genre) ? genre : "All";
  const filtered = useMemo(() => {
    if (!movies) return null;
    const inGenre =
      activeGenre === "All"
        ? movies
        : movies.filter((m) => Array.isArray(m.genres) && m.genres.includes(activeGenre));
    if (sort === "title") return inGenre;
    const out = inGenre.slice();
    if (sort === "year") out.sort((a, b) => (b.year ?? -1) - (a.year ?? -1));
    if (sort === "rating") out.sort((a, b) => (b.tmdb_rating ?? -1) - (a.tmdb_rating ?? -1));
    return out;
  }, [movies, activeGenre, sort]);

  return (
    <AuthShell>
      <h1 className="page-title">Movies</h1>

      <div className="filter-bar">
        <span className="lbl">Genre</span>
        {genres.map((g) => (
          <button
            key={g}
            type="button"
            className={`chip ${activeGenre === g ? "on" : ""}`}
            onClick={() => setGenre(g)}
          >
            {g}
          </button>
        ))}
      </div>
      <div className="filter-bar">
        <span className="lbl">Sort</span>
        {MOVIE_SORTS.map((o) => (
          <button
            key={o.key}
            type="button"
            className={`chip ${sort === o.key ? "on" : ""}`}
            onClick={() => setSort(o.key)}
          >
            {o.label}
          </button>
        ))}
      </div>

      {error ? (
        <GridEmpty message={error} />
      ) : filtered === null ? (
        <Grid>
          {Array.from({ length: 18 }).map((_, i) => (
            <div
              key={i}
              style={{
                width: "100%",
                aspectRatio: "2/3",
                background: "var(--surface-2)",
                borderRadius: 6,
                animation: "pulse 1.6s var(--ease) infinite",
              }}
            />
          ))}
        </Grid>
      ) : filtered.length === 0 ? (
        <GridEmpty
          message={genre !== "All" ? "Nothing in F7FIVE0 for that filter." : emptyLibraryText("movies", scan.running)}
        />
      ) : (
        <Grid>
          {filtered.map((m, i) => {
            const row = pickProgressFor(progress, m.media_files.map((f) => f.id));
            const status = statusForFile(row);
            const pct = row?.duration_sec && row.duration_sec > 0
              ? Math.round((row.position_sec / row.duration_sec) * 100)
              : undefined;
            return (
              <div key={m.id} data-alpha-letter={alphaLetterOf(m.title)}>
                <MediaCard
                  href={`/movies/${m.id}`}
                  title={m.title}
                  subtitle={m.year ? String(m.year) : null}
                  posterPath={m.poster_path}
                  kind="movie"
                  priority={i < EAGER_POSTERS}
                  prefetch={false}
                  status={status}
                  progressPct={pct}
                  onAdminEdit={isAdmin ? () => openCardEdit(m) : undefined}
                  adminEditLabel={`Edit poster for ${m.title}`}
                />
              </div>
            );
          })}
        </Grid>
      )}

      <AlphaRail resetKey={`movies:${genre}:${filtered ? filtered.length : 0}`} />

      {editTarget && editInitial ? (
        <EditOverridesModal
          open
          kind="movie"
          entityId={editTarget.id}
          initial={editInitial}
          onClose={closeCardEdit}
          onApplied={onApplied}
        />
      ) : null}
    </AuthShell>
  );
}
