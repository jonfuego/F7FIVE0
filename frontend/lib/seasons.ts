// Season grouping and season-page routing for TV, shared by the show page
// and the season page (/series/<id>/season/<n>). Pure so node:test can
// cover it (seasons.test.ts).

export type SeasonEpisode = { season_number: number; episode_number: number };
export type SeasonGroup<E> = { season: number; episodes: E[] };

/** Episodes grouped by season, episodes in order, seasons ascending with
 * Specials (season 0) last. */
export function groupBySeason<E extends SeasonEpisode>(episodes: E[]): SeasonGroup<E>[] {
  const by = new Map<number, E[]>();
  for (const ep of episodes) {
    const arr = by.get(ep.season_number);
    if (arr) arr.push(ep);
    else by.set(ep.season_number, [ep]);
  }
  const groups: SeasonGroup<E>[] = [];
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

/** Only that season's episodes, in order. */
export function episodesForSeason<E extends SeasonEpisode>(episodes: E[], season: number): E[] {
  return episodes
    .filter((e) => e.season_number === season)
    .sort((a, b) => a.episode_number - b.episode_number);
}

export function seasonTitle(season: number): string {
  return season === 0 ? "Specials" : `Season ${season}`;
}

export function seasonHref(seriesId: string, season: number): string {
  return `/series/${encodeURIComponent(seriesId)}/season/${season}`;
}

export type SeasonThumb = {
  season: number;
  title: string;
  href: string;
  /** Season poster, or the show poster when the season has none. */
  poster: string | null;
  episodeCount: number;
  countLabel: string;
};

/** The season thumbs for the show page grid: the server's season list when it
 * sent one (with posters), otherwise built from the episodes. Seasons ascend
 * with Specials last; a season without its own picture uses the show poster. */
export function seasonThumbs(
  seriesId: string,
  showPoster: string | null,
  episodes: SeasonEpisode[],
  seasons?: { season_number: number; poster_path: string | null; episode_count: number }[],
): SeasonThumb[] {
  const rows =
    seasons && seasons.length > 0
      ? seasons.map((s) => ({ season: s.season_number, poster: s.poster_path, count: s.episode_count }))
      : groupBySeason(episodes).map((g) => ({ season: g.season, poster: null, count: g.episodes.length }));
  rows.sort((a, b) => {
    if (a.season === 0) return 1;
    if (b.season === 0) return -1;
    return a.season - b.season;
  });
  return rows.map((r) => ({
    season: r.season,
    title: seasonTitle(r.season),
    href: seasonHref(seriesId, r.season),
    poster: r.poster ?? showPoster,
    episodeCount: r.count,
    countLabel: `${r.count} ${r.count === 1 ? "episode" : "episodes"}`,
  }));
}

/** The `[season]` route segment as a season number, or null if it isn't one. */
export function parseSeasonParam(raw: string | string[] | undefined): number | null {
  const v = Array.isArray(raw) ? raw[0] : raw;
  if (!v || !/^\d{1,3}$/.test(v)) return null;
  return Number(v);
}
