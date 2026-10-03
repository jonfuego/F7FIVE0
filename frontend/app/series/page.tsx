// TV series — status chip filter (All / Watching / Complete / New) above
// the same 2:3 poster grid as Movies. Grid is CSS
// `repeat(auto-fill, minmax(180px, 1fr))` with `gap: 24px`, rendered by
// the <Grid> component via the .grid-wall class in globals.css.
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
import { useScrollRestoration } from "@/lib/scroll-restoration";
import type { Series, OverrideOut } from "@/lib/types";

type EditInitial = OverrideOut & { algorithmic_sort_hint: string };

const PAGE_LIMIT = 1000;
const STATUS_FILTERS = ["All", "Watching", "Complete", "New"] as const;
type Status = (typeof STATUS_FILTERS)[number];

export default function SeriesPage() {
  useScrollRestoration();
  const [series, setSeries] = useState<Series[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("All");
  const [isAdmin, setIsAdmin] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const [editTarget, setEditTarget] = useState<Series | null>(null);
  const [editInitial, setEditInitial] = useState<EditInitial | null>(null);

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
        const data = await apiGet<Series[]>(`/api/library/series?limit=${PAGE_LIMIT}`);
        if (!cancelled) setSeries(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load series");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadTick]);

  const onApplied = useCallback(() => setReloadTick((t) => t + 1), []);

  const openCardEdit = useCallback(async (sr: Series) => {
    setEditTarget(sr);
    try {
      const res = await fetch(`/api/admin/override/series/${sr.id}`, {
        cache: "no-store",
      });
      if (!res.ok) return;
      const body = (await res.json()) as OverrideOut;
      setEditInitial({
        ...body,
        algorithmic_sort_hint: algorithmicSortHint(sr.title),
      });
    } catch {
      setEditInitial(null);
    }
  }, []);

  const closeCardEdit = useCallback(() => {
    setEditTarget(null);
    setEditInitial(null);
  }, []);

  const filtered = useMemo(() => {
    if (!series) return null;
    return series.filter((s) => {
      // The list endpoint doesn't surface watch state per-series, so
      // Watching/Complete leave the filter as a passthrough until the
      // backend grows that affordance. New filters by year proximity.
      if (status === "New") {
        const y = s.year;
        const cur = new Date().getFullYear();
        if (!y || y < cur - 1) return false;
      }
      return true;
    });
  }, [series, status]);

  return (
    <AuthShell>
      <h1 className="page-title">Television</h1>

      <div className="filter-bar">
        <span className="lbl">Status</span>
        {STATUS_FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            className={`chip ${status === f ? "on" : ""}`}
            onClick={() => setStatus(f)}
          >
            {f}
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
              }}
            />
          ))}
        </Grid>
      ) : filtered.length === 0 ? (
        <GridEmpty
          message={status !== "All" ? "Nothing in F7FIVE0 for that filter." : "No TV shows in the library yet."}
        />
      ) : (
        <Grid>
          {filtered.map((s) => (
            <div key={s.id} data-alpha-letter={alphaLetterOf(s.title)}>
              <SeriesCard
                series={s}
                isAdmin={isAdmin}
                onEdit={openCardEdit}
              />
            </div>
          ))}
        </Grid>
      )}

      <AlphaRail resetKey={`series:${status}:${filtered ? filtered.length : 0}`} />

      {editTarget && editInitial ? (
        <EditOverridesModal
          open
          kind="series"
          entityId={editTarget.id}
          initial={editInitial}
          onClose={closeCardEdit}
          onApplied={onApplied}
        />
      ) : null}
    </AuthShell>
  );
}

function SeriesCard({
  series,
  isAdmin,
  onEdit,
}: {
  series: Series;
  isAdmin: boolean;
  onEdit: (sr: Series) => void;
}) {
  return (
    <MediaCard
      href={`/series/${series.id}`}
      title={series.title}
      subtitle={series.year ? String(series.year) : null}
      posterPath={series.poster_path}
      kind="series"
      onAdminEdit={isAdmin ? () => onEdit(series) : undefined}
      adminEditLabel={`Edit ${series.title}`}
    />
  );
}
