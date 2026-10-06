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

/** The `[season]` route segment as a season number, or null if it isn't one. */
export function parseSeasonParam(raw: string | string[] | undefined): number | null {
  const v = Array.isArray(raw) ? raw[0] : raw;
  if (!v || !/^\d{1,3}$/.test(v)) return null;
  return Number(v);
}
