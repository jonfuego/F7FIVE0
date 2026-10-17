// The section list on every /admin/<area> page: "Overview" (back arrow) first,
// then the nine areas. The current one carries aria-current="page" and the HIVE
// mark. Wide screens put it on the left; under about 720 px it stacks above the
// content and wraps. The overview itself has no list.

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Icon } from "@/components/Icon";
import { ADMIN_AREAS, ADMIN_HOME, currentAreaId } from "@/lib/admin-dashboard";

const itemCls =
  "relative flex min-h-tap items-center gap-2 px-3 text-sm font-semibold text-ink-2 hover:bg-surface-2 hover:text-ink";

export function AdminSectionList() {
  const current = currentAreaId(usePathname());
  return (
    <nav aria-label="Admin sections" data-testid="admin-section-list">
      <ul className="flex flex-wrap gap-1 min-[720px]:flex-col">
        <li>
          <Link href={ADMIN_HOME} className={itemCls}>
            <Icon icon={ArrowLeft} size={16} />
            Overview
          </Link>
        </li>
        {ADMIN_AREAS.map((area) => {
          const active = area.id === current;
          return (
            <li key={area.id}>
              <Link
                href={area.href}
                aria-current={active ? "page" : undefined}
                className={`${itemCls} ${active ? "text-ink" : ""}`}
                style={active ? { background: "var(--hive-tint)" } : undefined}
              >
                {active ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-y-0 left-0 w-[3px]"
                    style={{ background: "var(--hive-mark)" }}
                  />
                ) : null}
                {area.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
