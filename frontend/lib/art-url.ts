// Sized art URLs. The API keeps 300 and 600 px wide WebP copies of every
// image and serves one when the URL carries `w=300` or `w=600` (anything else
// returns the original). Grids and rails ask for 300; large tiles ask for 600;
// hero and detail art use the original. The `?v=` cache key is kept.
//
// Only same-origin /api/art paths are touched; remote URLs and null pass
// through unchanged.

export type ArtWidth = 300 | 600;

export function artSized(path: string | null | undefined, w: ArtWidth): string | null {
  if (!path) return null;
  if (!path.startsWith("/api/art/")) return path;
  const [base, query = ""] = path.split("?", 2);
  const params = new URLSearchParams(query);
  params.set("w", String(w));
  return `${base}?${params.toString()}`;
}
