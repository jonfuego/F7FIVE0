// Account page. Two self-service forms: display name and password.
//
// All traffic goes through the Next BFF under /api/session/me/*. The
// page loads the current profile once, then each form owns its own
// submit state so the two can be used independently.
//
// Password change revokes every session on the backend (including this
// one), so after a successful change we send the user back to /login.

"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import QRCode from "qrcode";
import { AuthShell } from "@/components/AuthShell";
import { apiGet } from "@/lib/client-api";
import { loadMe } from "@/lib/load-me";
import { useFeatures } from "@/lib/features";
import { createPasskey, passkeysSupported } from "@/lib/webauthn";
import type { Me } from "@/lib/types";

export default function AccountPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // loadMe goes through apiGet (single-flight refresh + retry), so the page
  // renders on first navigation even right after the 15-min access token
  // expired. See lib/load-me.ts for the cause this fixes.
  const load = useCallback(async (signal?: AbortSignal) => {
    setLoadError(null);
    try {
      const payload = await loadMe(apiGet, signal);
      if (payload) setMe(payload);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setLoadError("Could not load your profile.");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => {
      controller.abort();
    };
  }, [load]);

  return (
    <AuthShell>
      <div className="mx-auto max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">Account</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Update your display name or change your password.
        </p>

        {loadError ? (
          <div className="mt-6 rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">
            <p>{loadError}</p>
            <button
              type="button"
              onClick={() => load()}
              className="mt-3 rounded-md border border-red-800/60 px-3 py-1.5 text-xs text-red-100 hover:border-red-600"
            >
              Try again
            </button>
          </div>
        ) : me === null ? (
          <LoadingSkeleton />
        ) : (
          <div className="mt-6 space-y-6">
            <ProfileCard me={me} onChanged={setMe} />
            <PasskeysCard />
            <PasswordCard />
            <SessionCard me={me} />
            <AnywhereCard />
            <AndroidAppCard />
          </div>
        )}
      </div>
    </AuthShell>
  );
}

function ProfileCard({
  me,
  onChanged,
}: {
  me: Me;
  onChanged: (next: Me) => void;
}) {
  const [displayName, setDisplayName] = useState(me.display_name);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<FormStatus>(null);

  const dirty = displayName.trim() !== me.display_name;

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting || !dirty) return;
    setSubmitting(true);
    setStatus(null);
    try {
      const res = await fetch("/api/session/me", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ display_name: displayName.trim() }),
      });
      if (!res.ok) {
        const payload = await safeJson(res);
        setStatus({ kind: "error", message: friendlyError(res.status, payload) });
        return;
      }
      const next = (await res.json()) as Me;
      onChanged(next);
      setDisplayName(next.display_name);
      setStatus({ kind: "success", message: "Profile updated." });
    } catch {
      setStatus({ kind: "error", message: "Could not reach the server." });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
      <h2 className="text-base font-semibold">Profile</h2>
      <p className="mt-1 text-xs text-neutral-500">
        Your username is managed by an admin and cannot be changed here.
      </p>
      <form onSubmit={onSubmit} className="mt-4 space-y-4">
        <Field label="Username" htmlFor="username">
          <input
            id="username"
            type="text"
            value={me.username}
            disabled
            className={readonlyInputCls}
          />
        </Field>
        <Field label="Display name" htmlFor="display_name">
          <input
            id="display_name"
            type="text"
            required
            maxLength={120}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className={inputCls}
          />
        </Field>
        {status ? <StatusLine status={status} /> : null}
        <div>
          <button
            type="submit"
            disabled={submitting || !dirty}
            className={primaryButtonCls}
          >
            {submitting ? "Saving..." : "Save changes"}
          </button>
        </div>
      </form>
    </section>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next1, setNext1] = useState("");
  const [next2, setNext2] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<FormStatus>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;
    setStatus(null);
    if (next1.length < 8) {
      setStatus({ kind: "error", message: "New password must be at least 8 characters." });
      return;
    }
    if (next1 !== next2) {
      setStatus({ kind: "error", message: "New passwords do not match." });
      return;
    }
    if (next1 === current) {
      setStatus({ kind: "error", message: "New password must differ from current." });
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/session/me/password", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ current_password: current, new_password: next1 }),
      });
      if (res.status !== 204) {
        const payload = await safeJson(res);
        setStatus({ kind: "error", message: friendlyError(res.status, payload) });
        setSubmitting(false);
        return;
      }
      // The backend just revoked every session. Redirect to login so the
      // user gets a clean session on the new password. No point trying to
      // keep the UI responsive; nothing will succeed.
      window.location.replace("/login?next=/account");
    } catch {
      setStatus({ kind: "error", message: "Could not reach the server." });
      setSubmitting(false);
    }
  }

  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
      <h2 className="text-base font-semibold">Password</h2>
      <p className="mt-1 text-xs text-neutral-500">
        Changing your password signs you out everywhere. You will need to sign in again.
      </p>
      <form onSubmit={onSubmit} className="mt-4 space-y-4" autoComplete="off">
        <Field label="Current password" htmlFor="current_password">
          <input
            id="current_password"
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className={inputCls}
          />
        </Field>
        <Field label="New password" htmlFor="new_password">
          <input
            id="new_password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={next1}
            onChange={(e) => setNext1(e.target.value)}
            className={inputCls}
          />
        </Field>
        <Field label="Confirm new password" htmlFor="confirm_password">
          <input
            id="confirm_password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={next2}
            onChange={(e) => setNext2(e.target.value)}
            className={inputCls}
          />
        </Field>
        {status ? <StatusLine status={status} /> : null}
        <div>
          <button type="submit" disabled={submitting} className={primaryButtonCls}>
            {submitting ? "Changing..." : "Change password"}
          </button>
        </div>
      </form>
    </section>
  );
}

type Passkey = {
  id: string;
  name: string;
  transports: string | null;
  created_at: string;
  last_used_at: string | null;
};

// Passkeys section: register a new passkey, then list / rename / delete them.
// All calls go through the /api/session/passkey BFF, which proxies to the
// backend /api/auth/passkeys endpoints with the access cookie attached (the
// browser never holds a bearer token). Registration uses
// navigator.credentials.create via the createPasskey helper; management uses
// PATCH (rename) and DELETE against /api/session/passkey/credentials/{id}.
function PasskeysCard() {
  const features = useFeatures();
  const [items, setItems] = useState<Passkey[] | null>(null);
  const [supported, setSupported] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<FormStatus>(null);

  const enabled = features?.passkeys?.enabled === true;
  const rpId = features?.passkeys?.rp_id ?? null;

  useEffect(() => {
    setSupported(passkeysSupported());
  }, []);

  useEffect(() => {
    if (enabled) void refresh();
  }, [enabled]);

  async function refresh() {
    try {
      const res = await fetch("/api/session/passkey/credentials", { cache: "no-store" });
      if (!res.ok) {
        setItems([]);
        return;
      }
      setItems(((await res.json()) as Passkey[]) ?? []);
    } catch {
      setItems([]);
    }
  }

  async function onAdd() {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      // navigator.credentials.create runs inside createPasskey.
      const credential = await createPasskey();
      const res = await fetch("/api/session/passkey/register/verify", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ credential, name: defaultPasskeyName() }),
      });
      if (!res.ok) {
        const payload = await safeJson(res);
        setStatus({ kind: "error", message: friendlyError(res.status, payload) });
        return;
      }
      setStatus({ kind: "success", message: "Passkey added." });
      await refresh();
    } catch {
      setStatus({ kind: "error", message: "Passkey setup was cancelled or unavailable." });
    } finally {
      setBusy(false);
    }
  }

  async function onRename(id: string, current: string) {
    const next = window.prompt("Rename passkey", current);
    if (next === null) return;
    const name = next.trim();
    if (!name || name === current) return;
    // PATCH /api/session/passkey/credentials/{id} -> backend /api/auth/passkeys/{id}
    const res = await fetch(`/api/session/passkey/credentials/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (res.ok) await refresh();
    else setStatus({ kind: "error", message: "Could not rename passkey." });
  }

  async function onDelete(id: string) {
    if (!window.confirm("Remove this passkey? You will need another way to sign in.")) return;
    // DELETE /api/session/passkey/credentials/{id} -> backend /api/auth/passkeys/{id}
    const res = await fetch(`/api/session/passkey/credentials/${id}`, { method: "DELETE" });
    if (res.status === 204) await refresh();
    else setStatus({ kind: "error", message: "Could not remove passkey." });
  }

  // Hidden when the browser lacks WebAuthn or the server has passkeys off
  // (home-only install without https).
  if (!supported || !enabled) return null;

  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
      <h2 className="text-base font-semibold">Passkeys</h2>
      <p className="mt-1 text-xs text-neutral-500">
        Sign in with your fingerprint or device lock instead of a password. Your
        passkey works here and in the F7FIVE0 Android app
        {rpId ? <> for <span className="text-neutral-300">{rpId}</span></> : null}.
      </p>

      <div className="mt-4 space-y-2">
        {items === null ? (
          <div className="h-10 animate-pulse rounded-md bg-neutral-800/60" />
        ) : items.length === 0 ? (
          <p className="text-sm text-neutral-400">No passkeys yet.</p>
        ) : (
          items.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm"
            >
              <div>
                <div className="text-neutral-100">{p.name}</div>
                <div className="text-xs text-neutral-500">
                  Added {formatCreated(p.created_at)}
                  {p.last_used_at ? ` · last used ${formatCreated(p.last_used_at)}` : ""}
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => onRename(p.id, p.name)}
                  className="rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:border-neutral-500"
                >
                  Rename
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(p.id)}
                  className="rounded-md border border-rose-900/60 px-2 py-1 text-xs text-rose-300 hover:border-rose-700"
                >
                  Delete
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {status ? <div className="mt-3"><StatusLine status={status} /></div> : null}

      <div className="mt-4">
        <button type="button" onClick={onAdd} disabled={busy} className={primaryButtonCls}>
          {busy ? "Setting up..." : "Add a passkey"}
        </button>
      </div>
    </section>
  );
}

function defaultPasskeyName(): string {
  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";
  if (/Android/i.test(ua)) return "Android device";
  if (/iPhone|iPad|Macintosh/i.test(ua)) return "Apple device";
  if (/Windows/i.test(ua)) return "Windows device";
  return "This device";
}

function SessionCard({ me }: { me: Me }) {
  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
      <h2 className="text-base font-semibold">Session</h2>
      <div className="mt-3 grid grid-cols-[min-content_1fr] gap-x-4 gap-y-2 text-sm">
        <div className="text-neutral-500">Role</div>
        <div className="text-neutral-200">
          {me.role === "admin" ? "Admin" : "Member"}
        </div>
        <div className="text-neutral-500">Created</div>
        <div className="text-neutral-200">{formatCreated(me.created_at)}</div>
      </div>
    </section>
  );
}

function LoadingSkeleton() {
  return (
    <div className="mt-6 space-y-6">
      {[0, 1].map((i) => (
        <div
          key={i}
          className="h-48 animate-pulse rounded-xl border border-neutral-800 bg-neutral-900/40"
        />
      ))}
    </div>
  );
}

type FormStatus = { kind: "success" | "error"; message: string } | null;

function StatusLine({ status }: { status: NonNullable<FormStatus> }) {
  const color = status.kind === "success" ? "text-emerald-400" : "text-rose-400";
  return (
    <p role="status" className={`text-sm ${color}`}>
      {status.message}
    </p>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-sm text-neutral-300">
        {label}
      </label>
      <div className="mt-1">{children}</div>
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500";

const readonlyInputCls =
  "w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-400 outline-none cursor-not-allowed";

const primaryButtonCls =
  "rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60";

function formatCreated(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function friendlyError(status: number, payload: unknown): string {
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? String((payload as { detail?: unknown }).detail ?? "")
      : "";

  if (detail === "invalid_current_password") {
    return "Current password is incorrect.";
  }
  if (detail === "new_password_same_as_current") {
    return "New password must differ from the current one.";
  }
  if (detail === "display_name_required") {
    return "Display name cannot be empty.";
  }
  if (status === 422) {
    return "Please check the values you entered.";
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

// The address to use away from home, as text and a QR code a phone camera
// can open. Falls back to the address in the browser bar when setup did not
// configure remote access.
function AnywhereCard() {
  const features = useFeatures();
  const [origin, setOrigin] = useState("");
  const [qr, setQr] = useState<string | null>(null);
  const url = features?.public_url || origin;
  const remote = Boolean(features?.public_url);

  useEffect(() => {
    setOrigin(window.location.origin);
  }, []);

  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    QRCode.toDataURL(url, { margin: 1, width: 176, color: { dark: "#000000", light: "#ffffff" } })
      .then((data) => !cancelled && setQr(data))
      .catch(() => !cancelled && setQr(null));
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (!features) return null;

  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
      <h2 className="text-base font-semibold">{remote ? "Listen from anywhere" : "Open on your phone"}</h2>
      <p className="mt-1 text-xs text-neutral-500">
        {remote
          ? "This address works at home and away. Scan it with your phone's camera, or type it into the Android app."
          : "Scan with your phone's camera to open F7FIVE0. Remote access isn't set up, so this only works on your home network. An admin can turn it on in Admin > Remote access."}
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-5">
        {qr ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={qr} alt={`QR code for ${url}`} width={176} height={176} className="rounded-md" />
        ) : null}
        <div className="min-w-0">
          <p className="break-all font-sans text-sm text-neutral-200">{url}</p>
          <button
            type="button"
            onClick={() => void navigator.clipboard?.writeText(url)}
            className="mt-3 rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-800"
          >
            Copy address
          </button>
        </div>
      </div>
    </section>
  );
}

// Android app download. HEAD /download/android tells us whether an APK is
// published (and its name/size) so the button only shows when it will work.
function AndroidAppCard() {
  const [apk, setApk] = useState<
    { name: string; size: number; version: string; armv7: boolean } | null | undefined
  >(undefined);

  useEffect(() => {
    let cancelled = false;
    fetch("/download/android", { method: "HEAD", cache: "no-store" })
      .then((res) => {
        if (cancelled) return;
        if (!res.ok) return setApk(null);
        setApk({
          name: res.headers.get("x-apk-name") ?? "F7FIVE0.apk",
          size: Number(res.headers.get("content-length") ?? 0),
          version: res.headers.get("x-apk-version") ?? "",
          armv7: (res.headers.get("x-apk-abis") ?? "").split(",").includes("armv7"),
        });
      })
      .catch(() => !cancelled && setApk(null));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
      <h2 className="text-base font-semibold">Android app</h2>
      <p className="mt-1 text-xs text-neutral-500">
        Install F7FIVE0 on your Android phone. Music keeps playing with the screen locked,
        and you stay signed in.
      </p>
      {apk === undefined ? (
        <div className="mt-4 h-10 w-48 animate-pulse rounded-md bg-neutral-800/60" />
      ) : apk === null ? (
        <p className="mt-4 text-sm text-neutral-400">The Android app isn&apos;t available yet.</p>
      ) : (
        <>
          <a
            href="/download/android"
            className="mt-4 inline-flex items-center rounded-md bg-hive px-4 py-2 text-sm font-semibold text-on-hive hover:bg-hive-hover"
          >
            Download for Android
          </a>
          <p className="mt-2 text-xs text-neutral-500">
            {apk.version ? `Version ${apk.version}` : apk.name}
            {apk.size > 0 ? ` · ${(apk.size / (1024 * 1024)).toFixed(0)} MB` : ""}
          </p>
          <p className="mt-3 text-xs text-neutral-500">
            Open the downloaded file on your phone. If Android asks, allow installs from your
            browser, then tap Install. The app opens with this server already filled in; sign
            in with your F7FIVE0 username and password. Already have the app? Installing this
            file updates it in place.
          </p>
          {apk.armv7 ? (
            <p className="mt-2 text-xs text-neutral-500">
              Older 32-bit phone or TV box?{" "}
              <a href="/download/android?abi=armv7" className="underline hover:text-neutral-300">
                Get the 32-bit build
              </a>
              .
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
