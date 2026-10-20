"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AuthShell } from "@/components/AuthShell";
import { apiGet } from "@/lib/client-api";

type CollectionSummary = {
  id: string;
  name: string;
  kind: string | null;
  item_count: number;
  tmdb_collection_id: number | null;
  is_auto: boolean;
  description: string | null;
};

export default function CollectionsPage() {
  const [collections, setCollections] = useState<CollectionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<CollectionSummary[]>("/api/library/collections");
        if (!cancelled) setCollections(data);
      } catch (err) {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Failed to load collections");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AuthShell>
      <h1 className="page-title">Collections</h1>

      {error ? (
        <p style={{ color: "var(--hive-text)" }}>{error}</p>
      ) : collections === null ? (
        <p style={{ color: "var(--text-2)" }}>Loading...</p>
      ) : collections.length === 0 ? (
        <p style={{ color: "var(--text-2)" }}>No collections yet.</p>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
            gap: 24,
          }}
        >
          {collections.map((c) => (
            <Link
              key={c.id}
              href={`/collections/${c.id}`}
              style={{ textDecoration: "none", color: "inherit" }}
            >
              <div
                style={{
                  background: "var(--surface-2, #181818)",
                  borderRadius: 8,
                  padding: 16,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                  cursor: "pointer",
                }}
              >
                <div
                  style={{
                    width: "100%",
                    aspectRatio: "2/3",
                    background: "var(--surface-3, #242424)",
                    borderRadius: 4,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 32,
                  }}
                >
                  {c.name.charAt(0).toUpperCase()}
                </div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{c.name}</div>
                <div style={{ fontSize: 12, color: "var(--text-2)" }}>
                  {c.item_count} {c.item_count === 1 ? "movie" : "movies"}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </AuthShell>
  );
}
