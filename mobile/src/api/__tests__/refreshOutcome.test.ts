import {
  REFRESH_RETRY_DELAYS_MS,
  decideRefresh,
  retryDelayMs,
  type RefreshOutcome,
} from "../refreshOutcome";

const res = (status: number): RefreshOutcome => ({ kind: "response", status });
const networkError: RefreshOutcome = { kind: "network-error" };
const timeout: RefreshOutcome = { kind: "timeout" };

describe("decideRefresh", () => {
  it("401 signs out, even with retries left", () => {
    expect(decideRefresh(res(401), 0)).toBe("sign-out");
    expect(decideRefresh(res(401), 2)).toBe("sign-out");
  });

  it("2xx is success", () => {
    expect(decideRefresh(res(200))).toBe("refreshed");
    expect(decideRefresh(res(204))).toBe("refreshed");
  });

  it.each([500, 502, 503, 504, 530])(
    "%i does not sign out: retries, then keeps the session",
    (status) => {
      expect(decideRefresh(res(status), 0)).toBe("retry");
      expect(decideRefresh(res(status), 1)).toBe("retry");
      expect(decideRefresh(res(status), 2)).toBe("keep-session");
    },
  );

  it("a network error does not sign out: retries, then keeps the session", () => {
    expect(decideRefresh(networkError, 0)).toBe("retry");
    expect(decideRefresh(networkError, 1)).toBe("retry");
    expect(decideRefresh(networkError, 2)).toBe("keep-session");
  });

  it("a timeout does not sign out: retries, then keeps the session", () => {
    expect(decideRefresh(timeout, 0)).toBe("retry");
    expect(decideRefresh(timeout, 2)).toBe("keep-session");
  });

  it("408 and 429 are treated as try again", () => {
    expect(decideRefresh(res(408), 0)).toBe("retry");
    expect(decideRefresh(res(429), 0)).toBe("retry");
    expect(decideRefresh(res(429), 2)).toBe("keep-session");
  });

  it.each([400, 403, 404, 422])("%i never signs out and is not retried", (status) => {
    expect(decideRefresh(res(status), 0)).toBe("keep-session");
  });

  it("retry delays are 0.5 s then 1.5 s", () => {
    expect(REFRESH_RETRY_DELAYS_MS).toEqual([500, 1500]);
    expect(retryDelayMs(0)).toBe(500);
    expect(retryDelayMs(1)).toBe(1500);
  });
});
