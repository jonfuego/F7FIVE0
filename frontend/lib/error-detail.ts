// Turn an API error detail into text a person reads.
//
// Some API errors carry a machine code in front of the sentence, for example
// "already_matched: Queen (music library) already uses this MusicBrainz
// artist. ...". Clients and tests match on the code, so the API keeps it; the
// screen shows only the sentence. A bare code with no sentence ("override_not_found")
// is left as it is. Pure: no React, no `@/` imports (node --test runs it).

const CODE_PREFIX = /^[a-z][a-z0-9_]*:\s+(\S[\s\S]*)$/;

const FRIENDLY: Record<string, string> = {
  session_refresh_unavailable:
    "The server isn't answering right now. You are still signed in; try again in a moment.",
};

export function detailText(detail: string): string {
  const trimmed = detail.trim();
  if (FRIENDLY[trimmed]) return FRIENDLY[trimmed];
  const m = CODE_PREFIX.exec(trimmed);
  return m ? m[1] : trimmed;
}

// Text for an error thrown by lib/client-api (an ApiError carries `detail`)
// or by fetch itself (a plain Error). Duck-typed so this file stays pure.
export function errorText(err: unknown, fallback: string): string {
  if (err && typeof err === "object") {
    const detail = (err as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detailText(detail);
    const status = (err as { status?: unknown }).status;
    if (typeof status === "number") return `HTTP ${status}`;
    const message = (err as { message?: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  return fallback;
}
