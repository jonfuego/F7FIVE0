// Pure action logic for the player 3-dot menu (shared by the mini player and
// Now Playing). Kept free of React and TrackPlayer so it can be unit tested:
// the component injects the router push, the Now Playing close, the album /
// artist-radio loaders, and the queue mutators.
//
// Go to album / Go to artist only navigate. They close Now Playing first and
// then push the route; they never pause, stop, or reset playback, so the music
// keeps going while the screen changes behind the push.

import type { SongRow } from "@/api/types";

// The (tabs) group is not a URL segment, so the href omits it, matching every
// other album / artist navigation in the app (albums.tsx, artists.tsx, ...).

/** Route for an album detail screen. */
export function albumRoute(albumId: string): string {
  return `/music/album/${albumId}`;
}

/** Route for an artist detail screen. */
export function artistRoute(artistId: string): string {
  return `/music/artist/${artistId}`;
}

export interface PlayerMenuDeps {
  albumId: string | null;
  artistId: string | null;
  /** router.push */
  navigate: (path: string) => void;
  /** Close Now Playing before a navigation (router.back on the modal, no-op on
   * the mini player). */
  closeNowPlaying: () => void;
  /** Fetch the current album's tracks as song rows. */
  loadAlbumSongs: () => Promise<SongRow[]>;
  /** Fetch an artist-radio auto-playlist as song rows. */
  loadArtistRadio: () => Promise<SongRow[]>;
  /** Queue songs right after the current track. */
  playNext: (songs: SongRow[]) => void | Promise<void>;
  /** Append songs to the end of the queue. */
  addToQueue: (songs: SongRow[]) => void | Promise<void>;
}

export interface PlayerMenuActions {
  playAlbumNext: () => Promise<void>;
  goToAlbum: () => void;
  goToArtist: () => void;
  artistRadio: () => Promise<void>;
  addAlbumToQueue: () => Promise<void>;
}

export function createPlayerMenuActions(deps: PlayerMenuDeps): PlayerMenuActions {
  return {
    async playAlbumNext() {
      if (!deps.albumId) return;
      const songs = await deps.loadAlbumSongs();
      if (songs.length > 0) await deps.playNext(songs);
    },
    goToAlbum() {
      if (!deps.albumId) return;
      deps.closeNowPlaying();
      deps.navigate(albumRoute(deps.albumId));
    },
    goToArtist() {
      if (!deps.artistId) return;
      deps.closeNowPlaying();
      deps.navigate(artistRoute(deps.artistId));
    },
    async artistRadio() {
      if (!deps.artistId) return;
      const songs = await deps.loadArtistRadio();
      if (songs.length > 0) await deps.playNext(songs);
    },
    async addAlbumToQueue() {
      if (!deps.albumId) return;
      const songs = await deps.loadAlbumSongs();
      if (songs.length > 0) await deps.addToQueue(songs);
    },
  };
}
