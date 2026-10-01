/** Android Auto media browse tree (crit 44). Pure (no native imports) so it unit
 * tests in Node. Defines the root categories a car head unit shows and how each
 * maps to an app data source. The native media session (registered in the
 * playback service) serves children on demand; this module is the single source
 * of truth for the tree shape so both the service and tests agree.
 *
 * The DHU (Desktop Head Unit) screenshot is the orchestrator's job; this gets the
 * browsable structure + ids into code. */

export interface BrowseNode {
  /** Stable media id the head unit requests children for. */
  id: string;
  title: string;
  /** true = a browsable folder; false = a playable leaf. */
  browsable: boolean;
  /** For browsable roots, how the service should populate children. */
  source?: BrowseSource;
}

/** How a browsable node's children are fetched at request time. */
export type BrowseSource =
  | { kind: "recent" } // Recently Played (auto-playlist)
  | { kind: "mixes" } // The Mixes catalogue
  | { kind: "albums" } // /api/albums
  | { kind: "artists" } // /api/artists
  | { kind: "downloads" } // local downloads (offline-safe)
  | { kind: "home" }; // Home shortcuts (Continue + Recent)

export const ROOT_ID = "__root__";

/** The fixed root categories the car shows (spec crit 44 list). Order matters —
 * it's the order they appear in the head unit. */
export function rootChildren(): BrowseNode[] {
  return [
    { id: "home", title: "Home", browsable: true, source: { kind: "home" } },
    { id: "recent", title: "Recently Played", browsable: true, source: { kind: "recent" } },
    { id: "mixes", title: "Mixes", browsable: true, source: { kind: "mixes" } },
    { id: "albums", title: "Albums", browsable: true, source: { kind: "albums" } },
    { id: "artists", title: "Artists", browsable: true, source: { kind: "artists" } },
    { id: "downloads", title: "Downloads", browsable: true, source: { kind: "downloads" } },
  ];
}

/** The full browse tree root node. */
export function browseRoot(): BrowseNode {
  return { id: ROOT_ID, title: "F7FIVE0", browsable: true };
}

/** Look up a root category node by id (what the service uses to route a
 * children request to a data source). Null for unknown ids. */
export function findRoot(id: string): BrowseNode | null {
  if (id === ROOT_ID) return browseRoot();
  return rootChildren().find((n) => n.id === id) ?? null;
}

/** The browse source for a requested parent id, or null when it's not a known
 * root (the service then returns no children). */
export function sourceFor(parentId: string): BrowseSource | null {
  if (parentId === ROOT_ID) return null; // root children are the fixed list
  return findRoot(parentId)?.source ?? null;
}

// ---------------------------------------------------------------------------
// Children + media ids for the native browse service (modules/f7five0-auto).
// ---------------------------------------------------------------------------

/** One entry the native service turns into a MediaBrowserCompat.MediaItem. */
export interface AutoItem {
  id: string;
  title: string;
  subtitle?: string | null;
  artUri?: string | null;
  browsable: boolean;
}

/** A playable leaf id is `<listKey>#<index>`: the list it came from (so the
 * whole list can be queued, like tapping a row in the app) plus the position. */
export function playableId(listKey: string, index: number): string {
  return `${listKey}#${index}`;
}

export function parsePlayableId(mediaId: string): { listKey: string; index: number } | null {
  const hash = mediaId.lastIndexOf("#");
  if (hash <= 0) return null;
  const index = Number(mediaId.slice(hash + 1));
  if (!Number.isInteger(index) || index < 0) return null;
  return { listKey: mediaId.slice(0, hash), index };
}

/** Browsable folder ids below the root categories. */
export const folderId = {
  mix: (slug: string) => `mix:${slug}`,
  album: (id: string) => `album:${id}`,
  artist: (id: string) => `artist:${id}`,
};

/** What a (non-root) parent id refers to. List keys double as parent ids for
 * song lists, so `album:<id>` is both the folder and the list key. */
export type ParentRef =
  | { kind: "category"; source: BrowseSource }
  | { kind: "mix"; slug: string }
  | { kind: "album"; id: string }
  | { kind: "artist"; id: string };

export function parseParent(parentId: string): ParentRef | null {
  const src = sourceFor(parentId);
  if (src) return { kind: "category", source: src };
  const m = /^(mix|album|artist):(.+)$/.exec(parentId);
  if (!m) return null;
  if (m[1] === "mix") return { kind: "mix", slug: m[2] };
  if (m[1] === "album") return { kind: "album", id: m[2] };
  return { kind: "artist", id: m[2] };
}

/** Playable items for a song list under `listKey`. */
export function songItems(
  listKey: string,
  songs: { title: string; artist_name?: string | null; album_title?: string | null }[],
  limit = 100,
): AutoItem[] {
  return songs.slice(0, limit).map((s, i) => ({
    id: playableId(listKey, i),
    title: s.title,
    subtitle: [s.artist_name, s.album_title].filter(Boolean).join(" · ") || null,
    browsable: false,
  }));
}
