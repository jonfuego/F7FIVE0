// Season page: /series/<id>/season/<n>. One season of a show: its episodes
// (each row plays the episode and has the File info menu) and the Back arrow
// to the show page. Reached from the season headings on the show page.

"use client";

import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { notFound, useParams } from "next/navigation";
import { AuthShell } from "@/components/AuthShell";
import { BackButton } from "@/components/BackButton";
import { Backdrop } from "@/components/Backdrop";
import { EpisodeRow } from "@/components/EpisodeRow";
import { apiGet, ApiError } from "@/lib/client-api";
import { colorForTitle, hueFromString } from "@/lib/format";
import { episodesForSeason, parseSeasonParam, seasonTitle } from "@/lib/seasons";
import type { SeriesDetail } from "@/lib/types";

export default function SeasonPage() {
  const params = useParams<{ id: string; season: string }>();
  const id = params?.id ?? "";
  const season = parseSeasonParam(params?.season);
  const [series, setSeries] = useState<SeriesDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

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
        setError(err instanceof Error ? err.message : "Failed to load season");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const episodes = useMemo(
    () => (series && season !== null ? episodesForSeason(series.episodes, season) : []),
    [series, season],
  );

  if (season === null || missing) notFound();
  if (series && episodes.length === 0) notFound();

  const tint: CSSProperties | undefined = series
    ? {
        ["--pg" as never]: colorForTitle(series.title),
        ["--ph" as never]: String(hueFromString(series.title)),
      }
    : undefined;

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
      ) : (
        <section className="detail" style={tint}>
          <div className="backdrop">
            {series ? <Backdrop src={series.backdrop_path} alt="" /> : null}
          </div>
          <div className="body">
            <BackButton href={`/series/${id}`} />
            <div className="poster-card">
              <div className="keyart-mini" />
              {series?.poster_path ? (
                <img className="real-art" src={series.poster_path} alt={series.title} />
              ) : null}
            </div>
            <div className="info">
              <div className="kicker">{series ? series.title : "Loading…"}</div>
              <h1>{season !== null ? seasonTitle(season) : ""}</h1>
              {series ? (
                <div className="meta">
                  <span>
                    {episodes.length} {episodes.length === 1 ? "episode" : "episodes"}
                  </span>
                </div>
              ) : null}
              {series ? (
                <section className="episodes">
                  {episodes.map((ep) => (
                    <EpisodeRow key={ep.id} ep={ep} />
                  ))}
                </section>
              ) : null}
            </div>
          </div>
        </section>
      )}
    </AuthShell>
  );
}
