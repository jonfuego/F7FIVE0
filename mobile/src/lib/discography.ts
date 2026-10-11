// Groups an artist's albums into Discography sections.
//
// Pure and dependency free. The web app has the same file at
// frontend/lib/discography.ts with the same rules and the same test cases;
// change both together.
//
// Sections, in this order: Albums, EPs, Singles, Other. Empty sections are
// left out.
//
// Where an album goes:
//   1. A secondary type of Compilation or Live sends it to Other, whatever its
//      primary type is (a live album is "Album" + "Live" in MusicBrainz).
//   2. The other MusicBrainz secondary types also send it to Other, because
//      they are not studio releases: Soundtrack, Remix, DJ-mix, Mixtape/Street,
//      Demo, Spokenword, Interview, Audiobook, Audio drama. A secondary type
//      this list does not know is ignored, so a new MusicBrainz value never
//      hides a studio album.
//   3. Otherwise the primary type decides: Album, EP and Single go to Albums,
//      EPs and Singles. Anything else (Broadcast, Other, an unknown value, a
//      blank, or no type at all) goes to Other.
// Type matching ignores case and surrounding spaces.
//
// Inside a section albums are ordered by year, oldest first (the order the
// artist page and the API already use), then by title, then by their place in
// the input. Albums with no usable year come last.

export type DiscographySectionId = "albums" | "eps" | "singles" | "other";

export type DiscographyAlbum = {
  title: string;
  release_date?: string | null;
  album_type?: string | null;
  secondary_types?: string[] | null;
};

export type DiscographySection<T extends DiscographyAlbum = DiscographyAlbum> = {
  id: DiscographySectionId;
  title: string;
  albums: T[];
};

export const DISCOGRAPHY_SECTION_TITLES: Record<DiscographySectionId, string> = {
  albums: "Albums",
  eps: "EPs",
  singles: "Singles",
  other: "Other",
};

const SECTION_ORDER: DiscographySectionId[] = ["albums", "eps", "singles", "other"];

// Normalised (trimmed, lower case) secondary types that move an album to Other.
const OTHER_SECONDARY_TYPES = new Set([
  "compilation",
  "live",
  "soundtrack",
  "remix",
  "dj-mix",
  "mixtape/street",
  "demo",
  "spokenword",
  "interview",
  "audiobook",
  "audio drama",
]);

const PRIMARY_SECTIONS: Record<string, DiscographySectionId> = {
  album: "albums",
  ep: "eps",
  single: "singles",
};

function norm(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

/** The section one album belongs to. */
export function discographySectionFor(album: DiscographyAlbum): DiscographySectionId {
  const secondary = Array.isArray(album.secondary_types) ? album.secondary_types : [];
  if (secondary.some((t) => OTHER_SECONDARY_TYPES.has(norm(t)))) return "other";
  return PRIMARY_SECTIONS[norm(album.album_type)] ?? "other";
}

/** The four-digit year at the start of a release date, or null. */
export function discographyYear(releaseDate: string | null | undefined): number | null {
  if (typeof releaseDate !== "string") return null;
  const m = /^\s*(\d{4})/.exec(releaseDate);
  if (!m) return null;
  const year = Number(m[1]);
  return year > 0 ? year : null;
}

function compareAlbums(
  a: { album: DiscographyAlbum; index: number },
  b: { album: DiscographyAlbum; index: number },
): number {
  const ya = discographyYear(a.album.release_date);
  const yb = discographyYear(b.album.release_date);
  if (ya !== yb) {
    if (ya === null) return 1;
    if (yb === null) return -1;
    return ya - yb;
  }
  const ta = norm(a.album.title);
  const tb = norm(b.album.title);
  if (ta !== tb) return ta < tb ? -1 : 1;
  return a.index - b.index;
}

/** Albums, EPs, Singles, Other, in that order, empty sections left out. */
export function groupDiscography<T extends DiscographyAlbum>(
  albums: readonly T[],
): DiscographySection<T>[] {
  const buckets: Record<DiscographySectionId, { album: T; index: number }[]> = {
    albums: [],
    eps: [],
    singles: [],
    other: [],
  };
  albums.forEach((album, index) => {
    buckets[discographySectionFor(album)].push({ album, index });
  });
  return SECTION_ORDER.filter((id) => buckets[id].length > 0).map((id) => ({
    id,
    title: DISCOGRAPHY_SECTION_TITLES[id],
    albums: buckets[id].sort(compareAlbums).map((x) => x.album),
  }));
}
