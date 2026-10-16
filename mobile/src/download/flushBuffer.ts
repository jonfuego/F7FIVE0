/** Offline event buffer (crit 43). Pure (no native imports) so it unit tests in
 * Node. While offline the app can't POST progress or track-plays; it buffers them
 * here and flushes on reconnect. Progress events are deduped by media_file_id
 * (only the latest position matters), podcast progress by episode id the same
 * way; track-plays accumulate (each is a distinct play). The manager persists the buffer and, on reconnect, calls flush with a
 * sender; anything that fails to send is kept for the next attempt. */

export interface ProgressEvent {
  kind: "progress";
  mediaFileId: string;
  positionSec: number;
  durationSec?: number;
  /** Client timestamp (ms) for last-write-wins dedupe. */
  at: number;
}

/** Where a person got to in a podcast episode (played offline, or while the
 * server was unreachable). Only the latest position per episode matters. */
export interface PodcastProgressEvent {
  kind: "podcast_progress";
  episodeId: string;
  positionSec: number;
  durationSec?: number;
  at: number;
}

export interface TrackPlayEvent {
  kind: "track_play";
  trackId: string;
  msPlayed: number;
  completed: boolean;
  at: number;
}

export type BufferedEvent = ProgressEvent | PodcastProgressEvent | TrackPlayEvent;

export interface FlushBuffer {
  events: BufferedEvent[];
}

export function emptyBuffer(): FlushBuffer {
  return { events: [] };
}

/** Add an event. Progress events collapse to the newest per media_file_id;
 * track-plays are always appended. Returns a new buffer. */
export function addEvent(buffer: FlushBuffer, event: BufferedEvent): FlushBuffer {
  if (event.kind === "progress") {
    const rest = buffer.events.filter(
      (e) => !(e.kind === "progress" && e.mediaFileId === event.mediaFileId),
    );
    // Keep the newer of an existing (already filtered) vs incoming — since we
    // filtered out the old one, just append the incoming.
    return { events: [...rest, event] };
  }
  if (event.kind === "podcast_progress") {
    const existing = buffer.events.find(
      (e): e is PodcastProgressEvent => e.kind === "podcast_progress" && e.episodeId === event.episodeId,
    );
    // Keep whichever was taken last: a late-arriving older save must not
    // replace a newer one.
    if (existing && existing.at > event.at) return buffer;
    const rest = buffer.events.filter(
      (e) => !(e.kind === "podcast_progress" && e.episodeId === event.episodeId),
    );
    return { events: [...rest, event] };
  }
  return { events: [...buffer.events, event] };
}

/** Drop the buffered save for an episode when it was taken at or before
 * `atMs`: a newer save has reached the server, so sending the buffered one
 * later would only be refused (or, on an older server, move the place back). */
export function clearPodcastUpTo(buffer: FlushBuffer, episodeId: string, atMs: number): FlushBuffer {
  const events = buffer.events.filter(
    (e) => !(e.kind === "podcast_progress" && e.episodeId === episodeId && e.at <= atMs),
  );
  return events.length === buffer.events.length ? buffer : { events };
}

/** The latest buffered position for an episode, or null. Offline play resumes
 * from it when the server could not be asked. */
export function latestPodcastPosition(buffer: FlushBuffer, episodeId: string): number | null {
  const hit = buffer.events.find(
    (e): e is PodcastProgressEvent => e.kind === "podcast_progress" && e.episodeId === episodeId,
  );
  return hit ? hit.positionSec : null;
}

/** Order events for sending: progress first (so a play's completion reflects the
 * final position), then podcast progress, then track-plays, each in timestamp
 * order. */
export function orderedForFlush(buffer: FlushBuffer): BufferedEvent[] {
  const progress = buffer.events.filter((e): e is ProgressEvent => e.kind === "progress");
  const podcasts = buffer.events.filter((e): e is PodcastProgressEvent => e.kind === "podcast_progress");
  const plays = buffer.events.filter((e): e is TrackPlayEvent => e.kind === "track_play");
  const byTime = (a: BufferedEvent, b: BufferedEvent) => a.at - b.at;
  return [...progress.sort(byTime), ...podcasts.sort(byTime), ...plays.sort(byTime)];
}

/** Flush the buffer through an async sender. Events the sender resolves for are
 * dropped; events it rejects for are retained (returned in a new buffer) so the
 * next reconnect retries them. Returns the buffer of unsent events. */
export async function flush(
  buffer: FlushBuffer,
  send: (event: BufferedEvent) => Promise<void>,
): Promise<FlushBuffer> {
  const ordered = orderedForFlush(buffer);
  const kept: BufferedEvent[] = [];
  for (const event of ordered) {
    try {
      await send(event);
    } catch {
      kept.push(event);
    }
  }
  return { events: kept };
}
