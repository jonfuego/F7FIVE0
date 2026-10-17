// Small shared pieces of the /admin overview: the tile and panel frames, the
// "Couldn't load" state with Retry, the status word (icon plus word, never
// colour alone) and the loading skeleton.

import Link from "next/link";
import type { ReactNode } from "react";
import { CircleAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Icon } from "@/components/Icon";
import type { Tone } from "@/lib/admin-dashboard";
import type { Source } from "./useAdminOverview";

/** What a tile or panel that reads one or more sources should draw. A source
 *  whose last attempt failed makes the whole tile say so. */
export function gate(...sources: Source<unknown>[]): "error" | "loading" | "ok" {
  if (sources.some((s) => s.error)) return "error";
  if (sources.some((s) => !s.loaded || s.data === null)) return "loading";
  return "ok";
}

const TONE_CLASS: Record<Tone, string> = {
  neutral: "text-ink-2",
  positive: "text-positive",
  warning: "text-warning",
  danger: "text-hive-text",
};

export function toneClass(tone: Tone): string {
  return TONE_CLASS[tone];
}

export function StatusWord({
  tone, icon, children,
}: { tone: Tone; icon: LucideIcon; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 text-[15px] font-semibold leading-[22px] ${TONE_CLASS[tone]}`}>
      <Icon icon={icon} size={16} />
      {children}
    </span>
  );
}

export function Skeleton({ className = "h-5 w-24" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse bg-surface-3 ${className}`} />;
}

export function LoadFailed({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="status">
      <p className="inline-flex items-center gap-2 text-[15px] leading-[22px] text-ink-2">
        <Icon icon={CircleAlert} size={16} />
        Couldn&apos;t load
      </p>
      <div>
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 min-h-tap border border-line-strong px-3 text-xs font-semibold text-ink hover:border-ink-2"
        >
          Retry
        </button>
      </div>
    </div>
  );
}

export function Tile({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="bg-surface-2 p-4">
      <h3 className="overline text-ink-3">{label}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function Panel({
  id, title, action, children,
}: { id: string; title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-heading`} className="scroll-mt-20 border border-line bg-surface-1 p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-3">
        <h2 id={`${id}-heading`} className="title-2 text-ink">{title}</h2>
        {action}
      </div>
      <div className="mt-2">{children}</div>
    </section>
  );
}

export function PanelLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex min-h-tap items-center text-sm font-semibold text-hive-text hover:underline"
    >
      {children}
    </Link>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-2 text-[15px] leading-[22px] text-ink-3">{children}</p>;
}
