// Text for a failed sign-in on the login screen, as a pure function so jest can
// cover it. `err` is whatever the sign-in threw: a LoginThrottledError (HTTP
// 429, carries the server's wait) or an Error whose message is a LoginError
// code from state/auth.tsx. The raw `too_many_attempts` code is never shown.
import { LoginThrottledError, throttleMessage } from "./throttle";

export function loginMessage(err: unknown): string {
  if (err instanceof LoginThrottledError) return throttleMessage(err.retryAfterSeconds);
  const code = err instanceof Error ? err.message : String(err ?? "unknown");
  if (code === "too_many_attempts") return throttleMessage(null);
  if (code === "invalid_credentials") return "That username or password is incorrect.";
  if (code === "unreachable") return "Can't reach that server. Check the address and your connection.";
  return "Something went wrong signing in. Please try again.";
}
