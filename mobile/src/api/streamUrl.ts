/** Expired-URL recovery for playback (spec Q2, Option A + recovery).
 *
 * Signed stream URLs are fetched right before each track/video starts. If the
 * player reports a load error (a 401/403 on the signed URL, or an engine load
 * failure), re-sign ONCE and retry. If the retry also fails, surface the error.
 *
 * Pure and injectable so it unit-tests without a real player.
 */

export interface SignedStream {
  url: string;
  mode: "direct" | "hls";
}

/** Run `tryPlay` with a freshly-signed URL. On failure, re-sign once and retry.
 * A second failure propagates. Returns whatever `tryPlay` resolves to. */
export async function playWithUrlRecovery<T>(
  getSignedUrl: () => Promise<SignedStream>,
  tryPlay: (stream: SignedStream) => Promise<T>,
): Promise<T> {
  const first = await getSignedUrl();
  try {
    return await tryPlay(first);
  } catch (firstError) {
    // Re-sign and retry exactly once.
    let fresh: SignedStream;
    try {
      fresh = await getSignedUrl();
    } catch {
      // Couldn't even re-sign: surface the original playback error.
      throw firstError;
    }
    return await tryPlay(fresh);
  }
}
