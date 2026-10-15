import { ProgressSnapshot, ProgressSyncer } from "../progressSync";

describe("ProgressSyncer 15-second sync", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  function playing(pos: number): ProgressSnapshot {
    return { trackId: "t1", positionSec: pos, durationSec: 200, playing: true };
  }

  it("reports every 15 seconds while playing", () => {
    const report = jest.fn();
    let pos = 0;
    const syncer = new ProgressSyncer({
      report,
      getSnapshot: () => playing((pos += 15)),
    });
    syncer.start();
    jest.advanceTimersByTime(45_000);
    expect(report).toHaveBeenCalledTimes(3);
    syncer.stop();
  });

  it("does not report while paused", () => {
    const report = jest.fn();
    const syncer = new ProgressSyncer({
      report,
      getSnapshot: () => ({ trackId: "t1", positionSec: 10, playing: false }),
    });
    syncer.start();
    jest.advanceTimersByTime(60_000);
    expect(report).not.toHaveBeenCalled();
    syncer.stop();
  });

  it("flush() reports immediately (used on every track change)", () => {
    const report = jest.fn();
    const syncer = new ProgressSyncer({
      report,
      getSnapshot: () => playing(42),
    });
    syncer.flush();
    expect(report).toHaveBeenCalledTimes(1);
    expect(report).toHaveBeenCalledWith(expect.objectContaining({ positionSec: 42 }));
  });

  it("stop() halts further reporting", () => {
    const report = jest.fn();
    const syncer = new ProgressSyncer({ report, getSnapshot: () => playing(1) });
    syncer.start();
    jest.advanceTimersByTime(15_000);
    expect(report).toHaveBeenCalledTimes(1);
    syncer.stop();
    jest.advanceTimersByTime(60_000);
    expect(report).toHaveBeenCalledTimes(1);
  });

  it("uses a custom interval when provided", () => {
    const report = jest.fn();
    const syncer = new ProgressSyncer({
      report,
      intervalMs: 5_000,
      getSnapshot: () => playing(1),
    });
    syncer.start();
    jest.advanceTimersByTime(15_000);
    expect(report).toHaveBeenCalledTimes(3);
    syncer.stop();
  });
});

describe("ProgressSyncer with an async (native) source", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("a flush reports the native position, not a stale cached one", async () => {
    // The JS-side cache froze at 120 s (screen off); the native player is at 410 s.
    const cached = { position: 120 };
    const native = { position: 410 };
    const report = jest.fn();
    const syncer = new ProgressSyncer({
      report,
      getSnapshot: async () => ({
        trackId: "ep1",
        kind: "podcast",
        positionSec: native.position,
        durationSec: 3000,
        playing: false,
      }),
    });
    syncer.flush();
    await Promise.resolve();
    await Promise.resolve();
    expect(report).toHaveBeenCalledTimes(1);
    expect(report).toHaveBeenCalledWith(expect.objectContaining({ trackId: "ep1", positionSec: 410 }));
    expect(report).not.toHaveBeenCalledWith(expect.objectContaining({ positionSec: cached.position }));
  });

  it("the timer tick reads the native position each time", async () => {
    let native = 0;
    const report = jest.fn();
    const syncer = new ProgressSyncer({
      report,
      getSnapshot: async () => ({ trackId: "ep1", positionSec: (native += 15), playing: true }),
    });
    syncer.start();
    await jest.advanceTimersByTimeAsync(30_000);
    expect(report.mock.calls.map((c) => c[0].positionSec)).toEqual([15, 30]);
    syncer.stop();
  });

  it("tick() skips a save right after another one, so the timer and a native event do not double up", async () => {
    const report = jest.fn();
    const syncer = new ProgressSyncer({
      report,
      getSnapshot: async () => ({ trackId: "ep1", positionSec: 5, playing: true }),
    });
    syncer.tick();
    await jest.advanceTimersByTimeAsync(0);
    syncer.tick();
    await jest.advanceTimersByTimeAsync(0);
    expect(report).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(8_000);
    syncer.tick();
    await jest.advanceTimersByTimeAsync(0);
    expect(report).toHaveBeenCalledTimes(2);
  });

  it("a snapshot that fails does not report or throw", async () => {
    const report = jest.fn();
    const syncer = new ProgressSyncer({
      report,
      getSnapshot: () => Promise.reject(new Error("player not ready")),
    });
    syncer.flush();
    await jest.advanceTimersByTimeAsync(0);
    expect(report).not.toHaveBeenCalled();
  });
});
