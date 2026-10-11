// Artist radio, shared by the player track menu and the album page.
//
// The backend builds the radio queue at /api/library/auto-playlist/artist-radio.
// This helper owns the URL and the "best-effort" rule (any failure or an empty
// answer starts nothing), and takes the fetcher and the queue action as
// arguments so it stays pure and testable. Callers pass apiGet and the queue's
// playNextBlock, which plays right away when nothing is playing and otherwise
// slots the radio in after the current track.

export type ArtistRadioDeps<T> = {
  get: (path: string) => Promise<{ items?: T[] } | null | undefined>;
  playNextBlock: (items: T[]) => void;
};

export function artistRadioPath(artistId: string): string {
  return `/api/library/auto-playlist/artist-radio/${encodeURIComponent(artistId)}`;
}

// Returns true when a radio block was handed to the queue.
export async function startArtistRadio<T>(
  artistId: string | null | undefined,
  deps: ArtistRadioDeps<T>,
): Promise<boolean> {
  if (!artistId) return false;
  try {
    const data = await deps.get(artistRadioPath(artistId));
    if (Array.isArray(data?.items) && data.items.length > 0) {
      deps.playNextBlock(data.items);
      return true;
    }
  } catch {
    // best-effort
  }
  return false;
}
