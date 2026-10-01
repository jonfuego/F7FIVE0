/** Offline event buffer (crit 43). Pure (no native imports) so it unit tests in
 * Node. While offline the app can't POST progress or track-plays; it buffers them
 * here and flushes on reconnect. Progress events are deduped by media_file_id
 * (only the latest position matters); track-plays accumulate (each is a distinct
 * play). The manager persists the buffer and, on reconnect, calls flush with a
 * sender; anything that fails to send is kept for the next attempt. */

export interface ProgressEvent {
  kind: "progress";
  mediaFileId: string;
  positionSec: number;
  durationSec?: number;
  /** Client timestamp (ms) for last-write-wins dedupe. */
  at: number;
}

export interface TrackPlayEvent {
  kind: "track_play";
  trackId: string;
  msPlayed: number;
  completed: boolean;
  at: number;
}

export type BufferedEvent = ProgressEvent | TrackPlayEvent;

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
  return { events: [...buffer.events, event] };
}

/** Order events for sending: progress first (so a play's completion reflects the
 * final position), then track-plays, each in timestamp order. */
export function orderedForFlush(buffer: FlushBuffer): BufferedEvent[] {
  const progress = buffer.events.filter((e): e is ProgressEvent => e.kind === "progress");
  const plays = buffer.events.filter((e): e is TrackPlayEvent => e.kind === "track_play");
  const byTime = (a: BufferedEvent, b: BufferedEvent) => a.at - b.at;
  return [...progress.sort(byTime), ...plays.sort(byTime)];
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
