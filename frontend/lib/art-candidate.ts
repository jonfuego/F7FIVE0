// Art picker candidate helpers (Edit art > Search).
//
// A candidate has two image URLs: `url` is the full-size image that applying
// downloads (the backend re-derives it from {source, ref}), `preview_url` is
// a small copy for the tile. Older servers send no `preview_url`.

export type ArtCandidate = {
  source: string;
  ref: string;
  url: string;
  preview_url?: string | null;
  label: string;
};

// The URL a tile's <img> loads first: the preview when there is one, else the
// full URL.
export function candidateTileSrc(c: Pick<ArtCandidate, "url" | "preview_url">): string {
  const p = typeof c.preview_url === "string" ? c.preview_url.trim() : "";
  return p || c.url;
}
