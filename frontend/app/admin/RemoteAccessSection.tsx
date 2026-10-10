// Admin > Remote access. Sets up (or turns off) access from outside the home
// network: Tailscale Funnel, a Cloudflare tunnel, port forwarding with Caddy,
// or a dashboard-made Cloudflare tunnel token.
//
// The work runs on the server in the F7FIVE0-RemoteAccess scheduled task
// (SYSTEM), started by POST /api/admin/remote-access. This card polls the
// run, shows the sign-in link the helper captured, and counts down the
// sign-in window. On success the helper restarts the API and web app, so
// polling tolerates a short outage.

"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import QRCode from "qrcode";
import { apiDelete, apiGet, apiPost, ApiError } from "@/lib/client-api";
import type {
  RemoteAccessMethod, RemoteAccessRun, RemoteAccessRunState, RemoteAccessStatus,
} from "@/lib/types";

const ACTIVE: RemoteAccessRunState[] = ["queued", "running", "signin", "restarting"];

const METHOD_LABEL: Record<RemoteAccessMethod, string> = {
  tailscale: "Tailscale",
  cloudflare: "Cloudflare",
  portforward: "Port forwarding",
  token: "Cloudflare tunnel token",
};

type MethodInfo = {
  id: RemoteAccessMethod;
  title: string;
  blurb: string;
  points: string[];
};

const METHODS: MethodInfo[] = [
  {
    id: "tailscale",
    title: "Tailscale (recommended)",
    blurb: "No domain and no router changes. One sign-in with Google, Microsoft, Apple, or GitHub.",
    points: [
      "Address: https://f7five0.<your-tailnet>.ts.net",
      "Tailscale limits Funnel bandwidth: great for music and a video stream or two; high-bitrate video or several viewers at once may buffer.",
    ],
  },
  {
    id: "cloudflare",
    title: "Cloudflare",
    blurb: "No router changes. Needs a domain already on your Cloudflare account.",
    points: [
      "Address: any name on that domain, like music.yourdomain.com",
      "No bandwidth cap from F7FIVE0. Cloudflare's free-plan terms discourage using it mainly for heavy video.",
    ],
  },
  {
    id: "portforward",
    title: "Port forwarding (advanced)",
    blurb: "Full home upload speed, no middleman. You forward ports 80 and 443 on your router.",
    points: [
      "Address: your own domain, or a free name from duckdns.org",
      "Ports 80 and 443 on this PC are open to the internet. Won't work if your provider blocks them (common on cellular and some fiber plans).",
    ],
  },
  {
    id: "token",
    title: "Cloudflare tunnel token (advanced)",
    blurb: "You already made a tunnel in the Cloudflare dashboard and have its token.",
    points: ["F7FIVE0 runs the tunnel; you set its public hostname in the dashboard."],
  },
];

const ERRORS: Record<string, string> = {
  host_required: "Enter the address to use, like music.yourdomain.com.",
  invalid_host: "Enter just the address, like music.yourdomain.com (no https:// and no slashes).",
  invalid_duckdns_token: "That DuckDNS token doesn't look right. Copy it from duckdns.org.",
  invalid_tunnel_token: "That tunnel token doesn't look right. Copy the long token from the Cloudflare dashboard (the part after --token).",
  unknown_method: "Pick one of the options.",
  run_active: "A remote access run is already going. Wait for it, or cancel it.",
  helper_unavailable:
    "The remote access helper isn't installed. Run Setup again (it adds it), or use installer\\remote-access.ps1 from an elevated PowerShell.",
  helper_failed: "The server couldn't start the remote access helper. See the F7FIVE0 logs, or run Setup again.",
};

function errorText(err: unknown): string {
  if (err instanceof ApiError && err.detail && ERRORS[err.detail]) return ERRORS[err.detail];
  return err instanceof Error ? err.message : "Something went wrong.";
}

function formatClock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

type Form = { method: RemoteAccessMethod; host: string; duckdns: string; token: string };

export function RemoteAccessSection() {
  const [status, setStatus] = useState<RemoteAccessStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [run, setRun] = useState<RemoteAccessRun | null>(null);
  const [lostContact, setLostContact] = useState(false);
  const [picking, setPicking] = useState(false);
  const [confirmOff, setConfirmOff] = useState(false);
  const [form, setForm] = useState<Form>({ method: "tailscale", host: "", duckdns: "", token: "" });
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [showRun, setShowRun] = useState(false);
  const lastState = useRef<RemoteAccessRunState | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<RemoteAccessStatus>("/api/admin/remote-access");
      setStatus(data);
      setRun(data.run);
      setLoadError(null);
      if (ACTIVE.includes(data.run.state)) setShowRun(true);
    } catch (err) {
      setLoadError(errorText(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const active = run !== null && ACTIVE.includes(run.state);

  // Poll the run while it is active. The helper restarts the API and web app
  // at the end, so a few failed polls are expected.
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await apiGet<RemoteAccessRun>("/api/admin/remote-access/run");
        if (cancelled) return;
        setLostContact(false);
        setRun(next);
      } catch {
        if (!cancelled) setLostContact(true);
      }
    };
    const id = window.setInterval(tick, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [active]);

  // When a run finishes, reload the card (new address, reachability).
  useEffect(() => {
    const prev = lastState.current;
    const now = run?.state ?? null;
    lastState.current = now;
    if (prev && ACTIVE.includes(prev) && now && !ACTIVE.includes(now)) void load();
  }, [run?.state, load]);

  // Local countdown for the sign-in window.
  useEffect(() => {
    if (run?.state !== "signin" || run.sign_in_seconds_left == null) {
      setSecondsLeft(null);
      return;
    }
    setSecondsLeft(run.sign_in_seconds_left);
    const id = window.setInterval(() => setSecondsLeft((s) => (s == null ? s : Math.max(0, s - 1))), 1000);
    return () => window.clearInterval(id);
  }, [run?.state, run?.sign_in_seconds_left]);

  async function start(f: Form) {
    setBusy(true);
    setFormError(null);
    try {
      const body: Record<string, string> = { method: f.method };
      if (f.method !== "tailscale") body.host = f.host.trim();
      if (f.method === "portforward" && f.duckdns.trim()) body.duckdns_token = f.duckdns.trim();
      if (f.method === "token") body.tunnel_token = f.token.trim();
      const next = await apiPost<RemoteAccessRun>("/api/admin/remote-access", body);
      setRun(next);
      setShowRun(true);
      setPicking(false);
    } catch (err) {
      setFormError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true);
    setFormError(null);
    try {
      const next = await apiDelete<RemoteAccessRun>("/api/admin/remote-access");
      setRun(next);
      setShowRun(true);
      setConfirmOff(false);
    } catch (err) {
      setFormError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    try {
      setRun(await apiPost<RemoteAccessRun>("/api/admin/remote-access/cancel", {}));
    } catch (err) {
      setFormError(errorText(err));
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void start(form);
  }

  const isDuck = form.host.trim().toLowerCase().endsWith(".duckdns.org");

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-xs text-neutral-500">
          Use F7FIVE0 away from home: on your phone&apos;s data, at work, at a friend&apos;s place.
        </p>
        {!active ? (
          <button type="button" onClick={() => void load()} className="shrink-0 text-xs text-neutral-500 hover:text-neutral-200">
            Refresh
          </button>
        ) : null}
      </div>

      {loadError ? (
        <div className="mt-4 rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">{loadError}</div>
      ) : status === null ? (
        <div className="mt-4 h-24 animate-pulse rounded-md bg-neutral-900" />
      ) : (
        <div className="mt-4 space-y-4">
          {!status.available ? (
            <div className="rounded-md border border-line bg-hive-tint px-4 py-3 text-sm text-hive-text">
              {ERRORS.helper_unavailable}
            </div>
          ) : null}

          {showRun && run && run.state !== "idle" ? (
            <RunPanel
              run={run}
              lostContact={lostContact}
              secondsLeft={secondsLeft}
              onCancel={() => void cancel()}
              onRetry={() => {
                setShowRun(false);
                setPicking(true);
              }}
              onClose={() => setShowRun(false)}
            />
          ) : picking ? (
            <form onSubmit={onSubmit} className="space-y-4">
              <fieldset className="grid gap-3 sm:grid-cols-2">
                <legend className="sr-only">How should people reach F7FIVE0 away from home?</legend>
                {METHODS.map((m) => (
                  <label
                    key={m.id}
                    className={`cursor-pointer rounded-lg border p-4 text-sm ${
                      form.method === m.id ? "border-neutral-300 bg-neutral-800/60" : "border-neutral-800 hover:border-neutral-600"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <input
                        type="radio"
                        name="ra-method"
                        value={m.id}
                        checked={form.method === m.id}
                        onChange={() => setForm({ ...form, method: m.id })}
                      />
                      <span className="font-medium text-neutral-100">{m.title}</span>
                    </div>
                    <p className="mt-2 text-neutral-300">{m.blurb}</p>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-neutral-500">
                      {m.points.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ul>
                  </label>
                ))}
              </fieldset>

              {form.method !== "tailscale" ? (
                <label className="block text-sm">
                  <span className="text-neutral-300">Address</span>
                  <input
                    type="text"
                    inputMode="url"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    value={form.host}
                    onChange={(e) => setForm({ ...form, host: e.target.value })}
                    placeholder={form.method === "portforward" ? "myname.duckdns.org or music.yourdomain.com" : "music.yourdomain.com"}
                    className="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 font-sans text-sm text-neutral-100"
                  />
                </label>
              ) : null}
              {form.method === "portforward" && isDuck ? (
                <label className="block text-sm">
                  <span className="text-neutral-300">DuckDNS token</span>
                  <input
                    type="password"
                    autoComplete="off"
                    value={form.duckdns}
                    onChange={(e) => setForm({ ...form, duckdns: e.target.value })}
                    className="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 font-sans text-sm text-neutral-100"
                  />
                  <span className="mt-1 block text-xs text-neutral-500">
                    From duckdns.org. It keeps the name pointed at your home when your internet address changes.
                  </span>
                </label>
              ) : null}
              {form.method === "token" ? (
                <label className="block text-sm">
                  <span className="text-neutral-300">Tunnel token</span>
                  <input
                    type="password"
                    autoComplete="off"
                    value={form.token}
                    onChange={(e) => setForm({ ...form, token: e.target.value })}
                    className="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 font-sans text-sm text-neutral-100"
                  />
                  <span className="mt-1 block text-xs text-neutral-500">
                    In the Cloudflare dashboard, give the tunnel the public hostname above pointing at{" "}
                    <span className="font-sans">http://localhost:{status.web_port}</span>.
                  </span>
                </label>
              ) : null}

              {form.method === "tailscale" || form.method === "cloudflare" ? (
                <p className="text-xs text-neutral-500">
                  Next, a sign-in link appears here. Open it, sign in, and come back. Stay on this page:{" "}
                  {form.method === "cloudflare"
                    ? "Cloudflare allows about 9 minutes."
                    : "the sign-in waits up to 15 minutes."}
                </p>
              ) : null}
              {status.public_url ? (
                <p className="text-xs text-hive-text">
                  Changing the address signs passkeys out of the old one: everyone sets up their passkey again on the new address.
                </p>
              ) : null}

              {formError ? <p className="text-sm text-rose-300">{formError}</p> : null}
              <div className="flex flex-wrap gap-2">
                <button
                  type="submit"
                  disabled={busy || !status.available}
                  className="rounded-md bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
                >
                  {busy ? "Starting..." : "Set it up"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setPicking(false);
                    setFormError(null);
                  }}
                  className="rounded-md border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800"
                >
                  Back
                </button>
              </div>
            </form>
          ) : (
            <CurrentSetup
              status={status}
              confirmOff={confirmOff}
              busy={busy}
              error={formError}
              onChange={() => {
                setForm((f) => ({ ...f, method: status.method ?? "tailscale" }));
                setPicking(true);
              }}
              onAskOff={() => setConfirmOff(true)}
              onKeep={() => setConfirmOff(false)}
              onOff={() => void turnOff()}
            />
          )}
        </div>
      )}
    </div>
  );
}

function CurrentSetup({
  status, confirmOff, busy, error, onChange, onAskOff, onKeep, onOff,
}: {
  status: RemoteAccessStatus;
  confirmOff: boolean;
  busy: boolean;
  error: string | null;
  onChange: () => void;
  onAskOff: () => void;
  onKeep: () => void;
  onOff: () => void;
}) {
  const url = status.public_url;
  const [qr, setQr] = useState<string | null>(null);

  useEffect(() => {
    if (!url) {
      setQr(null);
      return;
    }
    let cancelled = false;
    QRCode.toDataURL(url, { margin: 1, width: 144, color: { dark: "#000000", light: "#ffffff" } })
      .then((data) => !cancelled && setQr(data))
      .catch(() => !cancelled && setQr(null));
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (!url) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-neutral-300">Off. F7FIVE0 works on your home network only.</p>
        {status.pending_public_url ? (
          <p className="text-xs text-neutral-500">
            Saved {status.pending_public_url}; F7FIVE0 picks it up after its next restart.
          </p>
        ) : null}
        {error ? <p className="text-sm text-rose-300">{error}</p> : null}
        <button
          type="button"
          onClick={onChange}
          disabled={!status.available}
          className="rounded-md bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
        >
          Set up remote access
        </button>
      </div>
    );
  }

  const reach =
    status.reachable === true
      ? { text: "Connected", cls: "bg-emerald-500/15 text-emerald-300" }
      : status.reachable === false
        ? { text: "Not reachable from this server", cls: "bg-rose-500/15 text-rose-300" }
        : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-5">
        {qr ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={qr} alt={`QR code for ${url}`} width={144} height={144} className="rounded-md" />
        ) : null}
        <div className="min-w-0 space-y-2">
          <p className="break-all font-sans text-sm text-neutral-100">{url}</p>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {status.method ? (
              <span className="rounded-full bg-neutral-800 px-2 py-0.5 text-neutral-300">{METHOD_LABEL[status.method]}</span>
            ) : null}
            {reach ? <span className={`rounded-full px-2 py-0.5 ${reach.cls}`}>{reach.text}</span> : null}
          </div>
          {status.reachable === false ? (
            <p className="max-w-md text-xs text-neutral-500">
              {status.method === "portforward"
                ? "Many routers can't loop back to their own public address, so this check can fail at home even when it works outside. Try it on your phone with Wi-Fi off."
                : "Check the tunnel or Tailscale on this PC, or set it up again."}
            </p>
          ) : null}
        </div>
      </div>
      {status.pending_public_url ? (
        <p className="text-xs text-neutral-500">
          Saved {status.pending_public_url}; F7FIVE0 picks it up after its next restart.
        </p>
      ) : null}
      {error ? <p className="text-sm text-rose-300">{error}</p> : null}
      {confirmOff ? (
        <div className="rounded-md border border-neutral-700 p-4 text-sm">
          <p className="text-neutral-200">Turn off remote access?</p>
          <p className="mt-1 text-xs text-neutral-500">
            F7FIVE0 keeps working at home. If you&apos;re using it through {url} right now, this page stops
            responding; open it at home instead.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={onOff}
              className="rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
            >
              Turn off
            </button>
            <button
              type="button"
              onClick={onKeep}
              className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-800"
            >
              Keep it on
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onChange}
            disabled={!status.available}
            className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-800 disabled:opacity-50"
          >
            Change
          </button>
          <button
            type="button"
            onClick={onAskOff}
            disabled={!status.available}
            className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-800 disabled:opacity-50"
          >
            Turn off
          </button>
        </div>
      )}
    </div>
  );
}

function RunPanel({
  run, lostContact, secondsLeft, onCancel, onRetry, onClose,
}: {
  run: RemoteAccessRun;
  lostContact: boolean;
  secondsLeft: number | null;
  onCancel: () => void;
  onRetry: () => void;
  onClose: () => void;
}) {
  const active = ACTIVE.includes(run.state);
  const isCloudflare = run.method === "cloudflare";
  const signInLabel = isCloudflare ? "Sign in to Cloudflare" : "Sign in to Tailscale";

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 text-sm">
        {active ? <span className="h-2 w-2 animate-pulse rounded-full bg-sky-400" /> : null}
        <span className="text-neutral-200">
          {run.state === "succeeded"
            ? run.method === "off"
              ? "Remote access is off."
              : "Done."
            : run.state === "failed"
              ? "That didn't work."
              : run.state === "cancelled"
                ? "Cancelled."
                : lostContact || run.state === "restarting"
                  ? "Restarting F7FIVE0 to use the new address. This page reconnects on its own."
                  : run.step ?? "Working..."}
        </span>
      </div>

      {run.state === "signin" && run.sign_in_url ? (
        <div className="rounded-lg border border-sky-900/60 bg-sky-950/30 p-4">
          <a
            href={run.sign_in_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block rounded-md bg-sky-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-sky-400"
          >
            {signInLabel}
          </a>
          <p className="mt-3 text-sm text-neutral-300">
            {isCloudflare
              ? `Sign in (or create a free account), click your domain${run.host ? ` (${run.host.split(".").slice(1).join(".")})` : ""}, then Authorize. Then come back here.`
              : "Sign in (or create a free account) with Google, Microsoft, Apple, or GitHub, then come back here. If Tailscale asks you to allow Funnel, allow it."}
          </p>
          {secondsLeft != null ? (
            <p className="mt-2 text-xs text-neutral-400">
              {secondsLeft > 0 ? `Time left to sign in: ${formatClock(secondsLeft)}` : "The sign-in window closed."}
            </p>
          ) : null}
          {isCloudflare ? (
            <p className="mt-2 text-xs text-neutral-500">
              Signed in but no Authorize page? Click the button again: Cloudflare sometimes lands on its dashboard first.
            </p>
          ) : null}
        </div>
      ) : null}

      {run.state === "succeeded" && run.public_url ? (
        <p className="text-sm text-neutral-300">
          F7FIVE0 is reachable at <span className="break-all font-sans text-neutral-100">{run.public_url}</span>.
        </p>
      ) : null}
      {run.state === "failed" && run.error ? (
        <div className="rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">{run.error}</div>
      ) : null}

      {run.log.length ? (
        <details className="text-xs">
          <summary className="cursor-pointer text-neutral-500 hover:text-neutral-300">Details</summary>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-md bg-neutral-950 p-3 font-sans text-[11px] text-neutral-400">
            {run.log.join("\n")}
          </pre>
        </details>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {active && run.state !== "restarting" ? (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-800"
          >
            Cancel
          </button>
        ) : null}
        {run.state === "failed" || run.state === "cancelled" ? (
          <button
            type="button"
            onClick={onRetry}
            className="rounded-md bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white"
          >
            Try again
          </button>
        ) : null}
        {!active ? (
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-800"
          >
            {run.state === "succeeded" ? "OK" : "Close"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
