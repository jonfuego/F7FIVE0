import {
  LoginThrottledError,
  TOO_MANY_ATTEMPTS,
  formatWait,
  parseRetryAfter,
  throttleMessage,
} from "../throttle";

describe("parseRetryAfter", () => {
  it("reads whole seconds", () => {
    expect(parseRetryAfter("900")).toBe(900);
    expect(parseRetryAfter(" 42 ")).toBe(42);
    expect(parseRetryAfter("1")).toBe(1);
  });

  it.each(["0", "-5", "1.5", "Wed, 21 Oct 2026 07:28:00 GMT", "soon", ""])(
    "treats %p as no usable wait",
    (value) => {
      expect(parseRetryAfter(value)).toBeNull();
    },
  );

  it("treats a missing header as no usable wait", () => {
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter(undefined)).toBeNull();
  });
});

describe("formatWait", () => {
  it("counts seconds under a minute and rounds minutes up", () => {
    expect(formatWait(1)).toBe("1 second");
    expect(formatWait(45)).toBe("45 seconds");
    expect(formatWait(59)).toBe("59 seconds");
    expect(formatWait(60)).toBe("1 minute");
    expect(formatWait(61)).toBe("2 minutes");
    expect(formatWait(125)).toBe("3 minutes");
    expect(formatWait(900)).toBe("15 minutes");
    expect(formatWait(0)).toBe("1 second");
  });
});

describe("throttleMessage", () => {
  it("says how long, in words", () => {
    expect(throttleMessage(900)).toBe("Too many attempts. Try again in 15 minutes.");
    expect(throttleMessage(30)).toBe("Too many attempts. Try again in 30 seconds.");
    expect(throttleMessage(60)).toBe("Too many attempts. Try again in 1 minute.");
  });

  it("still reads like a sentence without a wait", () => {
    for (const missing of [null, undefined, 0, -3, Number.NaN]) {
      expect(throttleMessage(missing)).toBe("Too many attempts. Try again in a few minutes.");
    }
  });

  it("never shows the raw code", () => {
    for (const wait of [900, 12, 1, null, undefined]) {
      expect(throttleMessage(wait)).not.toContain(TOO_MANY_ATTEMPTS);
    }
  });
});

describe("LoginThrottledError", () => {
  it("carries the code as its message and the server's wait", () => {
    const e = new LoginThrottledError(317);
    expect(e).toBeInstanceOf(Error);
    expect(e.message).toBe("too_many_attempts");
    expect(e.retryAfterSeconds).toBe(317);
    expect(new LoginThrottledError(null).retryAfterSeconds).toBeNull();
  });
});
