// Shared class strings and time formatting for the Admin section bodies.

export const inputCls =
  "w-full rounded-lg border border-line-strong bg-surface-1 px-3 py-2 text-sm text-ink outline-none focus:border-ink-2";

export const primaryButtonCls =
  "rounded-lg bg-ink px-4 py-2 text-sm font-medium text-bg transition hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-60";

export const smallButtonCls =
  "rounded-md border border-line px-2.5 py-1 text-xs text-ink transition hover:border-ink-3 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50";

export function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diff = Math.round((Date.now() - then) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatDate(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}


