// Admin > Metadata: the TMDB API key, and the Podcast Index key and secret. TMDB supplies posters, backdrops, and
// descriptions for movies and shows found in the library folders. The key
// is checked with TMDB before it is saved, takes effect without a restart,
// and saving it starts a library refresh. Stored in the database, so it
// overrides TMDB_API_KEY from Setup (.env).

"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { apiDelete, apiGet, apiPost, apiPut, ApiError } from "@/lib/client-api";
import type { MetadataSettings, PodcastIndexStatus, TmdbKeyCheck } from "@/lib/types";

// Sign-up works signed out; Settings > API 401s until you have a TMDB account.
const TMDB_API_PAGE = "https://www.themoviedb.org/signup";
const PODCASTINDEX_SIGNUP = "https://api.podcastindex.org/signup";

export function MetadataSection() {
  const [data, setData] = useState<MetadataSettings | null>(null);
  const [key, setKey] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"test" | "save" | "remove" | null>(null);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await apiGet<MetadataSettings>("/api/admin/metadata"));
    } catch (err) {
      setResult({ ok: false, message: err instanceof Error ? err.message : "Could not load." });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Reminder banners link to /admin#metadata; the section renders after the
  // page loads, so scroll once it exists.
  useEffect(() => {
    if (data && typeof window !== "undefined" && window.location.hash === "#metadata") {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [data]);

  async function test() {
    if (!key.trim() || busy) return;
    setBusy("test");
    setResult(null);
    try {
      setResult(await apiPost<TmdbKeyCheck>("/api/admin/metadata/tmdb/test", { api_key: key.trim() }));
    } catch (err) {
      setResult({ ok: false, message: err instanceof Error ? err.message : "Check failed." });
    } finally {
      setBusy(null);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!key.trim() || busy) return;
    setBusy("save");
    setResult(null);
    try {
      setData(await apiPut<MetadataSettings>("/api/admin/metadata/tmdb", { api_key: key.trim() }));
      setKey("");
      setEditing(false);
      setResult({ ok: true, message: "Saved. Refreshing the library: posters and descriptions fill in over the next few minutes." });
    } catch (err) {
      const msg = err instanceof ApiError && err.detail ? err.detail : err instanceof Error ? err.message : "Could not save.";
      setResult({ ok: false, message: msg });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (busy) return;
    if (!window.confirm("Remove the TMDB key? New movies and shows won't get posters or descriptions from TMDB.")) return;
    setBusy("remove");
    setResult(null);
    try {
      const res = await apiDelete<MetadataSettings>("/api/admin/metadata/tmdb");
      setData(res);
      setResult({
        ok: true,
        message: res.tmdb.configured ? "Removed. The key from Setup is used again." : "Removed. TMDB is off.",
      });
    } catch (err) {
      setResult({ ok: false, message: err instanceof Error ? err.message : "Could not remove." });
    } finally {
      setBusy(null);
    }
  }

  const tmdb = data?.tmdb;
  const showForm = !tmdb?.configured || editing;

  return (
    <div id="metadata" ref={ref} className="scroll-mt-24">
      <p className="text-xs text-neutral-500">
        TMDB supplies posters, backdrops, and descriptions for the movies and shows in your
        folders. The key is free.
      </p>

      {!data ? (
        <div className="mt-4 h-16 animate-pulse rounded-lg bg-neutral-900" />
      ) : (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-neutral-400">TMDB API key:</span>
            {tmdb?.configured ? (
              <>
                <span className="font-mono text-neutral-100">{tmdb.masked}</span>
                <span className="text-xs text-neutral-500">
                  {tmdb.source === "env" ? "(from Setup)" : "(saved here)"}
                </span>
                {!editing ? (
                  <button type="button" className={smallButtonCls} onClick={() => setEditing(true)}>
                    Change
                  </button>
                ) : null}
                {tmdb.source === "admin" ? (
                  <button type="button" className={smallButtonCls} onClick={remove} disabled={busy !== null}>
                    {busy === "remove" ? "Removing..." : "Remove"}
                  </button>
                ) : null}
              </>
            ) : (
              <span className="text-amber-400">not set</span>
            )}
          </div>

          {showForm ? (
            <>
              <ol className="list-decimal space-y-1 pl-5 text-xs text-neutral-400">
                <li>
                  Make a free account at{" "}
                  <a href={TMDB_API_PAGE} target="_blank" rel="noreferrer" className="underline hover:text-white">
                    themoviedb.org
                  </a>
                  , then open Settings &rsaquo; API.
                </li>
                <li>Request an API key (choose Developer; any short description works).</li>
                <li>
                  Copy the <strong>API Key</strong> (the shorter one, not the &quot;API Read Access Token&quot;) and
                  paste it here.
                </li>
              </ol>
              <form onSubmit={save} className="flex flex-wrap gap-2">
                <input
                  value={key}
                  onChange={(e) => {
                    setKey(e.target.value);
                    setResult(null);
                  }}
                  placeholder="Paste your TMDB API key"
                  autoComplete="off"
                  spellCheck={false}
                  className={`${inputCls} min-w-[16rem] flex-1 font-mono`}
                  aria-label="TMDB API key"
                />
                <button type="button" onClick={test} disabled={!key.trim() || busy !== null} className={smallButtonCls}>
                  {busy === "test" ? "Testing..." : "Test"}
                </button>
                <button type="submit" disabled={!key.trim() || busy !== null} className={primaryButtonCls}>
                  {busy === "save" ? "Saving..." : "Save"}
                </button>
                {editing ? (
                  <button
                    type="button"
                    className={smallButtonCls}
                    onClick={() => {
                      setEditing(false);
                      setKey("");
                      setResult(null);
                    }}
                  >
                    Cancel
                  </button>
                ) : null}
              </form>
            </>
          ) : null}

          {result ? (
            <p className={`text-xs ${result.ok ? "text-emerald-400" : "text-red-400"}`}>{result.message}</p>
          ) : null}

          {data.podcastindex ? (
            <PodcastIndexBlock status={data.podcastindex} onChange={(podcastindex) => setData({ ...data, podcastindex })} />
          ) : null}
        </div>
      )}
    </div>
  );
}

// Podcast Index: the directory behind podcast search. Optional; with no key,
// search uses Apple's iTunes directory. The key and secret are checked with one
// search before they are saved, a saved pair wins over .env, and the secret is
// write-only: the server tells us only whether one is set.
function PodcastIndexBlock({
  status,
  onChange,
}: {
  status: PodcastIndexStatus;
  onChange: (next: PodcastIndexStatus) => void;
}) {
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"test" | "save" | "remove" | null>(null);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const showForm = !status.configured || editing;
  const filled = key.trim() !== "" && secret.trim() !== "";

  async function test() {
    if (busy) return;
    // Blank fields test the pair that is in use now.
    if (!filled && (key.trim() || secret.trim())) {
      setResult({ ok: false, message: "Enter both the key and the secret." });
      return;
    }
    setBusy("test");
    setResult(null);
    try {
      setResult(
        await apiPost<TmdbKeyCheck>("/api/admin/metadata/podcastindex/test", {
          key: key.trim(),
          secret: secret.trim(),
        }),
      );
    } catch (err) {
      setResult({ ok: false, message: err instanceof Error ? err.message : "Check failed." });
    } finally {
      setBusy(null);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!filled || busy) return;
    setBusy("save");
    setResult(null);
    try {
      const res = await apiPut<MetadataSettings>("/api/admin/metadata/podcastindex", {
        key: key.trim(),
        secret: secret.trim(),
      });
      onChange(res.podcastindex);
      setKey("");
      setSecret("");
      setEditing(false);
      setResult({ ok: true, message: "Saved. Podcast search uses Podcast Index now." });
    } catch (err) {
      const msg = err instanceof ApiError && err.detail ? err.detail : err instanceof Error ? err.message : "Could not save.";
      setResult({ ok: false, message: msg });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (busy) return;
    if (!window.confirm("Remove the Podcast Index key? Podcast search goes back to Apple's iTunes directory.")) return;
    setBusy("remove");
    setResult(null);
    try {
      const res = await apiDelete<MetadataSettings>("/api/admin/metadata/podcastindex");
      onChange(res.podcastindex);
      setResult({
        ok: true,
        message: res.podcastindex.configured
          ? "Removed. The key from Setup is used again."
          : "Removed. Search uses Apple's iTunes directory.",
      });
    } catch (err) {
      setResult({ ok: false, message: err instanceof Error ? err.message : "Could not remove." });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3 border-t border-neutral-800 pt-4" data-testid="podcastindex-block">
      <p className="text-xs text-neutral-500">
        Podcast Index is the directory behind podcast search. It is free and optional: with no key,
        search uses Apple&apos;s iTunes directory.
      </p>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-neutral-400">Podcast Index key:</span>
        {status.configured ? (
          <>
            <span className="font-mono text-neutral-100">{status.key_masked}</span>
            <span className="text-xs text-neutral-500">
              {status.source === "env" ? "(from Setup)" : "(saved here)"}
              {status.secret_set ? ", secret set" : ""}
            </span>
            {!editing ? (
              <button type="button" className={smallButtonCls} onClick={() => setEditing(true)}>
                Change
              </button>
            ) : null}
            {status.source === "admin" ? (
              <button type="button" className={smallButtonCls} onClick={remove} disabled={busy !== null}>
                {busy === "remove" ? "Removing..." : "Remove"}
              </button>
            ) : null}
            <button type="button" className={smallButtonCls} onClick={test} disabled={busy !== null}>
              {busy === "test" ? "Testing..." : "Test"}
            </button>
          </>
        ) : (
          <span className="text-amber-400">not set (using iTunes)</span>
        )}
      </div>

      {showForm ? (
        <>
          <p className="text-xs text-neutral-400">
            Make a free account at{" "}
            <a href={PODCASTINDEX_SIGNUP} target="_blank" rel="noreferrer" className="underline hover:text-white">
              api.podcastindex.org
            </a>
            . It emails you an API key and a secret; paste both here.
          </p>
          <form onSubmit={save} className="flex flex-wrap gap-2">
            <input
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
                setResult(null);
              }}
              placeholder="API key"
              autoComplete="off"
              spellCheck={false}
              className={`${inputCls} min-w-[12rem] flex-1 font-mono`}
              aria-label="Podcast Index API key"
            />
            <input
              value={secret}
              onChange={(e) => {
                setSecret(e.target.value);
                setResult(null);
              }}
              type="password"
              placeholder="API secret"
              autoComplete="off"
              spellCheck={false}
              className={`${inputCls} min-w-[12rem] flex-1 font-mono`}
              aria-label="Podcast Index API secret"
            />
            <button type="button" onClick={test} disabled={!filled || busy !== null} className={smallButtonCls}>
              {busy === "test" ? "Testing..." : "Test"}
            </button>
            <button type="submit" disabled={!filled || busy !== null} className={primaryButtonCls}>
              {busy === "save" ? "Saving..." : "Save"}
            </button>
            {editing ? (
              <button
                type="button"
                className={smallButtonCls}
                onClick={() => {
                  setEditing(false);
                  setKey("");
                  setSecret("");
                  setResult(null);
                }}
              >
                Cancel
              </button>
            ) : null}
          </form>
        </>
      ) : null}

      {result ? (
        <p className={`text-xs ${result.ok ? "text-emerald-400" : "text-red-400"}`}>{result.message}</p>
      ) : null}
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500";

const primaryButtonCls =
  "rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60";

const smallButtonCls =
  "rounded-md border border-neutral-800 px-2.5 py-1 text-xs text-neutral-200 transition hover:border-neutral-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-50";
