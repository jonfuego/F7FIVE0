// Toggle button: mark a single media file watched or unwatched.
//
// Lives on detail pages next to PlayButton and on episode/track rows.
// The parent owns the "current status" (derived from its ProgressMap);
// this component just calls the right endpoint and invokes a callback
// so the parent can patch its local state without refetching.

"use client";

import { useState } from "react";
import { Circle, CircleCheck } from "lucide-react";
import { apiDelete, apiPost } from "@/lib/client-api";
import { Icon } from "@/components/Icon";

type Props = {
  mediaFileId: string;
  isWatched: boolean;
  onChanged?: (nowWatched: boolean) => void;
  size?: "sm" | "md";
};

export function MarkWatchedButton({
  mediaFileId, isWatched, onChanged, size = "sm",
}: Props) {
  const [busy, setBusy] = useState(false);

  async function onClick(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (busy) return;
    setBusy(true);
    try {
      if (isWatched) {
        await apiDelete(`/api/library/progress/${mediaFileId}`);
        onChanged?.(false);
      } else {
        await apiPost(`/api/library/progress/${mediaFileId}/mark-watched`, {});
        onChanged?.(true);
      }
    } catch {
      // Surface errors silently in v1. The UI will re-sync on next load.
    } finally {
      setBusy(false);
    }
  }

  const label = isWatched ? "Mark unwatched" : "Mark watched";
  const padding = size === "md" ? "px-3 py-2 text-sm" : "px-2.5 py-1 text-xs";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      aria-label={label}
      title={label}
      className={`inline-flex items-center gap-1.5 rounded-md border border-neutral-800 text-neutral-200 transition hover:border-neutral-600 hover:text-white disabled:opacity-60 ${padding}`}
    >
      {isWatched ? <Icon icon={CircleCheck} size={14} /> : <Icon icon={Circle} size={14} />}
      {label}
    </button>
  );
}
