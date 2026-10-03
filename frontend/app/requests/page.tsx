// Media requests. Any user can search upstream and request a movie or
// series; admins get an approve/deny queue on the same page.
//
// All traffic goes through the Next BFF at /api/requests/*, which swaps the
// httpOnly cookie for a Bearer token before hitting the backend.

"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { AuthShell } from "@/components/AuthShell";
import { apiGet, apiPost, ApiError } from "@/lib/client-api";
import { useFeatures } from "@/lib/features";
import type {
  MediaRequest, Me, RequestKind, RequestSearchResult, RequestStatus,
} from "@/lib/types";

export default function RequestsPage() {
  const [me, setMe] = useState<Me | null>(null);
  const features = useFeatures();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await fetch("/api/session/me", { cache: "no-store" });
      if (!res.ok) return;
      const profile = (await res.json()) as Me | null;
      if (!cancelled && profile) setMe(profile);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AuthShell>
      <div className="mx-auto max-w-5xl space-y-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Requests</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Search for a movie or show and request it. You will see it here once it is added.
          </p>
        </header>
        {features && !features.requests.enabled ? (
          <p className="text-sm text-neutral-500">
            Requests are not turned on for this server. An admin can enable them
            by connecting Radarr and/or Sonarr.
          </p>
        ) : (
          <>
            <SearchSection />
            <MyRequestsSection />
            {me?.role === "admin" ? <AdminQueueSection /> : null}
          </>
        )}
      </div>
    </AuthShell>
  );
}

// ---------------------------------------------------------------------------
// Search + request
// ---------------------------------------------------------------------------
function SearchSection() {
  const [kind, setKind] = useState<RequestKind>("movie");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<RequestSearchResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const term = q.trim();
    if (!term || busy) return;
    setBusy(true);
    setError(null);
    try {
      const data = await apiGet<RequestSearchResult[]>(
        `/api/requests/search?kind=${kind}&q=${encodeURIComponent(term)}`,
      );
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setBusy(false);
    }
  }

  async function request(r: RequestSearchResult) {
    setRequesting(r.external_id);
    setError(null);
    try {
      await apiPost("/api/requests", {
        kind: r.kind,
        external_id: r.external_id,
        title: r.title,
        year: r.year,
        poster_url: r.poster_url,
      });
      setResults((prev) =>
        prev
          ? prev.map((x) =>
              x.external_id === r.external_id ? { ...x, requested: true } : x,
            )
          : prev,
      );
    } catch (err) {
      if (err instanceof ApiError && err.detail === "already_requested") {
        setResults((prev) =>
          prev
            ? prev.map((x) =>
                x.external_id === r.external_id ? { ...x, requested: true } : x,
              )
            : prev,
        );
      } else {
        setError(err instanceof Error ? err.message : "Request failed.");
      }
    } finally {
      setRequesting(null);
    }
  }

  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
      <h2 className="text-base font-semibold">Find something to watch</h2>
      <form onSubmit={onSubmit} className="mt-4 flex flex-wrap items-center gap-3">
        <div className="inline-flex overflow-hidden rounded-lg border border-neutral-700">
          {(["movie", "series"] as RequestKind[]).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setKind(k)}
              className={`px-3 py-2 text-sm ${
                kind === k
                  ? "bg-neutral-100 text-neutral-900"
                  : "bg-neutral-950 text-neutral-300"
              }`}
            >
              {k === "movie" ? "Movies" : "Shows"}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder={`Search ${kind === "movie" ? "movies" : "shows"}...`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="min-w-[16rem] flex-1 rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500"
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Searching..." : "Search"}
        </button>
      </form>

      {error ? (
        <p className="mt-3 text-sm text-rose-400">{error}</p>
      ) : null}

      {results !== null ? (
        results.length === 0 ? (
          <div className="mt-4 rounded-md border border-dashed border-neutral-800 bg-neutral-900/30 px-4 py-6 text-sm text-neutral-500">
            No matches. Try a different title.
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {results.map((r) => (
              <div
                key={`${r.kind}-${r.external_id}`}
                className="flex gap-3 rounded-lg border border-neutral-800 bg-neutral-950/40 p-3"
              >
                {r.poster_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={r.poster_url}
                    alt=""
                    className="h-24 w-16 flex-none rounded object-cover"
                  />
                ) : (
                  <div className="h-24 w-16 flex-none rounded bg-neutral-800" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-neutral-100">
                    {r.title}
                    {r.year ? <span className="text-neutral-500"> ({r.year})</span> : null}
                  </div>
                  {r.overview ? (
                    <p className="mt-1 line-clamp-2 text-xs text-neutral-500">{r.overview}</p>
                  ) : null}
                  <div className="mt-2">
                    {r.in_library ? (
                      <span className="text-xs text-emerald-400">In your library</span>
                    ) : r.requested ? (
                      <span className="text-xs text-sky-400">Requested</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => request(r)}
                        disabled={requesting === r.external_id}
                        className="rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-100 transition hover:border-neutral-500 disabled:opacity-50"
                      >
                        {requesting === r.external_id ? "Requesting..." : "Request"}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// My requests
// ---------------------------------------------------------------------------
function MyRequestsSection() {
  const [rows, setRows] = useState<MediaRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<MediaRequest[]>("/api/requests/mine");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load your requests.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold">My requests</h2>
        <button type="button" onClick={load} className="text-xs text-neutral-500 hover:text-neutral-200">
          Refresh
        </button>
      </div>
      {error ? (
        <p className="mt-3 text-sm text-rose-400">{error}</p>
      ) : rows === null ? (
        <div className="mt-4 h-16 animate-pulse rounded-md bg-neutral-900" />
      ) : rows.length === 0 ? (
        <div className="mt-4 rounded-md border border-dashed border-neutral-800 bg-neutral-900/30 px-4 py-6 text-sm text-neutral-500">
          You have not requested anything yet.
        </div>
      ) : (
        <ul className="mt-4 divide-y divide-neutral-900">
          {rows.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="truncate text-neutral-200">
                {r.title}
                {r.year ? <span className="text-neutral-500"> ({r.year})</span> : null}
                <span className="ml-2 text-xs text-neutral-600">{r.kind}</span>
              </span>
              <StatusChip status={r.status} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Admin queue
// ---------------------------------------------------------------------------
function AdminQueueSection() {
  const [rows, setRows] = useState<MediaRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<MediaRequest[]>("/api/requests?status=pending");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load the queue.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function act(id: string, action: "approve" | "deny") {
    setActing(id);
    setError(null);
    try {
      const body = action === "deny" ? { note: null } : {};
      await apiPost(`/api/requests/${id}/${action}`, body);
      setRows((prev) => (prev ? prev.filter((r) => r.id !== id) : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : `${action} failed.`);
    } finally {
      setActing(null);
    }
  }

  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold">Pending requests</h2>
        <button type="button" onClick={load} className="text-xs text-neutral-500 hover:text-neutral-200">
          Refresh
        </button>
      </div>
      {error ? (
        <p className="mt-3 text-sm text-rose-400">{error}</p>
      ) : rows === null ? (
        <div className="mt-4 h-16 animate-pulse rounded-md bg-neutral-900" />
      ) : rows.length === 0 ? (
        <div className="mt-4 rounded-md border border-dashed border-neutral-800 bg-neutral-900/30 px-4 py-6 text-sm text-neutral-500">
          Nothing waiting on you.
        </div>
      ) : (
        <ul className="mt-4 divide-y divide-neutral-900">
          {rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm">
              <span className="min-w-0 truncate text-neutral-200">
                {r.title}
                {r.year ? <span className="text-neutral-500"> ({r.year})</span> : null}
                <span className="ml-2 text-xs text-neutral-600">
                  {r.kind} - {r.requested_by ?? "unknown"}
                </span>
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => act(r.id, "approve")}
                  disabled={acting === r.id}
                  className="rounded-md bg-emerald-600/80 px-2.5 py-1 text-xs text-white transition hover:bg-emerald-600 disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  type="button"
                  onClick={() => act(r.id, "deny")}
                  disabled={acting === r.id}
                  className="rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-200 transition hover:border-neutral-500 disabled:opacity-50"
                >
                  Deny
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function StatusChip({ status }: { status: RequestStatus }) {
  const map: Record<RequestStatus, string> = {
    pending: "bg-hive-tint text-hive-text",
    approved: "bg-sky-900/40 text-sky-300",
    denied: "bg-neutral-800 text-neutral-400",
    available: "bg-emerald-900/40 text-emerald-300",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] ${map[status]}`}>
      {status}
    </span>
  );
}
