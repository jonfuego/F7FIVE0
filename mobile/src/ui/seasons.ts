/** Season grouping and the season route for the app, shared by the show
 * screen and the season screen (`/movies/season/<seriesId>/<n>`). */

export interface SeasonEpisode {
  season_number: number;
  episode_number: number;
}

/** [season, episodes] pairs: episodes in order, seasons ascending, Specials
 * (season 0) last. */
export function groupSeasons<E extends SeasonEpisode>(episodes: E[]): [number, E[]][] {
  const map = new Map<number, E[]>();
  for (const ep of episodes) {
    const list = map.get(ep.season_number) ?? [];
    list.push(ep);
    map.set(ep.season_number, list);
  }
  for (const list of map.values()) list.sort((a, b) => a.episode_number - b.episode_number);
  return [...map.entries()].sort(([a], [b]) => (a === 0 ? 1 : b === 0 ? -1 : a - b));
}

export function episodesForSeason<E extends SeasonEpisode>(episodes: E[], season: number): E[] {
  return episodes.filter((e) => e.season_number === season).sort((a, b) => a.episode_number - b.episode_number);
}

export function seasonTitle(season: number): string {
  return season === 0 ? "Specials" : `Season ${season}`;
}

export function seasonRoute(seriesId: string, season: number): string {
  return `/movies/season/${seriesId}/${season}`;
}

export function parseSeason(raw: string | string[] | undefined): number | null {
  const v = Array.isArray(raw) ? raw[0] : raw;
  if (!v || !/^\d{1,3}$/.test(v)) return null;
  return Number(v);
}
