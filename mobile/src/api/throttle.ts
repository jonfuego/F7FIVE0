// Sign-in lockout wording for the app, as pure helpers so jest can cover them.
// The server answers a locked-out sign-in with HTTP 429 and a `Retry-After`
// header holding the real number of seconds until the same request would be
// allowed (backend services/login_throttle.py). The login screen shows that
// wait; it never shows the raw `too_many_attempts` code.
//
// Keep in step with frontend/lib/login-errors.ts (same wording, same rounding).

/** `Retry-After` as whole seconds, or null when it is missing or not a plain
 * positive integer (the server only ever sends that form). */
export function parseRetryAfter(value: string | null | undefined): number | null {
  if (value == null) return null;
  const text = String(value).trim();
  if (!/^\d+$/.test(text)) return null;
  const seconds = Number(text);
  return seconds >= 1 && Number.isSafeInteger(seconds) ? seconds : null;
}

/** "45 seconds", "1 minute", "15 minutes". Under a minute counts seconds; from
 * a minute up it rounds the minutes up, so the wording never promises less
 * than the real wait. */
export function formatWait(seconds: number): string {
  const s = Math.max(1, Math.ceil(seconds));
  if (s < 60) return `${s} ${s === 1 ? "second" : "seconds"}`;
  const m = Math.ceil(s / 60);
  return `${m} ${m === 1 ? "minute" : "minutes"}`;
}

/** The lockout message. Without a usable wait it still reads like a sentence. */
export function throttleMessage(seconds: number | null | undefined): string {
  if (seconds == null || !(seconds >= 1)) {
    return "Too many attempts. Try again in a few minutes.";
  }
  return `Too many attempts. Try again in ${formatWait(seconds)}.`;
}

/** The login error code for a 429. `LoginError` in state/auth.tsx includes it. */
export const TOO_MANY_ATTEMPTS = "too_many_attempts";

/** Thrown for a 429 on sign-in. `message` is the code the login screen maps;
 * `retryAfterSeconds` is the server's real wait (null if it sent none). */
export class LoginThrottledError extends Error {
  constructor(readonly retryAfterSeconds: number | null) {
    super(TOO_MANY_ATTEMPTS);
    this.name = "LoginThrottledError";
  }
}
