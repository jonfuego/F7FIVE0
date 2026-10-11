/** Pure decision for a token-refresh attempt: when may we sign the user out?
 *
 * Only a real 401 from the refresh call means the refresh token is dead. A
 * server restart, a 5xx, a timeout or a dropped connection says nothing about
 * the session, so none of them may clear the stored token or send the user to
 * login. They are "try again" a bounded number of times, then "keep the
 * session" (that request fails, the token stays, the next request tries again).
 *
 * No imports, so jest runs it with no native modules. The web app has the same
 * helper in frontend/lib/refresh-outcome.ts; keep the two in step.
 */
export type RefreshOutcome =
  | { kind: "response"; status: number }
  | { kind: "network-error" }
  | { kind: "timeout" };

export type RefreshDecision =
  /** 2xx: tokens rotated. */
  | "refreshed"
  /** Real 401: the refresh token is rejected. The only decision that signs out. */
  | "sign-out"
  /** Transient failure with retries left: wait and call refresh again. */
  | "retry"
  /** Transient (retries used up) or unexpected non-401 answer: no sign-out, no
   * clearing of storage; the caller fails this request only. */
  | "keep-session";

/** 2 retries after the first try, waiting 0.5 s then 1.5 s. */
export const REFRESH_RETRY_DELAYS_MS: readonly number[] = [500, 1500];

export function retryDelayMs(retriesUsed: number): number {
  const i = Math.min(Math.max(retriesUsed, 0), REFRESH_RETRY_DELAYS_MS.length - 1);
  return REFRESH_RETRY_DELAYS_MS[i];
}

function isTransient(outcome: RefreshOutcome): boolean {
  if (outcome.kind !== "response") return true; // network error or timeout
  const s = outcome.status;
  // 5xx (restart, proxy 502/503/504, Cloudflare 52x), request timeout, rate limit.
  return s >= 500 || s === 408 || s === 429;
}

/** retriesUsed is how many retries have already been made (0 on the first try). */
export function decideRefresh(outcome: RefreshOutcome, retriesUsed = 0): RefreshDecision {
  if (outcome.kind === "response") {
    if (outcome.status >= 200 && outcome.status < 300) return "refreshed";
    if (outcome.status === 401) return "sign-out";
  }
  if (isTransient(outcome)) {
    return retriesUsed < REFRESH_RETRY_DELAYS_MS.length ? "retry" : "keep-session";
  }
  // 400/403/404/422 and other odd answers: the API only ever rejects a refresh
  // token with 401, so these mean a misrouted or filtered request (a proxy or
  // WAF 403, say), not a dead session. Retrying would not change them.
  return "keep-session";
}
