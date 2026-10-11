// Mix pictures. The four home mixes ship a default SVG in /public/mix and an
// admin can replace it with an uploaded picture. The API reports the override
// URL (with its ?v= cache key) per mix key, or null when none is set.

export const MIX_ART_KEYS = [
  "recently-added",
  "most-played",
  "continue-listening",
  "random",
] as const;

export type MixArtKey = (typeof MIX_ART_KEYS)[number];

/** `{mix key: override URL or null}` as returned by GET /api/art/mixes. */
export type MixArtMap = Partial<Record<string, string | null>>;

export function hasMixArt(key: string): key is MixArtKey {
  return (MIX_ART_KEYS as readonly string[]).includes(key);
}

export function defaultMixArt(key: MixArtKey): string {
  return `/mix/${key}.svg`;
}

/** The picture URL for a mix: the admin's override (with its ?v= cache key)
 * when one is set, else the static default. Null for a mix that has no picture
 * slot. Callers size an override with artSized(); the default SVG needs none
 * (artSized leaves non-/api/art paths alone). */
export function mixArtSrc(
  key: string,
  overrides: MixArtMap | null | undefined,
): string | null {
  if (!hasMixArt(key)) return null;
  return overrides?.[key] || defaultMixArt(key);
}
