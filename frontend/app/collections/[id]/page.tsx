"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { AuthShell } from "@/components/AuthShell";
import { apiGet } from "@/lib/client-api";

type CollectionItem = {
  entity_kind: string;
  entity_id: string;
  sort_order: number;
};

type CollectionDetail = {
  id: string;
  name: string;
  kind: string | null;
  item_count: number;
  tmdb_collection_id: number | null;
  is_auto: boolean;
  description: string | null;
  items: CollectionItem[];
};

type MovieOut = {
  id: string;
  title: string;
  year: number | null;
  poster_path: string | null;
};

export default function CollectionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [collection, setCollection] = useState<CollectionDetail | null>(null);
  const [movies, setMovies] = useState<MovieOut[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<CollectionDetail>(`/api/library/collections/${id}`);
        if (!cancelled) {
          setCollection(data);
        }
      } catch (err) {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Failed to load collection");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!collection) return;
    let cancelled = false;
    (async () => {
      try {
        const movieItems = collection.items.filter((i) => i.entity_kind === "movie");
        const all = await apiGet<MovieOut[]>("/api/library/movies?limit=20000");
        const ids = new Set(movieItems.map((i) => i.entity_id));
        if (!cancelled) setMovies(all.filter((m) => ids.has(m.id)));
      } catch {
        // ignore; show what we have
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [collection]);

  if (error) {
    return (
      <AuthShell>
        <p style={{ color: "var(--hive-text)" }}>{error}</p>
      </AuthShell>
    );
  }

  if (!collection) {
    return (
      <AuthShell>
        <p style={{ color: "var(--text-2)" }}>Loading...</p>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <Link href="/collections" style={{ fontSize: 14, color: "var(--text-2)", marginBottom: 8, display: "inline-block" }}>
        All collections
      </Link>
      <h1 className="page-title">{collection.name}</h1>
      {collection.description && (
        <p style={{ color: "var(--text-2)", marginBottom: 16 }}>{collection.description}</p>
      )}

      {movies.length === 0 ? (
        <p style={{ color: "var(--text-2)" }}>No movies visible.</p>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
            gap: 24,
          }}
        >
          {movies.map((m) => (
            <Link
              key={m.id}
              href={`/movies/${m.id}`}
              style={{ textDecoration: "none", color: "inherit" }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div
                  style={{
                    width: "100%",
                    aspectRatio: "2/3",
                    background: "var(--surface-2, #181818)",
                    borderRadius: 6,
                    overflow: "hidden",
                  }}
                >
                  {m.poster_path ? (
                    <img
                      src={m.poster_path}
                      alt={m.title}
                      style={{ width: "100%", height: "100%", objectFit: "cover" }}
                    />
                  ) : null}
                </div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{m.title}</div>
                {m.year && <div style={{ fontSize: 12, color: "var(--text-2)" }}>{m.year}</div>}
              </div>
            </Link>
          ))}
        </div>
      )}
    </AuthShell>
  );
}
