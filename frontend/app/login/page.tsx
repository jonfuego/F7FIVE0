// Login page. Client component so the form can do its own submit,
// surface errors inline, and redirect without a full page reload.
//
// The auth work happens server-side at /api/session/login — this file
// only talks to that BFF endpoint, never to the backend directly.

"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useFeatures } from "@/lib/features";
import { passkeyErrorMessage } from "@/lib/passkey-errors";
import { getPasskeyAssertion, passkeysSupported } from "@/lib/webauthn";
import { HiveWordmark } from "@/components/HiveWordmark";

// Wrapping the hook-using body in Suspense is what lets Next 14's static
// prerender bail out cleanly for pages that read URL search params.
export default function LoginPage() {
  return (
    <Suspense fallback={<LoginShellFallback />}>
      <LoginPageInner />
    </Suspense>
  );
}

function LoginShellFallback() {
  return (
    <main className="login-shell">
      <div className="login-card">
        <div className="mb-6">
          <HiveWordmark href="/login" height={24} />
          <p className="mt-3 text-sm text-ink-2">Sign in to keep watching.</p>
        </div>
      </div>
    </main>
  );
}

function LoginPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = sanitizeNext(params.get("next"));

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [passkeyBusy, setPasskeyBusy] = useState(false);
  const [browserPasskeys, setBrowserPasskeys] = useState(false);
  const features = useFeatures();
  // Shown only when the browser supports WebAuthn and the server has passkeys
  // on (https PUBLIC_URL). WebAuthn is browser-only; decide after mount so SSR
  // and the first client render agree.
  const canPasskey = browserPasskeys && features?.passkeys?.enabled === true;
  useEffect(() => {
    setBrowserPasskeys(passkeysSupported());
  }, []);

  async function onPasskey() {
    if (passkeyBusy || submitting) return;
    setError(null);
    setPasskeyBusy(true);
    try {
      const isPwa =
        typeof window !== "undefined" &&
        (window.matchMedia("(display-mode: standalone)").matches ||
          (navigator as unknown as { standalone?: boolean }).standalone === true);
      const credential = await getPasskeyAssertion();
      const res = await fetch("/api/session/passkey/login/verify", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-client-type": isPwa ? "pwa" : "browser",
        },
        body: JSON.stringify({ credential }),
      });
      if (!res.ok) {
        const payload = await safeJson(res);
        setError(passkeyErrorMessage(res.status, payload));
        setPasskeyBusy(false);
        return;
      }
      window.location.replace(next);
    } catch {
      // A cancelled or unavailable authenticator lands here; keep the password
      // form usable rather than surfacing a scary error.
      setError("Passkey sign-in was cancelled or is unavailable. Use your password.");
      setPasskeyBusy(false);
    }
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);

    try {
      // Detect installed-PWA shell so the backend can hand this session
      // a multi-decade refresh TTL. Plain browser tabs stay on the
      // standard 30-day sliding window.
      const isPwa =
        typeof window !== "undefined" &&
        (window.matchMedia("(display-mode: standalone)").matches ||
          (navigator as unknown as { standalone?: boolean }).standalone === true);

      const res = await fetch("/api/session/login", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-client-type": isPwa ? "pwa" : "browser",
        },
        body: JSON.stringify({ username: username.trim().toLowerCase(), password }),
      });
      if (!res.ok) {
        const payload = await safeJson(res);
        setError(friendlyError(res.status, payload));
        setSubmitting(false);
        return;
      }
      // router.push would keep us in the SPA but a full navigation is
      // cleaner here: cookies were just set and any server components on
      // the target page will re-render with them on the first request.
      window.location.replace(next);
    } catch {
      setError("Could not reach the server. Try again in a moment.");
      setSubmitting(false);
    }
  }

  return (
    <main className="login-shell">
      <div className="login-card">
        <div className="mb-6">
          <HiveWordmark href="/login" height={24} />
          <p className="mt-3 text-sm text-ink-2">Sign in to keep watching.</p>
        </div>

        {canPasskey && (
          <div className="mb-4">
            <button
              type="button"
              onClick={onPasskey}
              disabled={passkeyBusy || submitting}
              className="min-h-tap w-full rounded-1 border border-line-strong bg-surface-2 px-4 py-2 text-sm font-semibold text-ink transition hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {passkeyBusy ? "Waiting for passkey..." : "Sign in with passkey"}
            </button>
            <div className="my-4 flex items-center gap-3 text-xs text-ink-3">
              <span className="h-px flex-1 bg-line" />
              or use your password
              <span className="h-px flex-1 bg-line" />
            </div>
          </div>
        )}

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm text-ink-2">
              Username
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="mt-1 w-full rounded-1 border border-line-strong bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-ink"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm text-ink-2">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-1 border border-line-strong bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-ink"
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="min-h-tap w-full rounded-1 bg-hive px-4 py-2 text-sm font-semibold text-on-hive transition hover:bg-hive-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}

// Reject anything that isn't a same-origin path; a raw string from the URL
// could otherwise bounce the user to a third-party site.
function sanitizeNext(raw: string | null): string {
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

function friendlyError(status: number, payload: unknown): string {
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? String((payload as { detail?: unknown }).detail ?? "")
      : "";

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

async function safeJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}
