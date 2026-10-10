// Saved library views: the keys, their defaults and what a stored value may
// be. Views live on the server per user (GET /api/library/view-prefs, PUT
// /api/library/view-prefs/<key>, through the library BFF), so a view follows
// the person across web, phone and TV. The React hook is lib/use-view-pref.ts;
// this file is pure so node:test can cover it (view-prefs.test.ts).

export type MixInputs = Record<string, Record<string, string>>;

// The Admin section ids that can be collapsed. The admin page remembers which
// are folded per user (admin.collapsed). Keep these in sync with the ids the
// admin page gives its CollapsibleSection headers.
export const ADMIN_SECTION_IDS = [
  "users", "updates", "remote-access", "library-folders", "metadata", "library",
  "audio-analysis", "health", "active-streams", "sessions", "auth-events", "history",
] as const;

export type AdminSectionId = (typeof ADMIN_SECTION_IDS)[number];

type Spec<T> = { fallback: T; valid: (v: unknown) => v is T };

function oneOf<const T extends string>(...allowed: T[]): (v: unknown) => v is T {
  return (v: unknown): v is T => typeof v === "string" && (allowed as string[]).includes(v);
}

function shortString(v: unknown): v is string {
  return typeof v === "string" && v.length > 0 && v.length <= 64;
}

// admin.collapsed is the list of collapsed Admin section ids. Only known ids
// are kept; anything else is dropped so a stale id can't hide a section forever.
function adminCollapsed(v: unknown): v is AdminSectionId[] {
  if (!Array.isArray(v)) return false;
  const known = new Set<string>(ADMIN_SECTION_IDS);
  return v.every((x) => typeof x === "string" && known.has(x));
}

function mixInputs(v: unknown): v is MixInputs {
  if (!v || typeof v !== "object" || Array.isArray(v)) return false;
  for (const fields of Object.values(v as Record<string, unknown>)) {
    if (!fields || typeof fields !== "object" || Array.isArray(fields)) return false;
    for (const x of Object.values(fields as Record<string, unknown>)) {
      if (typeof x !== "string" || x.length > 64) return false;
    }
  }
  return true;
}

export const VIEW_PREFS = {
  // Music browse tab: /music (Artists), /music/albums, /music/songs.
  "music.browse": { fallback: "artists", valid: oneOf("artists", "albums", "songs") } as Spec<"artists" | "albums" | "songs">,
  // Movies genre chip ("All" or a genre name) and sort.
  "movies.genre": { fallback: "All", valid: shortString } as Spec<string>,
  "movies.sort": { fallback: "title", valid: oneOf("title", "year", "rating") } as Spec<"title" | "year" | "rating">,
  // TV status filter.
  "tv.status": { fallback: "All", valid: oneOf("All", "Watching", "Complete", "New") } as Spec<"All" | "Watching" | "Complete" | "New">,
  // Music Videos artist order.
  "musicvideos.sort": { fallback: "name", valid: oneOf("name", "videos") } as Spec<"name" | "videos">,
  // Mixes: the last values typed into each mix's picker (year, decade, genre...).
  "mixes.inputs": { fallback: {}, valid: mixInputs } as Spec<MixInputs>,
  // Admin page: the list of collapsed section ids (nothing collapsed by default).
  "admin.collapsed": { fallback: [], valid: adminCollapsed } as Spec<AdminSectionId[]>,
};

export type ViewPrefKey = keyof typeof VIEW_PREFS;
export type ViewPrefValue<K extends ViewPrefKey> = (typeof VIEW_PREFS)[K]["fallback"];

/** The stored value when it is valid for the key, else the key's default. */
export function resolveViewPref<K extends ViewPrefKey>(key: K, stored: unknown): ViewPrefValue<K> {
  const spec = VIEW_PREFS[key] as unknown as Spec<ViewPrefValue<K>>;
  return spec.valid(stored) ? stored : spec.fallback;
}

/** All known views from the server's {key: value} map, defaults filled in;
 * unknown or invalid entries are ignored. */
export function mergeViewPrefs(stored: Record<string, unknown> | null | undefined): {
  [K in ViewPrefKey]: ViewPrefValue<K>;
} {
  const out = {} as { [K in ViewPrefKey]: ViewPrefValue<K> };
  for (const key of Object.keys(VIEW_PREFS) as ViewPrefKey[]) {
    (out as Record<string, unknown>)[key] = resolveViewPref(key, stored?.[key]);
  }
  return out;
}

/** Path of one view on the BFF. */
export function viewPrefPath(key: ViewPrefKey): string {
  return `/api/library/view-prefs/${encodeURIComponent(key)}`;
}

export const VIEW_PREFS_PATH = "/api/library/view-prefs";
