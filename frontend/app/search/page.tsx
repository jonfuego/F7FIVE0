// Cross-type library search. Marquee command-palette treatment: a
// centered card with a mono-font input, results grouped Movies / TV /
// Albums (capped 4 / 4 / 3), and an editorial empty-state copy.
//
// Keyboard:
//   - Esc inside the input clears the query (and bubbles up to the
//     global listener which navigates back).
//   - "/" from anywhere in the layout focuses this page.
//   - ⌘K / Ctrl+K from anywhere navigates here (handled in MarqueeTop).

"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/AuthShell";
import { apiGet, apiPost, ApiError } from "@/lib/client-api";
import {
  colorForTitle,
  hueFromString,
  joinMeta,
} from "@/lib/format";
import { useScrollRestoration } from "@/lib/scroll-restoration";
import { useFeatures } from "@/lib/features";
import type { RequestKind, RequestSearchResult, SearchResult } from "@/lib/types";

const DEBOUNCE_MS = 200;
const RESULT_LIMIT = 40;

export default function SearchPage() {
  return (
    <Suspense fallback={<SearchShellFallback />}>
      <SearchPageInner />
    </Suspense>
  );
}

function SearchShellFallback() {
  return (
    <AuthShell>
      <div className="cmdk" style={{ position: "static", minHeight: "60vh" }}>
        <div className="box">
          <div className="input-row">
            <span className="ic">⌕</span>
            <input placeholder="Search F7FIVE0…" disabled />
          </div>
        </div>
      </div>
    </AuthShell>
  );
}

function SearchPageInner() {
  useScrollRestoration();
  const router = useRouter();
  const params = useSearchParams();
  const initialQ = params.get("q") ?? "";
  const initialDeep = params.get("deep") === "true";

  const [query, setQuery] = useState(initialQ);
  // Deep search widens matching to episode and track titles. Off by default;
  // surfaced via the empty-results "Search everything" link and kept in the
  // URL so a deep search is shareable / reloadable.
  const [deep, setDeep] = useState(initialDeep);
  const [results, setResults] = useState<SearchResult[] | null>(
    initialQ.trim() ? null : [],
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Escape from anywhere on this page closes the results view. We try
  // router.back() first; if the user landed here from a deep link with
  // no history, fall back to the home route.
  useEffect(() => {
    function dismiss() {
      if (typeof window !== "undefined" && window.history.length > 1) {
        router.back();
      } else {
        router.push("/");
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        dismiss();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  useEffect(() => {
    const q = query.trim();
    const next = new URLSearchParams();
    if (q) next.set("q", q);
    if (deep) next.set("deep", "true");
    const suffix = next.toString();
    router.replace(suffix ? `/search?${suffix}` : "/search");
  }, [query, deep, router]);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const qs = new URLSearchParams({ q, limit: String(RESULT_LIMIT) });
        if (deep) qs.set("deep", "true");
        const data = await apiGet<SearchResult[]>(
          `/api/library/search?${qs.toString()}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setResults(data);
        setError(null);
      } catch (err) {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError) {
          setError(err.message);
        } else if (err instanceof Error) {
          if (err.name === "AbortError") return;
          setError(err.message);
        } else {
          setError("Search failed.");
        }
        setResults([]);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, deep]);

  const grouped = useMemo(() => groupResults(results ?? []), [results]);

  const trimmed = query.trim();
  const noMatches =
    trimmed.length > 0 &&
    !loading &&
    results !== null &&
    grouped.movies.length === 0 &&
    grouped.tv.length === 0 &&
    grouped.albums.length === 0 &&
    !error;

  return (
    <AuthShell>
      <div
        className="cmdk"
        style={{
          position: "static",
          minHeight: "70vh",
          background: "transparent",
          backdropFilter: "none",
          padding: "48px 16px",
        }}
      >
        <div className="box">
          <div className="input-row">
            <span className="ic" aria-hidden>⌕</span>
            <input
              ref={inputRef}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search F7FIVE0…"
              spellCheck={false}
              autoComplete="off"
              aria-label="Search the library"
            />
            <button
              type="button"
              onClick={() => {
                if (typeof window !== "undefined" && window.history.length > 1) {
                  router.back();
                } else {
                  router.push("/");
                }
              }}
              aria-label="Close search"
              title="Close (Esc)"
              style={{
                fontFamily: "var(--mono)",
                fontSize: 10,
                color: "var(--ink-3)",
                border: "1px solid var(--line)",
                padding: "4px 10px",
                borderRadius: 3,
                cursor: "pointer",
                background: "transparent",
              }}
            >
              ESC
            </button>
          </div>
          <div className="body">
            {deep ? (
              <div style={{ padding: "10px 24px 0" }}>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    fontFamily: "var(--mono)",
                    fontSize: 11,
                    letterSpacing: "0.12em",
                    textTransform: "uppercase",
                    color: "var(--ink-2)",
                    border: "1px solid var(--line)",
                    borderRadius: 3,
                    padding: "4px 10px",
                  }}
                >
                  Deep search
                  <button
                    type="button"
                    onClick={() => setDeep(false)}
                    aria-label="Turn off deep search"
                    style={{
                      background: "transparent",
                      border: "none",
                      color: "var(--ink-3)",
                      cursor: "pointer",
                      fontSize: 13,
                      lineHeight: 1,
                    }}
                  >
                    ✕
                  </button>
                </span>
              </div>
            ) : null}

            {error ? (
              <div
                style={{
                  padding: "16px 24px",
                  fontFamily: "var(--mono)",
                  fontSize: 12,
                  color: "var(--danger)",
                }}
              >
                {error}
              </div>
            ) : null}

            {grouped.movies.length > 0 ? (
              <>
                <div className="group">Films</div>
                {grouped.movies.map((r) => (
                  <ResultRow key={`m-${r.id}`} r={r} kindLabel={null} />
                ))}
              </>
            ) : null}

            {grouped.tv.length > 0 ? (
              <>
                <div className="group">Television</div>
                {grouped.tv.map((r) => (
                  <ResultRow key={`t-${r.id}`} r={r} kindLabel="Series" />
                ))}
              </>
            ) : null}

            {grouped.albums.length > 0 ? (
              <>
                <div className="group">Records</div>
                {grouped.albums.map((r) => (
                  <ResultRow key={`a-${r.id}`} r={r} kindLabel="Album" />
                ))}
              </>
            ) : null}

            {noMatches ? (
              <div className="empty">
                Nothing in F7FIVE0 for &ldquo;{trimmed}&rdquo;
                {!deep ? (
                  <div style={{ marginTop: 14 }}>
                    <button
                      type="button"
                      onClick={() => setDeep(true)}
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: 11,
                        letterSpacing: "0.14em",
                        textTransform: "uppercase",
                        color: "var(--ink-2)",
                        border: "1px solid var(--line)",
                        borderRadius: 3,
                        padding: "6px 14px",
                        cursor: "pointer",
                        background: "transparent",
                      }}
                    >
                      Search everything
                    </button>
                    <div
                      style={{
                        marginTop: 8,
                        fontFamily: "var(--mono)",
                        fontSize: 10,
                        color: "var(--ink-3)",
                      }}
                    >
                      Includes episode and track titles
                    </div>
                  </div>
                ) : null}
                <RequestFromSearch query={trimmed} />
              </div>
            ) : null}

            {trimmed.length === 0 && !loading ? (
              <div
                className="empty"
                style={{
                  fontStyle: "normal",
                  color: "var(--ink-3)",
                  fontFamily: "var(--serif)",
                  fontVariationSettings: '"opsz" 144',
                }}
              >
                Type a title, an artist, or a year. Try /
              </div>
            ) : null}

            {loading && (results === null || results.length === 0) ? (
              <div
                style={{
                  padding: "16px 24px",
                  fontFamily: "var(--mono)",
                  fontSize: 11,
                  letterSpacing: "0.18em",
                  textTransform: "uppercase",
                  color: "var(--ink-3)",
                }}
              >
                Searching…
              </div>
            ) : null}
          </div>
          <div className="foot">
            <span>
              <span className="kbd">↑</span>
              <span className="kbd">↓</span> navigate
            </span>
            <span>
              <span className="kbd">↵</span> open ·{" "}
              <span className="kbd">ESC</span> close
            </span>
          </div>
        </div>
      </div>
    </AuthShell>
  );
}

function ResultRow({
  r,
  kindLabel,
}: {
  r: SearchResult;
  kindLabel: string | null;
}) {
  const tint: CSSProperties = {
    ["--pg" as never]: colorForTitle(r.title),
    ["--ph" as never]: String(hueFromString(r.title)),
  };
  const sub = joinMeta([r.year, r.subtitle, kindLabel]);
  return (
    <Link href={hrefFor(r)} className="res" style={tint}>
      <div className="sw">
        <div className="keyart-mini" />
        {r.poster_path ? (
          <img
            src={r.poster_path}
            alt=""
            loading="lazy"
            decoding="async"
            className="real-art"
          />
        ) : null}
      </div>
      <div className="body">
        <div className="t">{r.title}</div>
        {sub ? <div className="s">{sub}</div> : null}
      </div>
      {kindLabel ? <div className="right">{kindLabel}</div> : null}
    </Link>
  );
}

// Request fallthrough shown on the no-results state: search the *arr catalog
// for the same query and file a request. Reuses /api/requests/{search,create}.
function RequestFromSearch({ query }: { query: string }) {
  const features = useFeatures();
  if (!features?.requests.enabled) return null;
  return <RequestFromSearchInner query={query} />;
}

function RequestFromSearchInner({ query }: { query: string }) {
  const [kind, setKind] = useState<RequestKind | null>(null);
  const [results, setResults] = useState<RequestSearchResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [requesting, setRequesting] = useState<string | null>(null);

  async function lookup(k: RequestKind) {
    setKind(k);
    setBusy(true);
    setErr(null);
    setResults(null);
    try {
      const data = await apiGet<RequestSearchResult[]>(
        `/api/requests/search?kind=${k}&q=${encodeURIComponent(query)}`,
      );
      setResults(data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Catalog lookup failed.");
    } finally {
      setBusy(false);
    }
  }

  function markRequested(extId: string) {
    setResults((prev) =>
      prev ? prev.map((x) => (x.external_id === extId ? { ...x, requested: true } : x)) : prev,
    );
  }

  async function request(r: RequestSearchResult) {
    setRequesting(r.external_id);
    setErr(null);
    try {
      await apiPost("/api/requests", {
        kind: r.kind, external_id: r.external_id,
        title: r.title, year: r.year, poster_url: r.poster_url,
      });
      markRequested(r.external_id);
    } catch (e) {
      if (e instanceof ApiError && e.detail === "already_requested") {
        markRequested(r.external_id);
      } else {
        setErr(e instanceof Error ? e.message : "Request failed.");
      }
    } finally {
      setRequesting(null);
    }
  }

  const pill = (active: boolean): CSSProperties => ({
    fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.14em",
    textTransform: "uppercase", padding: "6px 14px", borderRadius: 3,
    cursor: "pointer", border: "1px solid var(--line)",
    background: active ? "var(--ink)" : "transparent",
    color: active ? "var(--bg)" : "var(--ink-2)",
  });

  return (
    <div style={{ marginTop: 22, textAlign: "left", maxWidth: 600, marginInline: "auto" }}>
      <div style={{ fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--ink-3)", marginBottom: 10 }}>
        Not in the library? Request it
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" style={pill(kind === "movie")} onClick={() => lookup("movie")}>Find movie</button>
        <button type="button" style={pill(kind === "series")} onClick={() => lookup("series")}>Find show</button>
      </div>

      {busy ? (
        <div style={{ marginTop: 12, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>Searching the catalog…</div>
      ) : null}
      {err ? (
        <div style={{ marginTop: 12, fontFamily: "var(--mono)", fontSize: 12, color: "var(--danger)" }}>{err}</div>
      ) : null}
      {results && !busy && results.length === 0 ? (
        <div style={{ marginTop: 12, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>
          No catalog matches for &ldquo;{query}&rdquo;.
        </div>
      ) : null}

      {results && results.length > 0 ? (
        <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
          {results.map((r) => (
            <div key={`${r.kind}-${r.external_id}`} style={{ display: "flex", gap: 12, alignItems: "center", border: "1px solid var(--line)", borderRadius: 4, padding: 10 }}>
              {r.poster_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={r.poster_url} alt="" style={{ width: 44, height: 66, objectFit: "cover", borderRadius: 2, flexShrink: 0 }} />
              ) : (
                <div style={{ width: 44, height: 66, background: "var(--bg-2)", borderRadius: 2, flexShrink: 0 }} />
              )}
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontFamily: "var(--grotesk)", fontSize: 14, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.title}{r.year ? <span style={{ color: "var(--ink-3)" }}> ({r.year})</span> : null}
                </div>
                {r.overview ? (
                  <div style={{ marginTop: 3, fontSize: 11, color: "var(--ink-3)", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{r.overview}</div>
                ) : null}
              </div>
              <div style={{ flexShrink: 0 }}>
                {r.in_library ? (
                  <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--positive)" }}>In library</span>
                ) : r.requested ? (
                  <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--ink-2)" }}>Requested</span>
                ) : (
                  <button type="button" onClick={() => request(r)} disabled={requesting === r.external_id} style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", padding: "6px 12px", borderRadius: 3, border: "1px solid var(--line)", background: "transparent", color: "var(--ink)", cursor: "pointer" }}>
                    {requesting === r.external_id ? "…" : "Request"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

type Grouped = {
  movies: SearchResult[];
  tv: SearchResult[];
  albums: SearchResult[];
};

function groupResults(results: SearchResult[]): Grouped {
  const movies: SearchResult[] = [];
  const tv: SearchResult[] = [];
  const albums: SearchResult[] = [];
  for (const r of results) {
    if (r.kind === "movie") movies.push(r);
    else if (r.kind === "series") tv.push(r);
    else if (r.kind === "album") albums.push(r);
  }
  // Caps: Movies 4, TV 4, Albums 3 — matches the prototype ratios.
  return {
    movies: movies.slice(0, 4),
    tv: tv.slice(0, 4),
    albums: albums.slice(0, 3),
  };
}

function hrefFor(r: SearchResult): string {
  switch (r.kind) {
    case "movie":
      return `/movies/${r.id}`;
    case "series":
      return `/series/${r.id}`;
    case "album":
      return `/music/${r.id}`;
  }
}
