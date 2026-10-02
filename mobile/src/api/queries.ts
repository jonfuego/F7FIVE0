import { useQuery, UseQueryResult } from "@tanstack/react-query";

import { useApi } from "@/state/auth";
import type { ApiClient } from "./client";
import type {
  Album,
  OnDeckItem,
  AlbumDetail,
  Artist,
  AutoPlaylistItem,
  ArtistDetail,
  ContinueWatchingItem,
  DeviceSession,
  MediaRequest,
  Mix,
  Movie,
  Progress,
  MusicVideoArtist,
  MusicVideoArtistDetail,
  MusicVideoReleaseDetail,
  RecentItem,
  SeriesDetail,
  SearchResult,
  Series,
  SongRow,
} from "./types";

/** The list endpoints default to 200 rows; ask for the whole library like the
 * web app does (movies/series/albums cap at the server max, songs match the
 * web songs page). */
export const LIBRARY_LIMIT = 20000;
export const SONGS_LIMIT = 2000;

function useJsonQuery<T>(key: unknown[], path: string, enabled = true): UseQueryResult<T> {
  const api = useApi();
  return useQuery<T>({
    queryKey: key,
    queryFn: () => api.json<T>(path),
    enabled,
  });
}

export const useSongs = () => useJsonQuery<SongRow[]>(["songs"], `/api/songs?limit=${SONGS_LIMIT}`);
export const useAlbums = () => useJsonQuery<Album[]>(["albums"], `/api/albums?limit=${LIBRARY_LIMIT}`);
export const useArtists = () => useJsonQuery<Artist[]>(["artists"], "/api/artists");
export const useAlbum = (id: string) =>
  useJsonQuery<AlbumDetail>(["album", id], `/api/albums/${id}`, !!id);
export const useArtist = (id: string) =>
  useJsonQuery<ArtistDetail>(["artist", id], `/api/artists/${id}`, !!id);
// Mixes are the backend's generated auto-playlists. There is no list
// endpoint, so the catalogue is static and each mix is fetched on tap.
export const MIXES: Mix[] = [
  { id: "random", title: "Shuffle All", subtitle: "Random picks from the library" },
  { id: "recently-added", title: "Recently Added", subtitle: "Fresh in the library" },
  { id: "most-played", title: "Most Played", subtitle: "Your heavy rotation" },
  { id: "recently-played", title: "Recently Played", subtitle: "Back to what you had on" },
  { id: "continue-listening", title: "Continue Listening", subtitle: "Pick up where you left off" },
  { id: "never-played", title: "Never Played", subtitle: "Tracks you haven't heard yet" },
];
export const useMixes = (): UseQueryResult<Mix[]> =>
  useQuery<Mix[]>({ queryKey: ["mixes"], queryFn: () => Promise.resolve(MIXES) });

export function mapAutoPlaylistItems(items: AutoPlaylistItem[]): SongRow[] {
  return items.map((it) => ({
    id: it.track_id,
    title: it.title,
    duration_sec: it.duration_sec ?? null,
    album_id: it.album_id,
    album_title: it.album_title,
    cover_path: it.cover_path ?? null,
    artist_id: it.artist_id,
    artist_name: it.artist_name,
    media_files: [{ id: it.media_file_id }],
  }));
}

/** Fetch a simple (no path param) auto-playlist and shape it as song rows. */
export async function fetchMixSongs(api: ApiClient, mixId: string): Promise<SongRow[]> {
  const res = await api.json<{ items: AutoPlaylistItem[] }>(
    `/api/auto-playlist/${encodeURIComponent(mixId)}?limit=100`,
  );
  return mapAutoPlaylistItems(res.items);
}

/** Fetch a parameterized auto-playlist (kind + path id: by-artist, by-year,
 * by-decade, by-genre, artist-radio) as song rows. The id is encoded but the
 * slash between kind and id is preserved. */
export async function fetchAutoPlaylistById(
  api: ApiClient,
  kind: string,
  id: string,
): Promise<SongRow[]> {
  const res = await api.json<{ items: AutoPlaylistItem[] }>(
    `/api/auto-playlist/${kind}/${encodeURIComponent(id)}?limit=100`,
  );
  return mapAutoPlaylistItems(res.items);
}
export const useMovies = () => useJsonQuery<Movie[]>(["movies"], `/api/movies?limit=${LIBRARY_LIMIT}`);
export const useMovie = (id: string) =>
  useJsonQuery<Movie>(["movie", id], `/api/movies/${id}`, !!id);
export const useProgress = (mediaFileId: string) =>
  useJsonQuery<Progress | null>(["progress", mediaFileId], `/api/progress/${mediaFileId}`, !!mediaFileId);
export const useSeries = (id: string) =>
  useJsonQuery<SeriesDetail>(["series", id], `/api/series/${id}`, !!id);
export const useMusicVideoArtist = (id: string) =>
  useJsonQuery<MusicVideoArtistDetail>(["mv-artist", id], `/api/music-videos/artists/${id}`, !!id);
export const useMusicVideoRelease = (id: string) =>
  useJsonQuery<MusicVideoReleaseDetail>(["mv-release", id], `/api/music-videos/releases/${id}`, !!id);
export const useShows = () => useJsonQuery<Series[]>(["shows"], `/api/series?limit=${LIBRARY_LIMIT}`);
export const useMusicVideoArtists = () =>
  useJsonQuery<MusicVideoArtist[]>(["music-videos"], "/api/music-videos/artists");
export const useContinueWatching = () =>
  useJsonQuery<ContinueWatchingItem[]>(["continue"], "/api/continue-watching?limit=20");
export const useAllProgress = () => useJsonQuery<Progress[]>(["progress-all"], "/api/progress");
export const useOnDeck = () => useJsonQuery<OnDeckItem[]>(["on-deck"], "/api/on-deck?limit=20");
export const useRecent = () => useJsonQuery<RecentItem[]>(["recent"], "/api/recent?limit=20");
export const useMyRequests = () => useJsonQuery<MediaRequest[]>(["requests"], "/api/requests/mine");
export const useMySessions = () => useJsonQuery<DeviceSession[]>(["sessions"], "/api/sessions");

export function useSearch(q: string): UseQueryResult<SearchResult[]> {
  const api = useApi();
  const trimmed = q.trim();
  return useQuery<SearchResult[]>({
    queryKey: ["search", trimmed],
    queryFn: () => api.json<SearchResult[]>(`/api/search?q=${encodeURIComponent(trimmed)}`),
    enabled: trimmed.length > 0,
  });
}

export async function revokeSession(api: ApiClient, id: string): Promise<void> {
  await api.request(`/api/sessions/${id}`, { method: "DELETE" });
}

export async function revokeOtherSessions(api: ApiClient): Promise<void> {
  await api.request(`/api/sessions`, { method: "DELETE" });
}
