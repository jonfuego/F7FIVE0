// Pure decisions for the web cast hand-off (no React, no DOM, so node:test can
// run them). The Player mints a separate stream for the receiver; these map
// positions between three clocks: the source movie, the local stream (an HLS
// resume starts its element clock at the encode's bucket) and the cast stream
// (the same, with its own bucket).

export type CastTimeline = {
  mode: "direct" | "hls";
  timeline_offset_sec?: number;
  offset_sec?: number;
};

/** Source second at which a stream's own clock reads 0. Direct play is
 * absolute. Falls back to offset_sec for an older backend. */
export function timelineBase(s: CastTimeline): number {
  if (s.mode !== "hls") return 0;
  const base = s.timeline_offset_sec ?? s.offset_sec ?? 0;
  return base > 0 ? base : 0;
}

/** Body for the stream the receiver gets: its own encode identity, started at
 * the viewer's current source second. */
export function castMintBody(
  fileId: string,
  atSourceSec: number,
): { file_id: string; resume_sec?: number; purpose: "cast" } {
  const body: { file_id: string; resume_sec?: number; purpose: "cast" } = {
    file_id: fileId,
    purpose: "cast",
  };
  const at = Math.floor(atSourceSec);
  if (Number.isFinite(at) && at > 0) body.resume_sec = at;
  return body;
}

/** Where the receiver starts, in the cast stream's own clock. Undefined at the
 * very start so the load request carries no startTime. */
export function castStartTime(atSourceSec: number, castStream: CastTimeline): number | undefined {
  const rel = Math.floor(atSourceSec - timelineBase(castStream));
  return rel > 0 ? rel : undefined;
}

/** The receiver's duration in its own clock (the stream is the movie minus its
 * bucket). Null when the length is unknown. */
export function castDurationSec(
  sourceDurationSec: number | null | undefined,
  castStream: CastTimeline,
): number | null {
  if (!sourceDurationSec || sourceDurationSec <= 0) return null;
  const d = sourceDurationSec - timelineBase(castStream);
  return d > 0 ? d : null;
}

/** The receiver's place as a source second. */
export function receiverSourceSec(receiverSec: number, castStream: CastTimeline): number {
  return timelineBase(castStream) + Math.max(0, receiverSec);
}

/** The local element time to resume at after the session ends: the receiver's
 * last place mapped onto the local stream's clock, else the local element's own
 * time. Never negative. */
export function localResumeSec(
  lastReceiverSec: number | null | undefined,
  castStream: CastTimeline,
  localStream: CastTimeline,
  localElementSec: number,
): number {
  if (lastReceiverSec != null && Number.isFinite(lastReceiverSec) && lastReceiverSec > 0) {
    const el = receiverSourceSec(lastReceiverSec, castStream) - timelineBase(localStream);
    return el > 0 ? el : 0;
  }
  return Number.isFinite(localElementSec) && localElementSec > 0 ? localElementSec : 0;
}
