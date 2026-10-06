// Loads the Edit modal's override view for a detail page.
//
// The detail pages used a raw fetch() for this and returned silently on any
// non-ok response. The access cookie lives 15 minutes, so after that the
// fetch got a 401 and the Edit button did nothing: no refresh, no modal, no
// message. This goes through the shared apiGet (one session refresh, then a
// retry) and turns any remaining failure into a message the page shows.
//
// The getter is passed in so node:test can drive it (overrides.test.ts).

export type OverrideKind = "movie" | "series" | "artist" | "music_video_release";

export type Getter = <T>(path: string) => Promise<T>;

export type OverrideLoad<T> = { ok: true; data: T } | { ok: false; error: string };

export function overridePath(kind: OverrideKind, id: string): string {
  return `/api/admin/override/${kind}/${encodeURIComponent(id)}`;
}

export function editErrorMessage(err: unknown): string {
  const status =
    err && typeof err === "object" && "status" in err ? Number((err as { status: unknown }).status) : null;
  if (status === 403) return "Only admins can edit this.";
  if (status === 404) return "This item isn't in the library any more.";
  const msg = err instanceof Error && err.message ? err.message : "network error";
  return `Couldn't open the editor (${msg}).`;
}

export async function loadOverride<T>(get: Getter, kind: OverrideKind, id: string): Promise<OverrideLoad<T>> {
  try {
    return { ok: true, data: await get<T>(overridePath(kind, id)) };
  } catch (err) {
    return { ok: false, error: editErrorMessage(err) };
  }
}
