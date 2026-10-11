// Pure helpers for the Home hero: which recent item to feature, and the
// parts of its subtitle line (with the links each part goes to).

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
