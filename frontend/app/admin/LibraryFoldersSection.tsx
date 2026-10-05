// Admin > Library folders. Each library (Movies, TV shows, Music, Music
// videos) can use several source folders. Paths are typed (the browser
// can't browse the server's drives); after saving, the server reports which
// folders it can open, as the account its services run under, and starts a
// folder scan.
//
// TV and music merge across folders; the same movie in two folders shows up
// twice. Removing a folder takes its items out of the library without
// deleting anything. See app/services/library_folders.py.

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPut, ApiError } from "@/lib/client-api";
import type { LibraryFolderKind, LibraryFolders } from "@/lib/types";

type Draft = Record<LibraryFolderKind, string[]>;

const HINT: Record<LibraryFolderKind, string> = {
  movies: "The same movie in two folders shows up twice.",
  tv: "Shows merge across folders: seasons on two drives make one show.",
  music: "Artists and albums merge across folders.",
  music_videos: "Artists merge across folders.",
};

function toDraft(data: LibraryFolders): Draft {
  const d = { movies: [], tv: [], music: [], music_videos: [] } as Draft;
  for (const lib of data.libraries) d[lib.kind] = lib.folders.map((f) => f.path);
  return d;
}

function same(a: Draft, b: Draft): boolean {
  return (Object.keys(a) as LibraryFolderKind[]).every(
    (k) => a[k].length === b[k].length && a[k].every((p, i) => p === b[k][i]),
  );
}

export function LibraryFoldersSection() {
  const [data, setData] = useState<LibraryFolders | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [adding, setAdding] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiGet<LibraryFolders>("/api/admin/library-folders");
      setData(res);
      setDraft(toDraft(res));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load library folders.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data || !draft) {
    return (
      <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
        <h2 className="text-base font-semibold">Library folders</h2>
        {error ? (
          <p className="mt-2 text-xs text-red-400">{error}</p>
        ) : (
          <div className="mt-4 h-24 animate-pulse rounded-lg bg-neutral-900" />
        )}
      </section>
    );
  }

  const saved = toDraft(data);
  const dirty = !same(draft, saved);
  const reachable = new Map<string, boolean>();
  for (const lib of data.libraries) for (const f of lib.folders) reachable.set(`${lib.kind}|${f.path}`, f.reachable);

  function addFolder(kind: LibraryFolderKind) {
    const value = (adding[kind] ?? "").trim().replace(/^"|"$/g, "");
    if (!value || !draft) return;
    if (draft[kind].some((p) => p.toLowerCase() === value.toLowerCase())) {
      setAdding({ ...adding, [kind]: "" });
      return;
    }
    setDraft({ ...draft, [kind]: [...draft[kind], value] });
    setAdding({ ...adding, [kind]: "" });
    setStatus(null);
  }

  function removeFolder(kind: LibraryFolderKind, path: string) {
    if (!draft) return;
    setDraft({ ...draft, [kind]: draft[kind].filter((p) => p !== path) });
    setStatus(null);
  }

  async function save() {
    if (!draft || busy) return;
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const res = await apiPut<LibraryFolders>("/api/admin/library-folders", { folders: draft });
      setData(res);
      setDraft(toDraft(res));
      const offline = res.libraries.flatMap((l) => l.folders).filter((f) => !f.reachable).length;
      setStatus(
        offline
          ? `Saved. Scanning now. ${offline} folder${offline === 1 ? "" : "s"} can't be opened by the server yet.`
          : "Saved. Scanning now; new items show up as they're found.",
      );
    } catch (err) {
      if (err instanceof ApiError && err.detail) setError(err.detail);
      else setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
      <h2 className="text-base font-semibold">Library folders</h2>
      <p className="mt-1 text-xs text-neutral-500">
        Each library can use more than one folder, on this PC or a network share
        (like <code>\\nas\media\Movies</code>). Type the path as the server sees it.
        Removing a folder takes its items out of the library; nothing is deleted.
        {data.source === "env" ? " These came from Setup; saving here replaces them." : ""}
      </p>

      <div className="mt-5 space-y-6">
        {data.libraries.map((lib) => {
          const kind = lib.kind;
          return (
            <div key={kind}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium text-neutral-100">{lib.label}</h3>
                <span className="text-xs text-neutral-500">
                  {lib.arr_managed ? "Managed by your *arr app; these folders aren't scanned." : HINT[kind]}
                </span>
              </div>
              <ul className="mt-2 space-y-1.5">
                {draft[kind].length === 0 ? (
                  <li className="text-xs text-neutral-500">No folders. This library is off.</li>
                ) : (
                  draft[kind].map((path) => {
                    const known = reachable.get(`${kind}|${path}`);
                    return (
                      <li
                        key={path}
                        className="flex items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2"
                      >
                        <span className="min-w-0 flex-1 truncate font-mono text-xs text-neutral-200" title={path}>
                          {path}
                        </span>
                        {known === undefined ? (
                          <span className="text-xs text-neutral-500">not saved yet</span>
                        ) : known ? (
                          <span className="text-xs text-emerald-400">found</span>
                        ) : (
                          <span
                            className="text-xs text-amber-400"
                            title="The server can't open this folder. Check the path, that the drive or NAS is on, and that the account the F7FIVE0 services run under can read it."
                          >
                            can&apos;t open
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={() => removeFolder(kind, path)}
                          className={smallButtonCls}
                          aria-label={`Remove ${path}`}
                        >
                          Remove
                        </button>
                      </li>
                    );
                  })
                )}
              </ul>
              <form
                className="mt-2 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  addFolder(kind);
                }}
              >
                <input
                  value={adding[kind] ?? ""}
                  onChange={(e) => setAdding({ ...adding, [kind]: e.target.value })}
                  placeholder={kind === "movies" ? "D:\\Movies or \\\\nas\\media\\Movies" : "Add a folder"}
                  className={inputCls}
                  aria-label={`Add a ${lib.label} folder`}
                />
                <button type="submit" className={smallButtonCls} disabled={!(adding[kind] ?? "").trim()}>
                  Add
                </button>
              </form>
            </div>
          );
        })}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button type="button" onClick={save} disabled={busy || !dirty} className={primaryButtonCls}>
          {busy ? "Saving..." : "Save folders"}
        </button>
        {dirty && !busy ? (
          <button type="button" onClick={() => setDraft(saved)} className={smallButtonCls}>
            Undo changes
          </button>
        ) : null}
        {error ? <span className="text-xs text-red-400">{error}</span> : null}
        {status ? <span className="text-xs text-neutral-400">{status}</span> : null}
      </div>
    </section>
  );
}

const inputCls =
  "w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500";

const primaryButtonCls =
  "rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60";

const smallButtonCls =
  "rounded-md border border-neutral-800 px-2.5 py-1 text-xs text-neutral-200 transition hover:border-neutral-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-50";
