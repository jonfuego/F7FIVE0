// Admin > Library health: which list the page shows. Pure, so node:test covers
// it (library-health-view.test.ts).
//
// Each count tile opens its own list. The URL carries it as ?view=, so a Needs
// attention link (or a Scans row) lands on the list it talks about.

export type HealthView = "missing" | "eligible" | "errors" | "unreachable";

export const HEALTH_VIEWS: HealthView[] = ["missing", "eligible", "errors", "unreachable"];

/** The list shown when the URL names none: the one with Remove buttons, as
 *  before the tiles opened lists. */
export const DEFAULT_HEALTH_VIEW: HealthView = "eligible";

export const HEALTH_VIEW_LABEL: Record<HealthView, string> = {
  missing: "Missing files",
  eligible: "Eligible for cleanup",
  errors: "Probe errors",
  unreachable: "Unreachable folders",
};

/** "/admin/library-health?view=missing". */
export function healthViewHref(view: HealthView): string {
  return `/admin/library-health?view=${view}`;
}

/** The view the URL asks for (`?view=`), else the default. */
export function healthViewFromSearch(search: string): HealthView {
  const value = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search).get("view");
  return HEALTH_VIEWS.find((v) => v === value) ?? DEFAULT_HEALTH_VIEW;
}

export type HealthCountsLike = {
  missing_files_total: number;
  missing_files_eligible: number;
  probe_errors: number;
  unreachable_folders: number;
};

/** The number on each tile. */
export function healthTileCount(view: HealthView, c: HealthCountsLike): number {
  switch (view) {
    case "missing": return c.missing_files_total;
    case "eligible": return c.missing_files_eligible;
    case "errors": return c.probe_errors;
    case "unreachable": return c.unreachable_folders;
  }
}

/** What an empty list says. */
export const HEALTH_EMPTY_TEXT: Record<HealthView, string> = {
  missing: "No missing files.",
  eligible: "No missing files eligible for cleanup. A file becomes eligible after 7 days missing, while its library folder is reachable.",
  errors: "No probe errors.",
  unreachable: "Every library folder is reachable.",
};

/** The page size the file lists ask for. */
export const HEALTH_PAGE_SIZE = 100;
