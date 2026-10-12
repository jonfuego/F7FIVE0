// One podcast: art, description, follow or unfollow, auto-download, and the
// episodes newest first with their state, Play, Download to server, and mark
// played or unplayed. Video podcasts are listed but not played.
//
// Everything about an episode's state (new, in progress, played) is the
// signed-in person's own. Descriptions are plain text; render them as text.

"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { GridEmpty } from "@/components/Grid";
import { apiDelete, apiGet, apiPatch, apiPost, ApiError } from "@/lib/client-api";
import { artSized } from "@/lib/art-url";
import { formatDuration } from "@/lib/format";
import { episodeStateLabel, progressFraction } from "@/lib/podcast-state";
import { episodeToQueueItem } from "@/lib/podcast-queue";
import { useQueue } from "@/lib/queue";
import { useIsAdmin } from "@/lib/use-is-admin";
import type { PodcastDetail, PodcastEpisode, PodcastProgress, PodcastShow } from "@/lib/types";

const PAGE = 200;

const FRIENDLY: Record<string, string> = {
  no_podcast_folder: "There is no podcasts folder yet. An admin can add one in Admin > Library folders.",
  podcast_folder_unreachable: "The podcasts folder cannot be opened right now.",
  not_subscribed: "Follow the show first.",
  video_not_supported: "Video podcasts aren't supported yet.",
  nothing_to_download: "This episode has no file to download.",
  download_not_started: "The download could not be started.",
};

function errorText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return FRIENDLY[err.detail] ?? err.detail;
  return err instanceof Error ? err.message : "Something went wrong.";
}

export default function PodcastPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const isAdmin = useIsAdmin();
  const [detail, setDetail] = useState<PodcastDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [queued, setQueued] = useState<Set<string>>(new Set());
  const pollRef = useRef<number | null>(null);

  // Load a page of episodes. offset 0 (re)loads the first page; a later offset
  // adds the next page under the ones already shown.
  const load = useCallback(
    async (offset = 0) => {
      try {
        const res = await apiGet<PodcastDetail>(`/api/library/podcasts/${id}?limit=${PAGE}&offset=${offset}`);
        setDetail((prev) =>
          offset > 0 && prev ? { ...res, episodes: [...prev.episodes, ...res.episodes] } : res,
        );
        setError(null);
      } catch (err) {
        setError(errorText(err));
      }
    },
    [id],
  );

  useEffect(() => {
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // While a download is queued, look again every few seconds until the file shows up.
  useEffect(() => {
    if (queued.size === 0) return;
    const started = Date.now();
    pollRef.current = window.setInterval(() => {
      if (Date.now() - started > 5 * 60_000) {
        setQueued(new Set());
        return;
      }
      void load(0);
    }, 5000);
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queued.size]);

  useEffect(() => {
    if (!detail || queued.size === 0) return;
    const done = detail.episodes.filter((e) => e.has_file && queued.has(e.id)).map((e) => e.id);
    if (done.length > 0) {
      setQueued((prev) => {
        const next = new Set(prev);
        done.forEach((d) => next.delete(d));
        return next;
      });
    }
  }, [detail, queued]);

  function patchEpisode(next: PodcastEpisode) {
    setDetail((prev) =>
      prev ? { ...prev, episodes: prev.episodes.map((e) => (e.id === next.id ? next : e)) } : prev,
    );
  }

  async function follow(on: boolean) {
    if (!detail || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      if (on) {
        const show = await apiPost<PodcastShow>("/api/library/podcasts/subscribe", { podcast_id: id });
        setDetail({ ...detail, podcast: show });
      } else {
        await apiDelete(`/api/library/podcasts/${id}/subscription`);
        setDetail({ ...detail, podcast: { ...detail.podcast, subscribed: false, auto_download: false } });
      }
    } catch (err) {
      setNotice(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function setAuto(on: boolean) {
    if (!detail || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      await apiPatch(`/api/library/podcasts/${id}/subscription`, { auto_download: on });
      setDetail({ ...detail, podcast: { ...detail.podcast, auto_download: on } });
    } catch (err) {
      setNotice(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function setPlayed(ep: PodcastEpisode, played: boolean) {
    setNotice(null);
    try {
      const res = played
        ? await apiPost<PodcastProgress>(`/api/library/podcasts/episodes/${ep.id}/played`, {})
        : await apiDelete<PodcastProgress>(`/api/library/podcasts/episodes/${ep.id}/played`);
      patchEpisode({ ...ep, state: res.state });
    } catch (err) {
      setNotice(errorText(err));
    }
  }

  async function download(ep: PodcastEpisode) {
    setNotice(null);
    try {
      const res = await apiPost<{ already_downloaded?: boolean; queued?: boolean }>(
        `/api/library/podcasts/episodes/${ep.id}/download`,
        {},
      );
      if (res?.already_downloaded) {
        void load(0);
        return;
      }
      setQueued((prev) => new Set(prev).add(ep.id));
    } catch (err) {
      setNotice(errorText(err));
    }
  }

  async function removeDownload(ep: PodcastEpisode) {
    if (!window.confirm(`Remove the downloaded file for "${ep.title}" from the server? You can still stream it.`)) return;
    setNotice(null);
    try {
      await apiDelete(`/api/admin/podcasts/episodes/${ep.id}/download`);
      patchEpisode({ ...ep, has_file: false, downloaded_by_f7five0: false });
    } catch (err) {
      setNotice(errorText(err));
    }
  }

  if (error && !detail) {
    return (
      <AuthShell>
        <GridEmpty message={error} />
      </AuthShell>
    );
  }
  if (!detail) {
    return (
      <AuthShell>
        <div className="page-pad pt-8">
          <div className="h-40 animate-pulse rounded-lg bg-neutral-900" />
        </div>
      </AuthShell>
    );
  }

  const show = detail.podcast;
  return (
    <AuthShell>
      <div className="page-pad pb-12 pt-8">
        <div className="flex flex-wrap gap-6">
          <div className="h-40 w-40 shrink-0 overflow-hidden rounded-lg bg-neutral-900">
            {show.art_url ? (
              <img src={artSized(show.art_url, 600) ?? show.art_url} alt="" className="h-full w-full object-cover" />
            ) : null}
          </div>
          <div className="min-w-0 flex-1 space-y-3" style={{ minWidth: "16rem" }}>
            <h1 className="text-2xl font-bold text-neutral-50">{show.title}</h1>
            {show.author ? <p className="text-sm text-neutral-400">{show.author}</p> : null}
            {show.description ? (
              <p className="max-w-3xl whitespace-pre-line text-sm text-neutral-300">{show.description}</p>
            ) : null}
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                className={show.subscribed ? smallButtonCls : primaryButtonCls}
                onClick={() => void follow(!show.subscribed)}
                disabled={busy}
              >
                {show.subscribed ? "Unfollow" : "Follow"}
              </button>
              {show.subscribed ? (
                <label className="flex items-center gap-2 text-sm text-neutral-300">
                  <input
                    type="checkbox"
                    checked={show.auto_download}
                    onChange={(e) => void setAuto(e.target.checked)}
                    disabled={busy}
                  />
                  Download new episodes to the server
                </label>
              ) : null}
            </div>
            {show.last_error ? (
              <p className="text-xs text-amber-400">
                The last check of this feed failed: {show.last_error}. The episodes below are from the last good copy.
              </p>
            ) : null}
            {notice ? (
              <p className="text-xs text-red-400" role="alert">
                {notice}
              </p>
            ) : null}
          </div>
        </div>

        <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wider text-neutral-400">
          Episodes <span className="text-neutral-500">({detail.total})</span>
        </h2>
        {detail.episodes.length === 0 ? (
          <p className="text-sm text-neutral-500">
            {show.last_checked_at ? "No episodes in this feed." : "Fetching the feed. Check back in a moment."}
          </p>
        ) : (
          <ul className="space-y-1.5" data-testid="podcast-episodes">
            {detail.episodes.map((ep) => (
              <EpisodeRow
                key={ep.id}
                ep={ep}
                subscribed={show.subscribed}
                isAdmin={isAdmin}
                queued={queued.has(ep.id)}
                onPlayed={(p) => void setPlayed(ep, p)}
                onDownload={() => void download(ep)}
                onRemove={() => void removeDownload(ep)}
              />
            ))}
          </ul>
        )}
        {detail.episodes.length < detail.total ? (
          <button type="button" className={`${smallButtonCls} mt-4`} onClick={() => void load(detail.episodes.length)}>
            Show more episodes
          </button>
        ) : null}
      </div>
    </AuthShell>
  );
}

function EpisodeRow({
  ep,
  subscribed,
  isAdmin,
  queued,
  onPlayed,
  onDownload,
  onRemove,
}: {
  ep: PodcastEpisode;
  subscribed: boolean;
  isAdmin: boolean;
  queued: boolean;
  onPlayed: (played: boolean) => void;
  onDownload: () => void;
  onRemove: () => void;
}) {
  const { playNow } = useQueue();
  const fraction = progressFraction(ep.state, ep.duration_sec);
  const played = ep.state.kind === "played";
  const date = ep.published_at ? new Date(ep.published_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "";
  return (
    <li className="rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-3" data-testid="podcast-episode">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1" style={{ minWidth: "14rem" }}>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className={`text-sm font-medium ${played ? "text-neutral-500" : "text-neutral-100"}`}>{ep.title}</span>
            <span className="text-xs text-neutral-500">
              {[date, ep.duration_sec ? formatDuration(ep.duration_sec) : ""].filter(Boolean).join(" · ")}
            </span>
          </div>
          {ep.description ? (
            <p className="mt-1 line-clamp-3 whitespace-pre-line text-xs text-neutral-400">{ep.description}</p>
          ) : null}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className={ep.state.kind === "new" ? "text-emerald-400" : "text-neutral-500"}>
              {episodeStateLabel(ep.state, ep.duration_sec)}
            </span>
            {ep.state.kind === "in_progress" ? (
              <div className="h-1 w-24 overflow-hidden rounded-full bg-neutral-800" aria-hidden="true">
                <div className="h-full bg-neutral-300" style={{ width: `${Math.round(fraction * 100)}%` }} />
              </div>
            ) : null}
            {ep.has_file ? <span className="rounded border border-neutral-700 px-1.5 text-neutral-400">on this server</span> : null}
            {queued ? <span className="text-amber-400">download queued</span> : null}
            {ep.is_video ? <span className="text-neutral-500">Video podcasts aren&apos;t supported yet</span> : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={primaryButtonCls}
            onClick={() => playNow(episodeToQueueItem(ep))}
            disabled={ep.is_video}
            aria-label={`Play ${ep.title}`}
          >
            {ep.state.kind === "in_progress" ? "Resume" : "Play"}
          </button>
          {!ep.is_video && !ep.has_file && subscribed ? (
            <button type="button" className={smallButtonCls} onClick={onDownload} disabled={queued}>
              {queued ? "Queued" : "Download to server"}
            </button>
          ) : null}
          <button type="button" className={smallButtonCls} onClick={() => onPlayed(!played)}>
            {played ? "Mark unplayed" : "Mark played"}
          </button>
          {isAdmin && ep.downloaded_by_f7five0 ? (
            <button type="button" className={smallButtonCls} onClick={onRemove}>
              Remove file
            </button>
          ) : null}
        </div>
      </div>
    </li>
  );
}

const primaryButtonCls =
  "rounded-lg bg-neutral-100 px-4 py-1.5 text-sm font-medium text-neutral-900 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60";

const smallButtonCls =
  "inline-flex items-center rounded-md border border-neutral-800 px-2.5 py-1 text-xs text-neutral-200 transition hover:border-neutral-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-50";
