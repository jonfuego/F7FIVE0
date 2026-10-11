// Pure helpers for the Home hero: which recent item to feature, and the
// parts of its subtitle line (with the links each part goes to), and the
// facts line under it.

export type FeaturedCandidate = {
  kind: "movie" | "series" | "album";
  id: string;
  title: string;
  subtitle: string | null;
  year: number | null;
  poster_path: string | null;
  added_at: string;
};

function time(item: FeaturedCandidate): number {
  const t = Date.parse(item.added_at);
  return Number.isNaN(t) ? 0 : t;
}

// Newest item in the list; the earlier entry wins a tie, so the server's
// order decides.
function newest<T extends FeaturedCandidate>(items: T[]): T | null {
  let best: T | null = null;
  for (const it of items) {
    if (best === null || time(it) > time(best)) best = it;
  }
  return best;
}

/**
 * The item the hero features: the newest one that has art, so the banner is
 * never a blank frame while a later pick has a poster. If nothing has art,
 * the newest item. Null only for an empty list.
 */
export function pickFeatured<T extends FeaturedCandidate>(
  items: readonly T[] | null,
): T | null {
  if (!items || items.length === 0) return null;
  const withArt = items.filter((it) => !!it.poster_path);
  return newest(withArt.length > 0 ? withArt : [...items]);
}

export type SubtitlePart = { text: string; href: string | null };

/** Section page a media type links to. */
export function typeHref(kind: FeaturedCandidate["kind"]): string {
  if (kind === "series") return "/series";
  if (kind === "album") return "/music/albums";
  return "/movies";
}

/**
 * Subtitle parts in display order: year (text), artist (links to the artist
 * page when the id is known), type label (links to its section).
 */
export function heroSubtitleParts(
  item: Pick<FeaturedCandidate, "kind" | "year" | "subtitle">,
  artistId: string | null,
): SubtitlePart[] {
  const parts: SubtitlePart[] = [];
  if (item.year != null) parts.push({ text: String(item.year), href: null });
  const sub = item.subtitle?.trim();
  if (sub) {
    parts.push({
      text: sub,
      href: item.kind === "album" && artistId ? `/music/artists/${artistId}` : null,
    });
  }
  const label =
    item.kind === "series" ? "Series" : item.kind === "album" ? "Album" : "Movie";
  parts.push({ text: label, href: typeHref(item.kind) });
  return parts;
}

/**
 * What the detail call behind the hero can carry. Every field is optional:
 * the helper reads what is there and skips the rest. Movies bring runtime,
 * genres and a rating; series bring their episode list; albums bring tracks
 * and genres.
 */
export type HeroFactsSource = {
  runtime_min?: number | null;
  genres?: readonly string[] | null;
  tmdb_rating?: number | null;
  episodes?: ReadonlyArray<{ season_number: number }> | null;
  tracks?: ReadonlyArray<{ duration_sec?: number | null }> | null;
};

const MAX_GENRES = 3;

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

// "1h 48m" for a positive runtime in minutes.
function runtimeText(minutes: number): string {
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

/**
 * Facts line for the hero, in display order, one string per fact. A fact
 * whose data is missing is left out, so the result may be empty:
 * - movie: runtime, genres (first three), rating
 * - series: seasons, episodes, genres, rating
 * - album: track count, total length, genres
 * Season 0 (specials) is not counted as a season. An album total length
 * needs every track's duration; with one missing it is skipped rather than
 * shown short.
 */
export function heroFacts(
  kind: FeaturedCandidate["kind"],
  src: HeroFactsSource | null | undefined,
): string[] {
  if (!src) return [];
  const facts: string[] = [];

  if (kind === "movie") {
    const rt = src.runtime_min;
    if (rt != null && Number.isFinite(rt) && rt > 0) facts.push(runtimeText(rt));
  }

  if (kind === "series") {
    const eps = src.episodes ?? [];
    const seasons = new Set(
      eps.map((e) => e.season_number).filter((n) => n > 0),
    );
    if (seasons.size > 0) facts.push(plural(seasons.size, "season", "seasons"));
    if (eps.length > 0) facts.push(plural(eps.length, "episode", "episodes"));
  }

  if (kind === "album") {
    const tracks = src.tracks ?? [];
    if (tracks.length > 0) {
      facts.push(plural(tracks.length, "track", "tracks"));
      const secs = tracks.map((t) => t.duration_sec);
      if (secs.every((s) => s != null && Number.isFinite(s) && s > 0)) {
        const totalMin = Math.round(
          (secs as number[]).reduce((a, b) => a + b, 0) / 60,
        );
        if (totalMin > 0) facts.push(runtimeText(totalMin));
      }
    }
  }

  const genres = (src.genres ?? [])
    .map((g) => (typeof g === "string" ? g.trim() : ""))
    .filter((g) => g.length > 0)
    .slice(0, MAX_GENRES);
  if (genres.length > 0) facts.push(genres.join(", "));

  if (kind !== "album") {
    const r = src.tmdb_rating;
    if (r != null && Number.isFinite(r) && r > 0) facts.push(`★ ${r.toFixed(1)}`);
  }

  return facts;
}
