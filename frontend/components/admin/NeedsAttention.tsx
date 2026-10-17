// "Needs attention": shown only when something does. Each item is one line of
// text and a link to where it gets fixed. Warning tone, with an icon and a
// count so the state never rests on colour alone.

import Link from "next/link";
import { TriangleAlert } from "lucide-react";
import { Icon } from "@/components/Icon";
import type { AttentionItem } from "@/lib/admin-dashboard";

export function NeedsAttention({ items }: { items: AttentionItem[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="needs-attention-heading" className="mb-5 border border-line bg-surface-1 p-4">
      <h2 id="needs-attention-heading" className="title-2 flex items-center gap-2 text-ink">
        <span className="inline-flex items-center gap-2 text-warning">
          <Icon icon={TriangleAlert} size={20} />
          <span className="tabular-nums">{items.length}</span>
        </span>
        Needs attention
      </h2>
      <ul className="mt-2">
        {items.map((item) => (
          <li
            key={item.id}
            className="flex flex-wrap items-center justify-between gap-x-4 border-t border-line py-1 first:border-t-0"
          >
            <div className="min-w-0 py-2">
              <p className="text-[15px] leading-[22px] text-ink">{item.text}</p>
              {item.detail ? <p className="caption text-ink-3">{item.detail}</p> : null}
            </div>
            <Link
              href={item.href}
              className="inline-flex min-h-tap items-center text-sm font-semibold text-hive-text hover:underline"
            >
              {item.linkLabel}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
