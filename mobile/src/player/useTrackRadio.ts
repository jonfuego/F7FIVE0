import { useCallback } from "react";

import { fetchTrackRadio } from "@/api/media";
import { mapAutoPlaylistItems } from "@/api/queries";
import { useApi } from "@/state/auth";
import { usePlayer } from "./PlayerProvider";

/** Start a sonic "Track radio" seeded by a track (crit 48). Fetches the
 * track-radio auto-playlist from the backend and hands it to the player. Returns
 * a callback so song rows and now-playing can share one implementation. */
export function useTrackRadio(): (trackId: string) => Promise<void> {
  const api = useApi();
  const { playSongs } = usePlayer();
  return useCallback(
    async (trackId: string) => {
      const items = await fetchTrackRadio(api, trackId, 100).catch(() => []);
      const songs = mapAutoPlaylistItems(items);
      if (songs.length === 0) return;
      await playSongs(songs, 0);
    },
    [api, playSongs],
  );
}
