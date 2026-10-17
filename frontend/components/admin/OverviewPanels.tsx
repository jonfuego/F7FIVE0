// The four panels under the tiles: Streaming now and Signed in on the left,
// Recent plays and Sign-in activity on the right (stacked under about 1000 px).
// Each says what is going on when it is empty, and says "Couldn't load" with a
// Retry when its own source fails.

import { Check, TriangleAlert, X } from "lucide-react";
import { Icon } from "@/components/Icon";
import {
  eventLines, formatPosition, latestSessions, relativeTime, streamLines,
} from "@/lib/admin-dashboard";
import { Empty, LoadFailed, Panel, PanelLink, Skeleton, gate } from "./OverviewParts";
import type { OverviewState, SourceKey } from "./useAdminOverview";

type Props = { state: OverviewState; now: number; retry: (key: SourceKey) => void };

const rowCls = "flex items-center gap-3 border-t border-line py-3 first:border-t-0";

export function OverviewPanels(props: Props) {
  return (
    <div className="mb-7 grid grid-cols-1 gap-5 min-[1000px]:grid-cols-2">
      <div className="space-y-5">
        <StreamingNow {...props} />
        <SignedIn {...props} />
      </div>
      <div className="space-y-5">
        <RecentPlays {...props} />
        <SignInActivity {...props} />
      </div>
    </div>
  );
}

function StreamingNow({ state, now, retry }: Props) {
  const g = gate(state.transcodes);
  const rows = state.transcodes.data;
  return (
    <Panel id="streaming-now" title="Streaming now">
      {g === "error" ? (
        <LoadFailed onRetry={() => retry("transcodes")} />
      ) : g === "loading" || !rows ? (
        <Skeleton className="h-16 w-full" />
      ) : rows.length === 0 ? (
        <Empty>Nothing playing right now.</Empty>
      ) : (
        <ul>
          {streamLines(rows, now).map((l) => (
            <li key={l.id} className={rowCls}>
              <span
                aria-hidden="true"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-3 text-sm font-bold text-ink"
              >
                {l.initial}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-semibold leading-[22px] text-ink">{l.title}</p>
                <p className="caption text-ink-3 tabular-nums">
                  {l.user} · {l.started} · {l.bytes}
                </p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <span className="overline border border-line-strong px-2 py-0.5 text-ink-2 tabular-nums">
                  {l.tag}
                </span>
                {l.slow ? (
                  <span className="caption inline-flex items-center gap-1 text-warning">
                    <Icon icon={TriangleAlert} size={14} />
                    Slow
                  </span>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function SignedIn({ state, now, retry }: Props) {
  const g = gate(state.sessions);
  const rows = state.sessions.data;
  return (
    <Panel
      id="signed-in"
      title="Signed in"
      action={
        rows && rows.length > 0 ? (
          <PanelLink href="/admin/activity">{`All ${rows.length} sessions`}</PanelLink>
        ) : null
      }
    >
      {g === "error" ? (
        <LoadFailed onRetry={() => retry("sessions")} />
      ) : g === "loading" || !rows ? (
        <Skeleton className="h-16 w-full" />
      ) : rows.length === 0 ? (
        <Empty>No one is signed in.</Empty>
      ) : (
        <ul>
          {latestSessions(rows, 3).map((s) => (
            <li key={s.id} className={rowCls}>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-semibold leading-[22px] text-ink">{s.display_name}</p>
                <p className="caption truncate text-ink-3">{s.device_label ?? "Unknown device"}</p>
              </div>
              <div className="shrink-0 text-right">
                <span className="overline border border-line-strong px-2 py-0.5 text-ink-2">{s.client_type}</span>
                <p className="caption mt-1 text-ink-3 tabular-nums">
                  {s.last_seen_at ? relativeTime(s.last_seen_at, now) : "not seen yet"}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function RecentPlays({ state, now, retry }: Props) {
  const g = gate(state.history);
  const rows = state.history.data;
  return (
    <Panel id="recent-plays" title="Recent plays" action={<PanelLink href="/admin/activity">Full history</PanelLink>}>
      {g === "error" ? (
        <LoadFailed onRetry={() => retry("history")} />
      ) : g === "loading" || !rows ? (
        <Skeleton className="h-16 w-full" />
      ) : rows.length === 0 ? (
        <Empty>Nothing played yet.</Empty>
      ) : (
        <ul>
          {rows.slice(0, 4).map((r) => (
            <li key={r.id} className={rowCls}>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-semibold leading-[22px] text-ink">{r.title}</p>
                <p className="caption text-ink-3 tabular-nums">
                  {r.user_display_name} · {relativeTime(r.started_at, now)}
                </p>
              </div>
              <span className="caption shrink-0 text-ink-3 tabular-nums">{formatPosition(r.last_position_sec)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function SignInActivity({ state, now, retry }: Props) {
  const g = gate(state.authEvents);
  const rows = state.authEvents.data;
  return (
    <Panel id="sign-in-activity" title="Sign-in activity" action={<PanelLink href="/admin/activity">All events</PanelLink>}>
      {g === "error" ? (
        <LoadFailed onRetry={() => retry("authEvents")} />
      ) : g === "loading" || !rows ? (
        <Skeleton className="h-16 w-full" />
      ) : rows.length === 0 ? (
        <Empty>No sign-ins recorded yet.</Empty>
      ) : (
        <ul>
          {eventLines(rows.slice(0, 3), now).map((e) => (
            <li key={e.id} className={rowCls}>
              <span className={e.failed ? "text-hive-text" : "text-ink-3"}>
                <Icon icon={e.failed ? X : Check} size={16} />
              </span>
              <div className="min-w-0 flex-1">
                <p
                  className={`truncate text-[15px] font-semibold leading-[22px] ${e.failed ? "text-hive-text" : "text-ink"}`}
                >
                  {e.text}
                </p>
                {e.ip ? <p className="caption text-ink-3 tabular-nums">{e.ip}</p> : null}
              </div>
              <span className="caption shrink-0 text-ink-3 tabular-nums">{e.when}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
