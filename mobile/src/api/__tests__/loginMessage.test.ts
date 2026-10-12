import { loginMessage } from "../loginMessage";
import { LoginThrottledError } from "../throttle";

describe("loginMessage", () => {
  it("a 429 lockout says how long, from the server's wait", () => {
    expect(loginMessage(new LoginThrottledError(900))).toBe("Too many attempts. Try again in 15 minutes.");
    expect(loginMessage(new LoginThrottledError(45))).toBe("Too many attempts. Try again in 45 seconds.");
  });

  it("a 429 with no wait still reads like a sentence", () => {
    expect(loginMessage(new LoginThrottledError(null))).toBe("Too many attempts. Try again in a few minutes.");
    expect(loginMessage(new Error("too_many_attempts"))).toBe("Too many attempts. Try again in a few minutes.");
  });

  it("never shows the raw code", () => {
    for (const err of [new LoginThrottledError(12), new LoginThrottledError(null), new Error("too_many_attempts")]) {
      expect(loginMessage(err)).not.toContain("too_many_attempts");
    }
  });

  it("keeps the other sign-in messages", () => {
    expect(loginMessage(new Error("invalid_credentials"))).toBe("That username or password is incorrect.");
    expect(loginMessage(new Error("unreachable"))).toBe(
      "Can't reach that server. Check the address and your connection.",
    );
    expect(loginMessage(new Error("unknown"))).toBe("Something went wrong signing in. Please try again.");
    expect(loginMessage("boom")).toBe("Something went wrong signing in. Please try again.");
  });
});
