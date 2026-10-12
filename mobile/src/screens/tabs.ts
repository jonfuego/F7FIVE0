/** Which bottom tabs show where. Pure (no navigation imports) so it unit tests
 * in Node.
 *
 * The phone shows every tab, with Podcasts between Movies & Shows and Search.
 * Android TV shows only the four it lists: no Account (no requests or admin
 * surfaces on the big screen) and no Podcasts (v1 podcasts are phone and web).
 * The TV layout hides every route that is not in TV_TABS, so a new route never
 * leaks onto the big screen by being added. */

export const PHONE_TABS = ["index", "music", "movies", "podcasts", "search", "account"] as const;

export const TV_TABS = ["index", "music", "movies", "search"] as const;

export function tabsFor(tv: boolean): readonly string[] {
  return tv ? TV_TABS : PHONE_TABS;
}

export function isTabVisible(name: string, tv: boolean): boolean {
  return tabsFor(tv).includes(name);
}
