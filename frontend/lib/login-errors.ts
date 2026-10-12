// Sign-in error wording for the login page, as pure helpers so node:test can
// cover them. The backend answers a locked-out sign-in with HTTP 429, the code
// `too_many_attempts` and a `Retry-After` header holding the real number of
// seconds until the same request would be allowed (services/login_throttle.py).
// The BFF forwards that header; the page turns it into words and a countdown.
// The raw code is never shown to a person.
//
// Keep in step with mobile/src/api/throttle.ts (same wording, same rounding).

/** `Retry-After` as whole seconds, or null when it is missing or not a plain
 * positive integer (the backend only ever sends that form). */
export function parseRetryAfter(value: string | null | undefined): number | null {
  if (value == null) return null;
  const text = String(value).trim();
  if (!/^\d+$/.test(text)) return null;
  const seconds = Number(text);
  return seconds >= 1 && Number.isSafeInteger(seconds) ? seconds : null;
}

/** The header value the BFF should send on, or null to send none. Junk is
 * dropped rather than forwarded. */
export function retryAfterHeader(value: string | null | undefined): string | null {
  const seconds = parseRetryAfter(value);
  return seconds === null ? null : String(seconds);
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

/** Whole seconds left until `untilMs`, never negative. */
export function remainingSeconds(untilMs: number, nowMs: number): number {
  return Math.max(0, Math.ceil((untilMs - nowMs) / 1000));
}

export function isThrottled(status: number, payload: unknown): boolean {
  return status === 429 || errorDetail(payload) === "too_many_attempts";
}

function errorDetail(payload: unknown): string {
  return payload && typeof payload === "object" && "detail" in payload
    ? String((payload as { detail?: unknown }).detail ?? "")
    : "";
}

/** Text for a failed password sign-in. `retryAfterSeconds` is the parsed
 * `Retry-After` of a 429. */
export function loginErrorMessage(
  status: number,
  payload: unknown,
  retryAfterSeconds?: number | null,
): string {
  const detail = errorDetail(payload);

  if (isThrottled(status, payload)) {
    return throttleMessage(retryAfterSeconds);
  }
  if (status === 401 || detail === "invalid_credentials") {
    return "Username or password is incorrect.";
  }
  if (status === 400 || detail === "missing_credentials") {
    return "Fill in both username and password.";
  }
  if (status >= 500) {
    return "Server is having a bad time. Try again in a minute.";
  }
  return detail || "Something went wrong.";
}
