// /mixes — record-store wall. 11 distinct playbills, one per existing
// auto-playlist kind. Non-parameterized kinds play on click;
// parameterized kinds open an inline picker. Existing playAlbum /
// addToQueue wiring preserved verbatim through MixCard.

"use client";

import { AuthShell } from "@/components/AuthShell";
import { MixCard } from "@/components/mixes/MixCard";
import { useViewPref } from "@/lib/use-view-pref";
import { useMixArt } from "@/lib/use-mix-art";

const MIXES = [
  {
    kind: "random",
    tag: "Wildcard",
    title: "Random",
    description: "A hundred random tracks, anything goes.",
    buildUrl: () => "/api/library/auto-playlist/random?limit=100",
  },
  {
    kind: "recently-added",
    tag: "Fresh",
    title: "Recently Added",
    description: "What's new in the library, freshest first.",
    buildUrl: () => "/api/library/auto-playlist/recently-added?limit=100",
  },
  {
    kind: "continue-listening",
    tag: "Pick Up",
    title: "Continue Listening",
    description: "Audio you started but didn't finish.",
    buildUrl: () => "/api/library/auto-playlist/continue-listening?limit=50",
  },
  {
    kind: "most-played",
    tag: "Top Spins",
    title: "Most Played",
    description: "What you've listened to the most.",
    buildUrl: () => "/api/library/auto-playlist/most-played?limit=100&window=all",
  },
  {
    kind: "never-played",
    tag: "Untouched",
    title: "Never Played",
    description: "Tracks you haven't touched yet.",
    buildUrl: () => "/api/library/auto-playlist/never-played?limit=100",
  },
  {
    kind: "recently-played",
    tag: "Last Spun",
    title: "Recently Played",
    description: "Most recent tracks from your play log.",
    buildUrl: () => "/api/library/auto-playlist/recently-played?limit=100",
  },
  {
    kind: "artist-random",
    tag: "Catalog",
    title: "Artist Random",
    description: "Shuffle one artist's catalog from start to finish.",
    buildUrl: (input?: Record<string, string>) => {
      const id = (input?.artist_id ?? "").trim();
      if (!id) return null;
      return `/api/library/auto-playlist/by-artist/${encodeURIComponent(id)}?limit=100`;
    },
    picker: {
      fields: [
        { kind: "text" as const, name: "artist_id", label: "Artist id", placeholder: "paste artist UUID" },
      ],
    },
  },
  {
    kind: "by-year",
    tag: "Annual",
    title: "By Year",
    description: "Albums released in a single year.",
    buildUrl: (input?: Record<string, string>) => {
      const year = (input?.year ?? "").trim();
      if (!/^\d{4}$/.test(year)) return null;
      return `/api/library/auto-playlist/by-year/${year}?limit=100`;
    },
    picker: {
      fields: [
        { kind: "number" as const, name: "year", label: "Year", placeholder: "1985", min: 1900, max: 2100 },
      ],
    },
  },
  {
    kind: "by-decade",
    tag: "Decade",
    title: "By Decade",
    description: "Everything from a given decade. 1980, 1990, 2000.",
    buildUrl: (input?: Record<string, string>) => {
      const decade = (input?.decade ?? "").trim();
      if (!/^\d{4}$/.test(decade)) return null;
      return `/api/library/auto-playlist/by-decade/${decade}?limit=100`;
    },
    picker: {
      fields: [
        { kind: "number" as const, name: "decade", label: "Decade (start year)", placeholder: "1990", min: 1900, max: 2100 },
      ],
    },
  },
  {
    kind: "by-genre",
    tag: "Genre",
    title: "By Genre",
    description: "Albums tagged with this genre. Free-text slug for v1.",
    buildUrl: (input?: Record<string, string>) => {
      const slug = (input?.genre_slug ?? "").trim();
      if (!slug) return null;
      return `/api/library/auto-playlist/by-genre/${encodeURIComponent(slug)}?limit=100`;
    },
    picker: {
      fields: [
        { kind: "text" as const, name: "genre_slug", label: "Genre", placeholder: "rock" },
      ],
    },
  },
  {
    kind: "artist-radio",
    tag: "Radio",
    title: "Artist Radio",
    description: "Seed an artist; mix in similar artists by genre.",
    buildUrl: (input?: Record<string, string>) => {
      const id = (input?.artist_id ?? "").trim();
      if (!id) return null;
      return `/api/library/auto-playlist/artist-radio/${encodeURIComponent(id)}?limit=100`;
    },
    picker: {
      fields: [
        { kind: "text" as const, name: "artist_id", label: "Artist id", placeholder: "paste artist UUID" },
      ],
    },
  },
];

export default function MixesPage() {
  // Saved view: the last values typed into each mix's picker (year, decade,
  // genre, artist), stored on the server per user.
  const [inputs, setInputs] = useViewPref("mixes.inputs");
  const { overrides, isAdmin, reload } = useMixArt();
  return (
    <AuthShell>
      <h1 className="page-title">Mixes</h1>

      <div className="playbills">
        {MIXES.map((m, i) => (
          <MixCard
            key={m.kind}
            kind={m.kind}
            tag={m.tag}
            title={m.title}
            description={m.description}
            buildUrl={m.buildUrl}
            picker={m.picker}
            index={i + 1}
            mixArt={overrides}
            isAdmin={isAdmin}
            onArtChanged={reload}
            savedValues={inputs[m.kind]}
            onSaveValues={(v) => setInputs({ ...inputs, [m.kind]: v })}
          />
        ))}
      </div>
    </AuthShell>
  );
}
