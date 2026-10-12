/** An episode's state for the person looking at it, and the words for it. The
 * server sends the caller's own state with every episode (progress is per user):
 * new, in progress with a position, or played. Pure, so it unit tests in Node. */
import type { PodcastEpisodeState } from "@/api/types";

function clock(sec: number): string {
  const total = Math.max(0, Math.floor(sec));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** "New", "Played", "50 min left", "1 hr 20 min left", or "Resume at 10:00" when
 * the length is not known. */
export function episodeStateLabel(state: PodcastEpisodeState, durationSec?: number | null): string {
  if (state.kind === "new") return "New";
  if (state.kind === "played") return "Played";
  if (durationSec == null || !(durationSec > 0)) return `Resume at ${clock(state.position_sec)}`;
  const leftMin = Math.max(1, Math.ceil(Math.max(0, durationSec - state.position_sec) / 60));
  if (leftMin < 60) return `${leftMin} min left`;
  const hours = Math.floor(leftMin / 60);
  const rest = leftMin % 60;
  return rest ? `${hours} hr ${rest} min left` : `${hours} hr left`;
}

/** 0 to 1: how far through an episode the person is. */
export function progressFraction(state: PodcastEpisodeState, durationSec?: number | null): number {
  if (state.kind === "played") return 1;
  if (state.kind === "new") return 0;
  if (durationSec == null || !(durationSec > 0)) return 0;
  return Math.min(1, Math.max(0, state.position_sec / durationSec));
}

/** The episodes of a show for one filter chip. */
export type EpisodeFilter = "all" | "unplayed" | "downloaded";

export function filterEpisodes<T extends { id: string; state: PodcastEpisodeState }>(
  episodes: readonly T[],
  filter: EpisodeFilter,
  isDownloaded: (id: string) => boolean,
): T[] {
  if (filter === "unplayed") return episodes.filter((e) => e.state.kind !== "played");
  if (filter === "downloaded") return episodes.filter((e) => isDownloaded(e.id));
  return [...episodes];
}
