// First-run admin (backend app/api/setup.py). A silent install makes no
// account; the login page asks GET /api/setup/state and, while the server has
// no account, shows "create your admin account" to a browser on the server PC
// and "finish on the server PC" to anyone else. Pure: no React, no fetch, so
// first-run.test.ts covers it.

export type SetupState = { needs_admin: boolean; local: boolean; web_port?: number };

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

// Names an existing row holds on every install (the seeded system user). The
// API answers 422 username_reserved for them.
export const RESERVED_USERNAMES: ReadonlySet<string> = new Set(["__system__"]);

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
  if (RESERVED_USERNAMES.has(u)) return RESERVED_MESSAGE;
  if (password.length < 8) return "Use a password of at least 8 characters.";
  if (password !== confirm) return "The passwords do not match.";
  return null;
}

const RESERVED_MESSAGE = "That username is used by F7FIVE0 itself. Pick another one.";

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
  if (detail === "username_reserved") return RESERVED_MESSAGE;
  if (status === 422) return "Check the username and password and try again.";
  return "Could not create the account. Try again in a moment.";
}

// The address to open on the server PC. The server's own web port (from
// /api/setup/state) wins: a visitor through a tunnel or proxy sees another port,
// or none, in its address bar. This page's port is the fallback for an older API.
export function serverPcAddress(
  serverPort: unknown,
  pagePort?: string | undefined | null,
): string {
  if (typeof serverPort === "number" && Number.isInteger(serverPort) && serverPort > 0 && serverPort < 65536) {
    return `http://localhost:${serverPort}`;
  }
  const p = (pagePort ?? "").trim();
  return `http://localhost:${/^\d{2,5}$/.test(p) ? p : "3001"}`;
}
