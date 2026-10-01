/** On Deck selection (crit 38). Pure (no native imports) so it unit tests in
 * Node. "On Deck" = the next episode to watch for a series: the first episode in
 * season/episode order that is not yet completed. If the viewer is mid-episode
 * (has progress but not completed) that in-progress episode is on deck; otherwise
 * it's the first unstarted episode after the last completed one. */

export interface OnDeckEpisode {
  id: string;
  season_number: number;
  episode_number: number;
  title?: string | null;
  media_files: { id: string }[];
}

export interface OnDeckProgress {
  /** Seconds watched. */
  position_sec: number;
  /** Non-null when the episode is marked complete. */
  completed_at?: string | null;
}

/** progressMap is keyed by media_file_id. */
export type ProgressMap = Record<string, OnDeckProgress | undefined>;

/** Sort episodes by season then episode number (ascending). Returns a new array. */
export function sortEpisodes<T extends { season_number: number; episode_number: number }>(episodes: T[]): T[] {
  return [...episodes].sort((a, b) =>
    a.season_number !== b.season_number
      ? a.season_number - b.season_number
      : a.episode_number - b.episode_number,
  );
}

function firstFileId(ep: OnDeckEpisode): string | undefined {
  return ep.media_files[0]?.id;
}

function isCompleted(ep: OnDeckEpisode, progress: ProgressMap): boolean {
  const id = firstFileId(ep);
  if (!id) return false;
  return !!progress[id]?.completed_at;
}

function isInProgress(ep: OnDeckEpisode, progress: ProgressMap): boolean {
  const id = firstFileId(ep);
  if (!id) return false;
  const p = progress[id];
  return !!p && !p.completed_at && p.position_sec > 0;
}

/** The next episode to watch for a series, or null when everything is watched or
 * there are no playable episodes.
 *
 * Rules (Plex "On Deck" semantics):
 *  1. If an episode is in progress (started, not completed), it is on deck
 *     (resume where you left off) — the earliest such episode.
 *  2. Otherwise the first episode after the last completed one that hasn't been
 *     started. If nothing is completed, that's the very first episode.
 *  3. If every episode is completed, returns null (series finished).
 *  Specials (season 0) are skipped when the series has regular seasons. */
export function nextUnwatchedEpisode(
  episodes: OnDeckEpisode[],
  progress: ProgressMap,
): OnDeckEpisode | null {
  const withFiles = episodes.filter((e) => firstFileId(e));
  // Specials (season 0) are ignored unless they're all the series has (Plex).
  const regular = withFiles.filter((e) => e.season_number > 0);
  const playable = sortEpisodes(regular.length > 0 ? regular : withFiles);
  if (playable.length === 0) return null;

  // Rule 1: earliest in-progress episode.
  const inProgress = playable.find((e) => isInProgress(e, progress));
  if (inProgress) return inProgress;

  // Rule 2: first not-completed episode (nothing started).
  const firstUnwatched = playable.find((e) => !isCompleted(e, progress));
  return firstUnwatched ?? null;
}

/** A continue-watching item, minimal shape for the On Deck rail. */
export interface OnDeckCandidate {
  kind: string;
  position_sec: number;
  duration_sec?: number | null;
}

/** Derive the Home "On Deck" rail from continue-watching (crit 38). On Deck is
 * the episodic queue: TV episodes/series in progress (or the very start), i.e.
 * items whose kind is episodic and that aren't essentially finished. Movies stay
 * in plain Continue Watching. Pure so it unit tests. */
export function deriveOnDeck<T extends OnDeckCandidate>(items: T[]): T[] {
  const NEARLY_DONE = 0.97;
  return items.filter((it) => {
    const episodic = it.kind === "episode" || it.kind === "series" || it.kind === "show";
    if (!episodic) return false;
    if (it.duration_sec && it.duration_sec > 0) {
      return it.position_sec / it.duration_sec < NEARLY_DONE;
    }
    return true;
  });
}
