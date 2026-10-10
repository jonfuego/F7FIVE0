// Shared bits for the Fix Match and Art Search panels: a small source
// badge per result tile, and the missing-source callout block.
//
// Both panels now search several sources (TMDB, MusicBrainz, Cover Art
// Archive, TheAudioDB, iTunes, and the *arr apps), so each result shows
// which source it came from, and the backend's friendly notes render as
// callouts. The TMDB note gets a link to Admin where the key is set.

import Link from "next/link";

const SOURCE_LABELS: Record<string, string> = {
  tmdb: "TMDB",
  musicbrainz: "MusicBrainz",
  coverart: "Cover Art Archive",
  audiodb: "TheAudioDB",
  itunes: "iTunes",
  lidarr: "Lidarr",
  radarr: "Radarr",
  sonarr: "Sonarr",
  tvdb: "TheTVDB",
};

export function labelForSource(source: string): string {
  return SOURCE_LABELS[source.toLowerCase()] ?? source;
}

export function SourceTag({ source }: { source: string }) {
  return (
    <span className="inline-flex flex-none items-center rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-neutral-300">
      {labelForSource(source)}
    </span>
  );
}

// A callout line that would help the admin set up a missing source. The
// backend sends the TMDB note as plain text; we recognise it so we can
// append a link to Admin. Every other note (an *arr that is not connected,
// or a source that did not answer) renders as plain text.
export function SourceCallouts({ notes }: { notes: string[] }) {
  if (!notes || notes.length === 0) return null;
  return (
    <div className="mt-3 space-y-2">
      {notes.map((note) => {
        const isTmdb = note.includes("TMDB key in Admin");
        return (
          <p
            key={note}
            className="rounded border border-neutral-800 bg-neutral-950/60 px-3 py-2 text-xs text-neutral-400"
          >
            {note}
            {isTmdb ? (
              <>
                {" "}
                <Link
                  href="/admin"
                  className="text-hive underline hover:text-hive-hover"
                >
                  Open Admin
                </Link>
              </>
            ) : null}
          </p>
        );
      })}
    </div>
  );
}
