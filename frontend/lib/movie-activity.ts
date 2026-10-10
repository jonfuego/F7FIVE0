// The one-line activity shown under a movie title, only when there is activity:
// "Watched 3 Mar" when finished, "45 min left" when partway through, else null.
// Pure so node:test can cover it (movie-activity.test.ts).

export type ActivityInput = {
  completed_at: string | null;
  position_sec: number;
  duration_sec: number | null;
};

function shortDate(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  return new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** The activity line, or null when there is nothing to show (unwatched). */
export function movieActivityLine(row: ActivityInput | null | undefined): string | null {
  if (!row) return null;
  if (row.completed_at) {
    const when = shortDate(row.completed_at);
    return when ? `Watched ${when}` : "Watched";
  }
  const { position_sec, duration_sec } = row;
  if (duration_sec && duration_sec > 0 && position_sec > 0) {
    const leftSec = Math.max(0, duration_sec - position_sec);
    const leftMin = Math.round(leftSec / 60);
    if (leftMin >= 1) return `${leftMin} min left`;
    return "Almost done";
  }
  return null;
}
