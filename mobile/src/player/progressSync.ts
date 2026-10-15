/** Queue/progress sync scheduler.
 *
 * The server's queue and progress endpoints are the source of truth. The client
 * syncs on every track change and every 15 seconds while playing (spec 6.2).
 * This class owns only the scheduling; the actual network POST is injected as
 * `report`, so it unit-tests with fake timers and no network.
 *
 * `getSnapshot` may be async: a podcast reads the position from the native
 * player (`TrackPlayer.getProgress()`), never from a JS-side cache, so a save
 * made with the screen off or on a pause from the notification is not stale.
 */

export interface ProgressSnapshot {
  /** The media file id of a track, or the episode id of a podcast episode. */
  trackId: string;
  /** "podcast" when trackId is an episode id (reported to the podcast API). */
  kind?: "podcast";
  positionSec: number;
  durationSec?: number;
  playing: boolean;
}

export interface ProgressSyncOptions {
  intervalMs?: number;
  report: (snapshot: ProgressSnapshot) => void | Promise<void>;
  getSnapshot: () => ProgressSnapshot | null | Promise<ProgressSnapshot | null>;
}

export const DEFAULT_SYNC_INTERVAL_MS = 15_000;

export class ProgressSyncer {
  private timer: ReturnType<typeof setInterval> | null = null;
  private readonly intervalMs: number;
  private readonly report: ProgressSyncOptions["report"];
  private readonly getSnapshot: ProgressSyncOptions["getSnapshot"];
  private lastReportAt = 0;

  constructor(opts: ProgressSyncOptions) {
    this.intervalMs = opts.intervalMs ?? DEFAULT_SYNC_INTERVAL_MS;
    this.report = opts.report;
    this.getSnapshot = opts.getSnapshot;
  }

  /** Begin the 15s tick. Each tick reports only while something is playing. */
  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => this.tick(), this.intervalMs);
  }

  /** Report if something is playing and nothing was reported in the last half
   * interval. The JS timer and a native progress event both call this, so a
   * stalled timer (screen off) is covered by the other without double saves. */
  tick(): void {
    if (Date.now() - this.lastReportAt < this.intervalMs / 2) return;
    this.withSnapshot((snap) => {
      if (snap.playing) this.send(snap);
    });
  }

  /** Force an immediate sync (call on every track change, and on pause). */
  flush(): void {
    this.withSnapshot((snap) => this.send(snap));
  }

  private send(snap: ProgressSnapshot): void {
    this.lastReportAt = Date.now();
    void this.report(snap);
  }

  /** Hands the snapshot to `handle`, synchronously when the source is sync. */
  private withSnapshot(handle: (snap: ProgressSnapshot) => void): void {
    let got: ReturnType<ProgressSyncOptions["getSnapshot"]>;
    try {
      got = this.getSnapshot();
    } catch {
      return;
    }
    if (got && typeof (got as Promise<ProgressSnapshot | null>).then === "function") {
      (got as Promise<ProgressSnapshot | null>).then((snap) => snap && handle(snap), () => {});
    } else if (got) {
      handle(got as ProgressSnapshot);
    }
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  get running(): boolean {
    return this.timer !== null;
  }
}
