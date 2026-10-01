/** Build the artwork URL handed to react-native-track-player for the lock
 * screen / media notification.
 *
 * Android's media notification loads artwork with a bare HTTP GET (no bearer
 * header), so a relative `/api/art/...` path or a bearer-only URL would render
 * blank. The API mints a short-lived HMAC-signed absolute URL (uid/exp/sig)
 * that serves without a bearer; prefer it. Only ever return an absolute URL,
 * never a relative `/api/art/` path.
 *
 * Pure (no expo/native imports) so the player unit tests can exercise it in
 * Node. Callers pass the API base explicitly. */
export function buildTrackArtwork(opts: {
  base: string;
  /** Signed absolute art URL from the API (best: works with no bearer). */
  artUrl?: string | null;
  /** Fallback relative or absolute cover path. */
  coverPath?: string | null;
}): string | undefined {
  if (opts.artUrl && /^https?:\/\//i.test(opts.artUrl)) return opts.artUrl;
  const cover = opts.coverPath;
  if (!cover) return undefined;
  if (/^https?:\/\//i.test(cover)) return cover;
  return `${opts.base}${cover.startsWith("/") ? "" : "/"}${cover}`;
}
