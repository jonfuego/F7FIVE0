import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useApi } from "@/state/auth";
import { queryClient } from "@/state/query";
import type { ApiClient } from "./client";
import type {
  PodcastChapter,
  PodcastDetail,
  PodcastHome,
  PodcastSearch,
  PodcastShow,
  PodcastStreamStart,
  PodcastEpisodeState,
} from "./types";

/** Podcast API (all per signed-in user: subscriptions and progress are theirs). */

function usePodcastQuery<T>(key: unknown[], path: string, enabled = true): UseQueryResult<T> {
  const api = useApi();
  return useQuery<T>({ queryKey: key, queryFn: () => api.json<T>(path), enabled });
}

/** In progress, My podcasts, On this server. */
export const usePodcastHome = () => usePodcastQuery<PodcastHome>(["podcasts"], "/api/podcasts");

/** One show and its episodes, newest first, with the caller's own state. */
export const usePodcast = (id: string) =>
  usePodcastQuery<PodcastDetail>(["podcast", id], `/api/podcasts/${encodeURIComponent(id)}?limit=500`, !!id);

/** Chapters of the episode playing (the feed JSON or the ones in the server file). */
export const usePodcastChapters = (episodeId: string | undefined, enabled = true) =>
  usePodcastQuery<PodcastChapter[]>(
    ["podcast-chapters", episodeId],
    `/api/podcasts/episodes/${encodeURIComponent(episodeId ?? "")}/chapters`,
    !!episodeId && enabled,
  );

/** Shows, episodes and progress change together; refetch them all. */
export function invalidatePodcasts(): void {
  void queryClient.invalidateQueries({ queryKey: ["podcasts"] });
  void queryClient.invalidateQueries({ queryKey: ["podcast"] });
}

const JSON_HEADERS = { "content-type": "application/json" };

export async function searchPodcasts(api: ApiClient, q: string): Promise<PodcastSearch> {
  return api.json<PodcastSearch>(`/api/podcasts/search?q=${encodeURIComponent(q)}`);
}

/** Follow a show by its feed URL (fetched now) or, for a show found in a
 * podcasts folder, by its id. */
export async function subscribe(
  api: ApiClient,
  target: { feedUrl: string } | { podcastId: string },
): Promise<PodcastShow> {
  const body = "feedUrl" in target ? { feed_url: target.feedUrl } : { podcast_id: target.podcastId };
  const show = await api.json<PodcastShow>("/api/podcasts/subscribe", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
  invalidatePodcasts();
  return show;
}

export async function unsubscribe(api: ApiClient, podcastId: string): Promise<void> {
  await api.request(`/api/podcasts/${encodeURIComponent(podcastId)}/subscription`, { method: "DELETE" });
  invalidatePodcasts();
}

export async function setAutoDownload(api: ApiClient, podcastId: string, on: boolean): Promise<void> {
  await api.json(`/api/podcasts/${encodeURIComponent(podcastId)}/subscription`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify({ auto_download: on }),
  });
  invalidatePodcasts();
}

/** A signed, session-bound /stream/podcast URL, plus where the caller left off. */
export async function startPodcastStream(api: ApiClient, episodeId: string): Promise<PodcastStreamStart> {
  return api.json<PodcastStreamStart>(`/api/podcasts/episodes/${encodeURIComponent(episodeId)}/stream`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: "{}",
  });
}

/** The shape the download manager wants: a signed URL and the file type. The
 * download goes through the same /stream/podcast URL, so it works whether or not
 * the server has the file. */
export async function fetchPodcastDownloadUrl(
  api: ApiClient,
  episodeId: string,
): Promise<{ url: string; container?: string | null }> {
  const s = await startPodcastStream(api, episodeId);
  return { url: s.url, container: s.container };
}

/** Save the caller's position; the server decides played (within 30 s of the
 * end or past 95 percent). `recordedAtMs` is when the position was read: the
 * server ignores a save older than the one it has, so a late retry or an
 * offline replay never moves the place back. `client` names the path that sent
 * it, for the server log. */
export async function reportPodcastProgress(
  api: ApiClient,
  episodeId: string,
  positionSec: number,
  durationSec?: number,
  opts: { recordedAtMs?: number; client?: string } = {},
): Promise<void> {
  await api.request(`/api/podcasts/episodes/${encodeURIComponent(episodeId)}/progress`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      position_sec: Math.max(0, Math.floor(positionSec)),
      duration_sec: durationSec && durationSec >= 1 ? Math.floor(durationSec) : undefined,
      recorded_at_ms: opts.recordedAtMs !== undefined ? Math.floor(opts.recordedAtMs) : undefined,
      client: opts.client,
    }),
  });
}

/** Mark an episode played or unplayed by hand. */
export async function setEpisodePlayed(
  api: ApiClient,
  episodeId: string,
  played: boolean,
): Promise<PodcastEpisodeState> {
  const res = await api.json<{ state: PodcastEpisodeState }>(
    `/api/podcasts/episodes/${encodeURIComponent(episodeId)}/played`,
    { method: played ? "POST" : "DELETE" },
  );
  invalidatePodcasts();
  return res.state;
}

/** Ask the server to download an episode into its podcasts library. 409
 * `no_podcast_folder` means an admin has not set a folder up. */
export async function requestServerDownload(api: ApiClient, episodeId: string): Promise<void> {
  await api.request(`/api/podcasts/episodes/${encodeURIComponent(episodeId)}/download`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: "{}",
  });
  invalidatePodcasts();
}
