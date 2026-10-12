// Podcasts: what you are partway through, the shows you follow, the shows on this
// server (so a show found in a podcasts folder can be followed too), search, add by
// feed URL, and OPML import and export.
//
// Subscriptions and progress are per person. Plain text only: descriptions are
// stripped of markup by the server and rendered as text.

"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AuthShell } from "@/components/AuthShell";
import { Grid, GridEmpty } from "@/components/Grid";
import { PodcastTile } from "@/components/PodcastTile";
import { apiGet, apiPost, ApiError } from "@/lib/client-api";
import { artSized } from "@/lib/art-url";
import { progressFraction, episodeStateLabel } from "@/lib/podcast-state";
import { episodeToQueueItem } from "@/lib/podcast-queue";
import { useQueue } from "@/lib/queue";
import type {
  PodcastEpisode, PodcastHome, PodcastOpmlResult, PodcastSearch, PodcastSearchResult, PodcastShow,
} from "@/lib/types";

const FRIENDLY: Record<string, string> = {
  feed_unreachable: "That feed could not be reached.",
  feed_invalid: "That address is not a podcast feed.",
  feed_blocked: "That address is not allowed (it points at this network).",
  search_failed: "The podcast directory could not be searched right now.",
  invalid_opml: "That file is not a readable OPML file.",
  opml_too_large: "That file is larger than 1 MB.",
};

function errorText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return FRIENDLY[err.detail] ?? err.detail;
  return err instanceof Error ? err.message : "Something went wrong.";
}

export default function PodcastsPage() {
  const router = useRouter();
  const [home, setHome] = useState<PodcastHome | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setHome(await apiGet<PodcastHome>("/api/library/podcasts"));
      setError(null);
    } catch (err) {
      setError(errorText(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const mineIds = new Set((home?.mine ?? []).map((s) => s.id));
  const onServer = (home?.on_server ?? []).filter((s) => !mineIds.has(s.id));

  return (
    <AuthShell>
      <h1 className="page-title">Podcasts</h1>

      <div className="page-pad space-y-8 pb-12 pt-4">
        <AddShows onAdded={(show) => router.push(`/podcasts/${show.id}`)} onImported={load} />

        {error ? <GridEmpty message={error} /> : null}

        {home && home.in_progress.length > 0 ? (
          <section aria-labelledby="pod-in-progress">
            <h2 id="pod-in-progress" className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-400">
              In progress
            </h2>
            <ul className="space-y-1.5">
              {home.in_progress.map((ep) => (
                <InProgressRow key={ep.id} ep={ep} />
              ))}
            </ul>
          </section>
        ) : null}

        <section aria-labelledby="pod-mine">
          <h2 id="pod-mine" className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-400">
            My podcasts
          </h2>
          {home === null ? (
            <div className="h-24 animate-pulse rounded-lg bg-neutral-900" />
          ) : home.mine.length === 0 ? (
            <p className="text-sm text-neutral-500">
              You are not following any podcasts yet. Search above, or paste a feed address.
            </p>
          ) : (
            <Grid variant="square">
              {home.mine.map((show) => (
                <PodcastTile key={show.id} show={show} />
              ))}
            </Grid>
          )}
        </section>

        {onServer.length > 0 ? (
          <section aria-labelledby="pod-server">
            <h2 id="pod-server" className="mb-1 text-sm font-semibold uppercase tracking-wider text-neutral-400">
              On this server
            </h2>
            <p className="mb-3 text-xs text-neutral-500">
              Shows with episodes in a podcasts folder. Open one to follow it.
            </p>
            <Grid variant="square">
              {onServer.map((show) => (
                <PodcastTile key={show.id} show={show} />
              ))}
            </Grid>
          </section>
        ) : null}
      </div>
    </AuthShell>
  );
}

function InProgressRow({ ep }: { ep: PodcastEpisode }) {
  const { playNow } = useQueue();
  const fraction = progressFraction(ep.state, ep.duration_sec);
  return (
    <li className="flex items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2">
      <div className="h-12 w-12 shrink-0 overflow-hidden rounded bg-neutral-900">
        {ep.art_url ? (
          <img src={artSized(ep.art_url, 300) ?? ep.art_url} alt="" className="h-full w-full object-cover" loading="lazy" />
        ) : null}
      </div>
      <div className="min-w-0 flex-1">
        <Link href={`/podcasts/${ep.podcast_id}`} className="block truncate text-xs text-neutral-400 hover:text-neutral-200">
          {ep.podcast_title}
        </Link>
        <div className="truncate text-sm text-neutral-100">{ep.title}</div>
        <div className="mt-1 flex items-center gap-2 text-xs text-neutral-500">
          <span>{episodeStateLabel(ep.state, ep.duration_sec)}</span>
          <div className="h-1 w-24 overflow-hidden rounded-full bg-neutral-800" aria-hidden="true">
            <div className="h-full bg-neutral-300" style={{ width: `${Math.round(fraction * 100)}%` }} />
          </div>
        </div>
      </div>
      <button
        type="button"
        className={smallButtonCls}
        onClick={() => playNow(episodeToQueueItem(ep))}
        disabled={ep.is_video}
        aria-label={`Resume ${ep.title}`}
      >
        Resume
      </button>
    </li>
  );
}

function AddShows({
  onAdded,
  onImported,
}: {
  onAdded: (show: PodcastShow) => void;
  onImported: () => void | Promise<void>;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PodcastSearch | null>(null);
  const [feedUrl, setFeedUrl] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function search(e: FormEvent) {
    e.preventDefault();
    const term = q.trim();
    if (!term || busy) return;
    setBusy("search");
    setMessage(null);
    try {
      setResults(await apiGet<PodcastSearch>(`/api/library/podcasts/search?q=${encodeURIComponent(term)}`));
    } catch (err) {
      setResults(null);
      setMessage({ ok: false, text: errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  async function subscribe(feed: string, key: string) {
    if (busy) return;
    setBusy(key);
    setMessage(null);
    try {
      onAdded(await apiPost<PodcastShow>("/api/library/podcasts/subscribe", { feed_url: feed }));
    } catch (err) {
      setMessage({ ok: false, text: errorText(err) });
      setBusy(null);
    }
  }

  async function addByUrl(e: FormEvent) {
    e.preventDefault();
    const url = feedUrl.trim();
    if (!url) return;
    await subscribe(url, "url");
  }

  async function importFile(file: File) {
    setBusy("import");
    setMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/library/podcasts/opml", { method: "POST", body: form });
      if (res.status === 401) {
        window.location.reload();
        return;
      }
      const body = (await res.json().catch(() => null)) as (PodcastOpmlResult & { detail?: string }) | null;
      if (!res.ok || !body) {
        setMessage({ ok: false, text: FRIENDLY[body?.detail ?? ""] ?? body?.detail ?? "Could not import that file." });
        return;
      }
      setMessage({
        ok: true,
        text: `Imported: ${body.added} added, ${body.already} already followed, ${body.failed} could not be used. New shows fill in over the next minute.`,
      });
      await onImported();
      window.setTimeout(() => void onImported(), 8000);
    } catch (err) {
      setMessage({ ok: false, text: errorText(err) });
    } finally {
      setBusy(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <section aria-label="Find podcasts" className="space-y-4" data-testid="podcast-add">
      <form onSubmit={search} className="flex flex-wrap gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search for a podcast"
          className={`${inputCls} min-w-[14rem] flex-1`}
          aria-label="Search for a podcast"
        />
        <button type="submit" className={primaryButtonCls} disabled={!q.trim() || busy !== null}>
          {busy === "search" ? "Searching..." : "Search"}
        </button>
      </form>

      {results ? (
        results.results.length === 0 ? (
          <p className="text-sm text-neutral-500">Nothing found for that search.</p>
        ) : (
          <ul className="space-y-1.5" data-testid="podcast-results">
            {results.results.map((r: PodcastSearchResult) => (
              <li key={r.feed_url} className="flex items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2">
                <div className="h-12 w-12 shrink-0 overflow-hidden rounded bg-neutral-900">
                  {r.art_url ? <img src={r.art_url} alt="" className="h-full w-full object-cover" loading="lazy" /> : null}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-neutral-100">{r.title}</div>
                  {r.author ? <div className="truncate text-xs text-neutral-400">{r.author}</div> : null}
                </div>
                <button
                  type="button"
                  className={smallButtonCls}
                  onClick={() => void subscribe(r.feed_url, r.feed_url)}
                  disabled={busy !== null}
                >
                  {busy === r.feed_url ? "Adding..." : "Follow"}
                </button>
              </li>
            ))}
          </ul>
        )
      ) : null}
      {results ? (
        <p className="text-xs text-neutral-500">
          Results from {results.provider === "podcastindex" ? "Podcast Index" : "Apple's iTunes directory"}.
        </p>
      ) : null}

      <form onSubmit={addByUrl} className="flex flex-wrap gap-2">
        <input
          value={feedUrl}
          onChange={(e) => setFeedUrl(e.target.value)}
          placeholder="Add by feed URL (https://...)"
          className={`${inputCls} min-w-[14rem] flex-1 font-mono`}
          aria-label="Add by feed URL"
          spellCheck={false}
        />
        <button type="submit" className={smallButtonCls} disabled={!feedUrl.trim() || busy !== null}>
          {busy === "url" ? "Adding..." : "Add"}
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={fileRef}
          type="file"
          accept=".opml,.xml,text/xml,application/xml,text/x-opml"
          className="hidden"
          aria-label="Import an OPML file"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void importFile(file);
          }}
        />
        <button type="button" className={smallButtonCls} onClick={() => fileRef.current?.click()} disabled={busy !== null}>
          {busy === "import" ? "Importing..." : "Import OPML"}
        </button>
        <a className={smallButtonCls} href="/api/library/podcasts/opml" download="f7five0-podcasts.opml">
          Export OPML
        </a>
        <span className="text-xs text-neutral-500">Move your list to or from another podcast app.</span>
      </div>

      {message ? (
        <p className={`text-xs ${message.ok ? "text-emerald-400" : "text-red-400"}`} role={message.ok ? undefined : "alert"}>
          {message.text}
        </p>
      ) : null}
    </section>
  );
}

const inputCls =
  "w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500";

const primaryButtonCls =
  "rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60";

const smallButtonCls =
  "inline-flex items-center rounded-md border border-neutral-800 px-2.5 py-1 text-xs text-neutral-200 transition hover:border-neutral-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-50";
