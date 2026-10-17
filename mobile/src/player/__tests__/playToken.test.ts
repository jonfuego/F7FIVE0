import { createPlayTokenSource } from "../playToken";

describe("play token", () => {
  it("is current until a newer one is taken", () => {
    const src = createPlayTokenSource();
    const a = src.take();
    expect(a.isCurrent()).toBe(true);
  });

  it("makes the older token stale when a newer one is taken", () => {
    const src = createPlayTokenSource();
    const a = src.take();
    const b = src.take();
    expect(a.isCurrent()).toBe(false);
    expect(b.isCurrent()).toBe(true);
    expect(b.id).toBeGreaterThan(a.id);
  });

  it("keeps only the latest of several taps current", () => {
    const src = createPlayTokenSource();
    const tokens = [src.take(), src.take(), src.take()];
    expect(tokens.map((t) => t.isCurrent())).toEqual([false, false, true]);
  });

  it("keeps sources independent", () => {
    const one = createPlayTokenSource();
    const two = createPlayTokenSource();
    const a = one.take();
    two.take();
    expect(a.isCurrent()).toBe(true);
  });
});
