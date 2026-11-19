// First-run admin (backend app/api/setup.py). A silent install makes no
// account; the login page asks GET /api/setup/state and, while the server has
// no account, shows "create your admin account" to a browser on the server PC
// and "finish on the server PC" to anyone else. Pure: no React, no fetch, so
// first-run.test.ts covers it.

export type SetupState = { needs_admin: boolean; local: boolean };

export type LoginView = "signin" | "create-admin" | "finish-on-server";

// What the login page shows. Anything unexpected (an older API without the
// route, a network error, a malformed body) keeps the normal sign-in form.
export function loginView(state: unknown): LoginView {
  if (!state || typeof state !== "object") return "signin";
  const s = state as Partial<SetupState>;
  if (s.needs_admin !== true) return "signin";
  return s.local === true ? "create-admin" : "finish-on-server";
}

export const USERNAME_RE = /^[a-z0-9._-]{3,64}$/;

// Checked in the page before the request; the API checks the same rules.
export function validateNewAdmin(
  username: string,
  password: string,
  confirm: string,
): string | null {
  const u = username.trim().toLowerCase();
  if (!USERNAME_RE.test(u)) {
    return "Usernames are 3 to 64 characters: lowercase letters, digits, dot, dash, underscore.";
  }
  if (password.length < 8) return "Use a password of at least 8 characters.";
  if (password !== confirm) return "The passwords do not match.";
  return null;
}

// The message for a failed POST /api/setup/admin. Never shows a raw code.
export function createAdminError(status: number, payload: unknown): string {
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? (payload as { detail: unknown }).detail
      : null;
  if (status === 409 || detail === "setup_done") {
    return "An account already exists on this server. Sign in instead.";
  }
  if (status === 403 || detail === "setup_local_only") {
    return "The admin account can only be created on the PC where F7FIVE0 is installed.";
  }
  if (status === 422) return "Check the username and password and try again.";
  return "Could not create the account. Try again in a moment.";
}

// The address to open on the server PC: same port as this page, on localhost.
export function serverPcAddress(port: string | undefined | null): string {
  const p = (port ?? "").trim();
  return `http://localhost:${/^\d{2,5}$/.test(p) ? p : "3001"}`;
}
