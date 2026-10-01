/** Queue/progress sync scheduler.
 *
 * The server's queue and progress endpoints are the source of truth. The client
 * syncs on every track change and every 15 seconds while playing (spec 6.2).
 * This class owns only the scheduling; the actual network POST is injected as
 * `report`, so it unit-tests with fake timers and no network.
 */

export interface ProgressSnapshot {
  trackId: string;
  positionSec: number;
  durationSec?: number;
  playing: boolean;
}

export interface ProgressSyncOptions {
  intervalMs?: number;
  report: (snapshot: ProgressSnapshot) => void | Promise<void>;
  getSnapshot: () => ProgressSnapshot | null;
}

export const DEFAULT_SYNC_INTERVAL_MS = 15_000;

export class ProgressSyncer {
  private timer: ReturnType<typeof setInterval> | null = null;
  private readonly intervalMs: number;
  private readonly report: ProgressSyncOptions["report"];
  private readonly getSnapshot: ProgressSyncOptions["getSnapshot"];

  constructor(opts: ProgressSyncOptions) {
    this.intervalMs = opts.intervalMs ?? DEFAULT_SYNC_INTERVAL_MS;
    this.report = opts.report;
    this.getSnapshot = opts.getSnapshot;
  }

  /** Begin the 15s tick. Each tick reports only while something is playing. */
  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => {
      const snap = this.getSnapshot();
      if (snap && snap.playing) {
        void this.report(snap);
      }
    }, this.intervalMs);
  }

  /** Force an immediate sync (call on every track change, and on pause). */
  flush(): void {
    const snap = this.getSnapshot();
    if (snap) {
      void this.report(snap);
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
