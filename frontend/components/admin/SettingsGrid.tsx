// The Settings grid at the bottom of the /admin overview: one tile per area,
// each a link to its subpage with an icon, a name and a one-line status.
// Hover and keyboard focus lift the tile 3 px up and left and draw the HIVE
// offset behind it; the global :focus-visible ring is the focus cue.
//
// The hrefs below are the same ten as ADMIN_AREAS in lib/admin-dashboard.ts
// (admin-dashboard.test.ts checks they match). A new admin area gets a subpage,
// an ADMIN_AREAS entry, a row here and a hash entry.

import Link from "next/link";
import {
  Activity, AudioLines, Download, FileWarning, FolderOpen, Globe, Plug, RefreshCw, Tags, TriangleAlert, Users, Wand2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Icon } from "@/components/Icon";
import { settingsTiles, type AdminAreaId } from "@/lib/admin-dashboard";
import { buildScanRows, scansSummary } from "@/lib/scans-rows";
import { scanInputs } from "@/app/admin/ScansSection";
import { toneClass } from "./OverviewParts";
import type { OverviewState } from "./useAdminOverview";

const TILE: Record<AdminAreaId, { icon: LucideIcon; href: string }> = {
  users: { icon: Users, href: "/admin/users" },
  "library-folders": { icon: FolderOpen, href: "/admin/library-folders" },
  scans: { icon: RefreshCw, href: "/admin/scans" },
  metadata: { icon: Tags, href: "/admin/metadata" },
  arr: { icon: Plug, href: "/admin/arr" },
  "audio-analysis": { icon: AudioLines, href: "/admin/audio-analysis" },
  "library-health": { icon: FileWarning, href: "/admin/library-health" },
  organizer: { icon: Wand2, href: "/admin/organizer" },
  "remote-access": { icon: Globe, href: "/admin/remote-access" },
  updates: { icon: Download, href: "/admin/updates" },
  activity: { icon: Activity, href: "/admin/activity" },
};

export function SettingsGrid({ state, now }: { state: OverviewState; now: number }) {
  const scans = state.scans.data;
  const tiles = settingsTiles({
    users: state.users.data,
    folders: state.folders.data,
    scanSummary: scans ? scansSummary(buildScanRows({ ...scanInputs(scans), now })) : null,
    metadata: state.metadata.data,
    arr: state.arr.data,
    audio: state.audio.data,
    remote: state.remote.data,
    updates: state.updates.data,
  });
  return (
    <section aria-labelledby="settings-heading">
      <h2 id="settings-heading" className="title-2 mb-3 text-ink">Settings</h2>
      <ul className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 min-[1000px]:grid-cols-3">
        {tiles.map((t) => {
          const spec = TILE[t.id];
          return (
            <li key={t.id}>
              <Link
                href={spec.href}
                className="flex min-h-tap items-start gap-3 bg-surface-2 p-4 transition-transform hover:-translate-x-[3px] hover:-translate-y-[3px] hover:shadow-hive focus-visible:-translate-x-[3px] focus-visible:-translate-y-[3px] focus-visible:shadow-hive"
              >
                <span className="mt-0.5 text-ink-2">
                  <Icon icon={spec.icon} size={20} />
                </span>
                <span className="min-w-0">
                  <span className="title-3 block text-ink">{t.label}</span>
                  {t.status ? (
                    <span className={`caption mt-1 flex items-center gap-1 ${toneClass(t.tone)}`}>
                      {t.tone === "warning" ? <Icon icon={TriangleAlert} size={14} /> : null}
                      {t.status}
                    </span>
                  ) : null}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
