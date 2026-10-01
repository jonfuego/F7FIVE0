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
