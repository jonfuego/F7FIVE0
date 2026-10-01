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
import { useScrollRestoration } from "@/lib/scroll-restoration";
import type { Movie, OverrideOut } from "@/lib/types";

type EditInitial = OverrideOut & { algorithmic_sort_hint: string };

const PAGE_LIMIT = 20000;

export default function MoviesPage() {
  useScrollRestoration();
  const [movies, setMovies] = useState<Movie[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [genre, setGenre] = useState<string>("All");
  const [isAdmin, setIsAdmin] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const [editTarget, setEditTarget] = useState<Movie | null>(null);
  const [editInitial, setEditInitial] = useState<EditInitial | null>(null);
  const progress = useProgressMap();

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
        const data = await apiGet<Movie[]>(`/api/library/movies?limit=${PAGE_LIMIT}`);
        if (!cancelled) setMovies(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load movies");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadTick]);

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

  const filtered = useMemo(() => {
    if (!movies) return null;
    if (genre === "All") return movies;
    return movies.filter((m) => Array.isArray(m.genres) && m.genres.includes(genre));
  }, [movies, genre]);

  return (
    <AuthShell>
      <h1 className="page-title">The Cinema</h1>

      <div className="filter-bar">
        <span className="lbl">Genre</span>
        {genres.map((g) => (
          <button
            key={g}
            type="button"
            className={`chip ${genre === g ? "on" : ""}`}
            onClick={() => setGenre(g)}
          >
            {g}
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
                background: "oklch(0.18 0.012 60)",
                borderRadius: 6,
                animation: "pulse 1.6s var(--ease) infinite",
              }}
            />
          ))}
        </Grid>
      ) : filtered.length === 0 ? (
        <GridEmpty
          message={genre !== "All" ? "Nothing in F7FIVE0 for that filter." : "No movies in the library yet."}
        />
      ) : (
        <Grid>
          {filtered.map((m) => {
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
