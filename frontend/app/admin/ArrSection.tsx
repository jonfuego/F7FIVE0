// Admin > Radarr, Sonarr and Lidarr: the address and API key of each app, a
// Test button, the quality profile and root folder Requests use (read from the
// app), and the webhook address and token to paste into each app. Saved in the
// database, so they take effect without a restart and win over the *_API_KEY
// and *_URL values from Setup (.env). The browser never talks to the apps and
// never gets a key back: keys are write-only here, and everything goes through
// /api/admin/arr (see services/arr_settings.py).

"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { apiDelete, apiGet, apiPost, apiPut, ApiError } from "@/lib/client-api";
import { isLoopbackOrigin, webhookBases, webhookUrl } from "@/lib/arr-webhook";
import { copyText } from "@/lib/copy-text";
import type {
  ArrAppId,
  ArrAppSettings,
  ArrOptions,
  ArrSettings,
  ArrTestResult,
  ArrWebhook,
} from "@/lib/types";

// What each app manages, in the words people use for the library.
const LIBRARY_NAME: Record<ArrAppId, string> = {
  radarr: "Movies",
  sonarr: "TV shows",
  lidarr: "Music",
};

function errorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : fallback;
}

export function ArrSection() {
  const [data, setData] = useState<ArrSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await apiGet<ArrSettings>("/api/admin/arr"));
      setLoadError(null);
    } catch (err) {
      setLoadError(errorText(err, "Could not load."));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div id="arr" className="scroll-mt-24">
      <p className="text-xs text-neutral-500">
        Radarr, Sonarr and Lidarr are optional. They manage your movies, TV shows and music, and Radarr and Sonarr
        also switch on Requests. Changes apply right away; no restart. Values saved here win over the ones from Setup
        (.env).
      </p>

      {loadError ? <p className="mt-4 text-xs text-red-400">{loadError}</p> : null}
      {!data && !loadError ? (
        <div className="mt-4 h-16 animate-pulse rounded-lg bg-neutral-900" />
      ) : null}

      {data ? (
        <div className="mt-4 space-y-4">
          {data.apps.map((cfg) => (
            <AppCard key={cfg.app} cfg={cfg} onSaved={setData} />
          ))}
          <WebhookBlock />
        </div>
      ) : null}
    </div>
  );
}

function AppCard({ cfg, onSaved }: { cfg: ArrAppSettings; onSaved: (s: ArrSettings) => void }) {
  const [url, setUrl] = useState(cfg.url);
  const [key, setKey] = useState("");
  const [profile, setProfile] = useState<number>(cfg.quality_profile_id ?? 0);
  const [folder, setFolder] = useState(cfg.root_folder ?? "");
  const [options, setOptions] = useState<ArrOptions | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | "remove" | null>(null);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const label = cfg.label;
  const library = LIBRARY_NAME[cfg.app];

  // With a key already set, load the profile and folder choices straight away.
  const hasKey = cfg.has_key;
  const supportsRequests = cfg.supports_requests;
  useEffect(() => {
    if (!hasKey || !supportsRequests) return;
    let alive = true;
    apiGet<ArrOptions>(`/api/admin/arr/${cfg.app}/options`)
      .then((o) => {
        if (alive) setOptions(o);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [cfg.app, hasKey, supportsRequests]);

  async function test() {
    if (busy) return;
    setBusy("test");
    setResult(null);
    try {
      const res = await apiPost<ArrTestResult>(`/api/admin/arr/${cfg.app}/test`, {
        url: url.trim(),
        api_key: key.trim(),
      });
      setResult({ ok: res.ok, message: res.message });
      if (res.ok && res.options) setOptions(res.options);
    } catch (err) {
      setResult({ ok: false, message: errorText(err, "Test failed.") });
    } finally {
      setBusy(null);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const body: Record<string, unknown> = {};
    if (url.trim() !== cfg.url) body.url = url.trim();
    if (key.trim()) body.api_key = key.trim();
    if (supportsRequests) {
      if (profile !== (cfg.quality_profile_id ?? 0)) body.quality_profile_id = profile;
      if (folder !== (cfg.root_folder ?? "")) body.root_folder = folder;
    }
    if (Object.keys(body).length === 0) {
      setResult({ ok: true, message: "Nothing to save." });
      return;
    }
    setBusy("save");
    setResult(null);
    try {
      const next = await apiPut<ArrSettings>(`/api/admin/arr/${cfg.app}`, body);
      onSaved(next);
      setKey("");
      setResult({
        ok: true,
        message:
          body.api_key && !cfg.has_key
            ? `Saved. ${library} now come from ${label}, and a sync is starting.`
            : "Saved.",
      });
    } catch (err) {
      setResult({ ok: false, message: errorText(err, "Could not save.") });
    } finally {
      setBusy(null);
    }
  }

  async function removeKey() {
    if (busy) return;
    if (!window.confirm(`Remove the ${label} key? ${library} go back to the folder scan.`)) return;
    setBusy("remove");
    setResult(null);
    try {
      const next = await apiDelete<ArrSettings>(`/api/admin/arr/${cfg.app}/key`);
      onSaved(next);
      const now = next.apps.find((a) => a.app === cfg.app);
      setOptions(null);
      setResult({
        ok: true,
        message: now?.configured
          ? "Removed. The key from Setup (.env) is used again."
          : `Removed. ${library} go back to the folder scan.`,
      });
    } catch (err) {
      setResult({ ok: false, message: errorText(err, "Could not remove.") });
    } finally {
      setBusy(null);
    }
  }

  const profiles = options?.profiles ?? [];
  const folders = options?.root_folders ?? [];
  const noKeyToTest = !key.trim() && !cfg.has_key;

  return (
    <div className="rounded-lg border border-neutral-800 p-4">
      <h3 className="text-sm font-semibold text-neutral-100">{label}</h3>
      <p className="mt-1 text-xs text-neutral-400">
        Setting a {label} key hands {library} from the folder scan to {label}. Remove the key to go back to the
        folder scan.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-neutral-400">{label} API key:</span>
        {cfg.has_key ? (
          <>
            <span className="font-mono text-neutral-100">{cfg.masked}</span>
            <span className="text-xs text-neutral-500">
              {cfg.key_source === "env" ? "(from Setup, in .env)" : "(saved here)"}
            </span>
            {cfg.key_source === "admin" ? (
              <button type="button" className={smallButtonCls} onClick={removeKey} disabled={busy !== null}>
                {busy === "remove" ? "Removing..." : "Remove key"}
              </button>
            ) : null}
          </>
        ) : (
          <span className="text-amber-400">not set ({library} use the folder scan)</span>
        )}
      </div>

      <form onSubmit={save} className="mt-3 space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-xs text-neutral-400">
            Address
            <input
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                setResult(null);
              }}
              placeholder="http://127.0.0.1:7878"
              autoComplete="off"
              spellCheck={false}
              className={`${inputCls} mt-1 font-mono`}
              aria-label={`${label} address`}
            />
          </label>
          <label className="block text-xs text-neutral-400">
            API key (from {label} &rsaquo; Settings &rsaquo; General)
            <input
              type="password"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
                setResult(null);
              }}
              placeholder={cfg.has_key ? "Leave blank to keep the current key" : `Paste the ${label} API key`}
              autoComplete="new-password"
              spellCheck={false}
              className={`${inputCls} mt-1 font-mono`}
              aria-label={`${label} API key`}
            />
          </label>
        </div>

        {supportsRequests ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs text-neutral-400">
              Requests: quality profile
              <select
                value={profile}
                onChange={(e) => {
                  setProfile(Number(e.target.value));
                  setResult(null);
                }}
                disabled={profiles.length === 0 && profile === 0}
                className={`${inputCls} mt-1`}
                aria-label={`${label} quality profile for Requests`}
              >
                <option value={0}>{profiles.length ? "Choose a profile" : "Test the connection to choose"}</option>
                {profile !== 0 && !profiles.some((p) => p.id === profile) ? (
                  <option value={profile}>Profile {profile}</option>
                ) : null}
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs text-neutral-400">
              Requests: root folder
              <select
                value={folder}
                onChange={(e) => {
                  setFolder(e.target.value);
                  setResult(null);
                }}
                disabled={folders.length === 0 && folder === ""}
                className={`${inputCls} mt-1`}
                aria-label={`${label} root folder for Requests`}
              >
                <option value="">{folders.length ? "Choose a folder" : "Test the connection to choose"}</option>
                {folder !== "" && !folders.some((f) => f.path === folder) ? <option value={folder}>{folder}</option> : null}
                {folders.map((f) => (
                  <option key={f.path} value={f.path}>
                    {f.path}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-xs text-neutral-500 sm:col-span-2">
              Approved Requests are added to {label} with this profile and folder. Requests need both.
            </p>
          </div>
        ) : (
          <p className="text-xs text-neutral-500">Lidarr has no Requests settings.</p>
        )}

        {options?.error ? <p className="text-xs text-red-400">{options.error}</p> : null}

        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={test} disabled={busy !== null || noKeyToTest} className={smallButtonCls}>
            {busy === "test" ? "Testing..." : "Test"}
          </button>
          <button type="submit" disabled={busy !== null} className={primaryButtonCls}>
            {busy === "save" ? "Saving..." : "Save"}
          </button>
          {result ? (
            <span role="status" className={`text-xs ${result.ok ? "text-emerald-400" : "text-red-400"}`}>
              {result.message}
            </span>
          ) : null}
        </div>
      </form>
    </div>
  );
}

function WebhookBlock() {
  const [hook, setHook] = useState<ArrWebhook | null>(null);
  const [origin, setOrigin] = useState("");
  const [baseIndex, setBaseIndex] = useState(0);
  const [show, setShow] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    setOrigin(window.location.origin);
    apiGet<ArrWebhook>("/api/admin/arr/webhook")
      .then(setHook)
      .catch((err) => setMessage({ ok: false, text: errorText(err, "Could not load the webhook token.") }));
  }, []);

  async function copy(id: string, text: string) {
    const ok = await copyText(text);
    setCopied(ok ? id : null);
    if (!ok) setMessage({ ok: false, text: "Could not copy. Select the text and copy it by hand." });
    window.setTimeout(() => setCopied((c) => (c === id ? null : c)), 1500);
  }

  async function generate(rotate: boolean) {
    if (busy) return;
    if (
      rotate &&
      !window.confirm(
        "Make a new token? Every webhook that uses the old one stops working until you paste the new one into each app.",
      )
    ) {
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      setHook(await apiPost<ArrWebhook>("/api/admin/arr/webhook/generate", { rotate }));
      setShow(true);
      setMessage({
        ok: true,
        text: rotate ? "New token saved. Update the webhook in each app." : "Token made. Paste it into each app's webhook.",
      });
    } catch (err) {
      setMessage({ ok: false, text: errorText(err, "Could not make a token.") });
    } finally {
      setBusy(false);
    }
  }

  const bases = hook ? webhookBases(origin, hook.base_urls) : [];
  const base = bases[Math.min(baseIndex, Math.max(bases.length - 1, 0))];

  return (
    <div className="rounded-lg border border-neutral-800 p-4">
      <h3 className="text-sm font-semibold text-neutral-100">Webhooks</h3>
      <p className="mt-1 text-xs text-neutral-400">
        Optional. With a webhook, a movie, show or album shows up here seconds after the app imports it, instead of at
        the next sync. In each app open Settings &rsaquo; Connect &rsaquo; Add &rsaquo; Webhook, paste the address,
        set Method to POST, and paste the token as the Password (any user name). Radarr and Sonarr can also send it in
        a header named X-Arr-Webhook-Token.
      </p>

      {!hook ? (
        message ? null : <div className="mt-3 h-12 animate-pulse rounded-lg bg-neutral-900" />
      ) : (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-neutral-400">Token:</span>
            {hook.has_token ? (
              <>
                <input
                  readOnly
                  type={show ? "text" : "password"}
                  value={hook.token ?? ""}
                  aria-label="Webhook token"
                  className={`${inputCls} min-w-[16rem] flex-1 font-mono`}
                  onFocus={(e) => e.currentTarget.select()}
                />
                <button type="button" className={smallButtonCls} onClick={() => setShow((s) => !s)}>
                  {show ? "Hide" : "Show"}
                </button>
                <button type="button" className={smallButtonCls} onClick={() => copy("token", hook.token ?? "")}>
                  {copied === "token" ? "Copied" : "Copy"}
                </button>
                <button type="button" className={smallButtonCls} onClick={() => generate(true)} disabled={busy}>
                  Make a new token
                </button>
                <span className="text-xs text-neutral-500">
                  {hook.source === "env" ? "(from Setup, in .env)" : "(saved here)"}
                </span>
              </>
            ) : (
              <>
                <span className="text-amber-400">not set. Webhooks are refused until there is a token.</span>
                <button type="button" className={primaryButtonCls} onClick={() => generate(false)} disabled={busy}>
                  {busy ? "Making..." : "Generate"}
                </button>
              </>
            )}
          </div>

          {bases.length > 1 ? (
            <label className="block text-xs text-neutral-400">
              Address the apps use to reach this server
              <select
                value={baseIndex}
                onChange={(e) => setBaseIndex(Number(e.target.value))}
                className={`${inputCls} mt-1`}
                aria-label="Address the apps use to reach this server"
              >
                {bases.map((b, i) => (
                  <option key={b.url} value={i}>
                    {b.label}: {b.url}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          {base ? (
            <ul className="space-y-2">
              {(Object.keys(hook.paths) as ArrAppId[]).map((app) => {
                const full = webhookUrl(base.url, hook.paths[app]);
                return (
                  <li key={app} className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="w-16 text-neutral-400">{LIBRARY_APP[app]}</span>
                    <input
                      readOnly
                      value={full}
                      aria-label={`${LIBRARY_APP[app]} webhook address`}
                      className={`${inputCls} min-w-[16rem] flex-1 font-mono`}
                      onFocus={(e) => e.currentTarget.select()}
                    />
                    <button type="button" className={smallButtonCls} onClick={() => copy(app, full)}>
                      {copied === app ? "Copied" : "Copy"}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {base && isLoopbackOrigin(base.url) ? (
            <p className="text-xs text-neutral-500">
              This address only works for apps running on this same PC. Open Admin from this server&apos;s home
              network address to get one the other apps can reach.
            </p>
          ) : null}
        </div>
      )}

      {message ? (
        <p role="status" className={`mt-3 text-xs ${message.ok ? "text-emerald-400" : "text-red-400"}`}>
          {message.text}
        </p>
      ) : null}
    </div>
  );
}

const LIBRARY_APP: Record<ArrAppId, string> = { radarr: "Radarr", sonarr: "Sonarr", lidarr: "Lidarr" };

const inputCls =
  "w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500";

const primaryButtonCls =
  "rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60";

const smallButtonCls =
  "rounded-md border border-neutral-800 px-2.5 py-1 text-xs text-neutral-200 transition hover:border-neutral-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-50";
