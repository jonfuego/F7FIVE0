// Pure rules for the Admin > Users table (batch 8 item 14). Kept apart from the
// React component so node:test covers them (admin-users.test.ts).
//
//   - Your own row: Disable and the role menu are not available, and the row
//     says why (OWN_ROW_REASON) instead of just greying the controls out.
//   - The result of an action (saved, or the error) belongs to one row and is
//     shown next to that row, not above the table. An error is red.
//
// Colors are chosen in page.tsx from `kind` (Tailwind only scans app/ and
// components/, so a class name written here would never be generated).

export const OWN_ROW_REASON = "You can't disable or demote your own account.";

export type RowMessageKind = "ok" | "error";

export type RowMessage = { userId: string; kind: RowMessageKind; text: string };

export function isOwnRow(userId: string, meId: string): boolean {
  return userId === meId;
}

// The text to show on a row whose controls are locked, or null when they are not.
export function ownRowReason(userId: string, meId: string): string | null {
  return isOwnRow(userId, meId) ? OWN_ROW_REASON : null;
}

// The message to show on this row: only the row the message belongs to.
export function rowMessageFor(message: RowMessage | null, userId: string): RowMessage | null {
  return message !== null && message.userId === userId ? message : null;
}

export function okMessage(userId: string, text: string): RowMessage {
  return { userId, kind: "ok", text };
}

export function errorMessage(userId: string, text: string): RowMessage {
  return { userId, kind: "error", text };
}

type ErrorLike = { status?: number; detail?: string | null; message?: string } | null | undefined;

// Plain text for a failed user action. The two "last admin" guards and a
// vanished user get their own wording; a server error says so and keeps the
// code, so a report like "HTTP 500" is still recognisable.
export function userActionErrorText(err: unknown, fallback = "Something went wrong."): string {
  const e: ErrorLike = typeof err === "object" && err !== null ? (err as ErrorLike) : null;
  const detail = e?.detail ?? null;
  if (detail === "cannot_disable_last_admin") return "Cannot disable the last active admin.";
  if (detail === "cannot_demote_last_admin") return "Cannot demote the last active admin.";
  if (detail === "user_not_found") return "That user no longer exists. Reload the list.";
  if (typeof e?.status === "number" && e.status >= 500) {
    return `The server could not save this change (HTTP ${e.status}). Nothing was changed.`;
  }
  const message = typeof e?.message === "string" ? e.message.trim() : "";
  return message || fallback;
}
