// The five status tiles at the top of the /admin overview: Version, Remote
// access, Streaming now, Storage and Library. Each reads its own sources, so one
// that fails says "Couldn't load" with a Retry and the others carry on.

import Link from "next/link";
import {
  Check, CircleCheck, CircleHelp, Loader, Power, TriangleAlert, X,
} from "lucide-react";
import { Icon } from "@/components/Icon";
import {
  libraryTile, remoteTile, storageMeters, streamingTile, versionTile,
} from "@/lib/admin-dashboard";
import { buildScanRows } from "@/lib/scans-rows";
import { scanInputs } from "@/app/admin/ScansSection";
import { LoadFailed, Skeleton, StatusWord, Tile, gate } from "./OverviewParts";
import type { OverviewState, SourceKey } from "./useAdminOverview";

type Props = { state: OverviewState; now: number; retry: (key: SourceKey) => void };

const linkCls =
  "inline-flex min-h-tap items-center text-sm font-semibold text-hive-text hover:underline";

export function StatusTiles({ state, now, retry }: Props) {
  return (
    <div className="mb-5 grid grid-cols-1 gap-3 min-[640px]:grid-cols-2 min-[1100px]:grid-cols-5">
      <VersionTile state={state} now={now} retry={retry} />
      <RemoteTile state={state} retry={retry} />
      <StreamingTile state={state} retry={retry} />
      <StorageTile state={state} retry={retry} />
      <LibraryTile state={state} now={now} retry={retry} />
    </div>
  );
}

function VersionTile({ state, now, retry }: Props) {
  const g = gate(state.updates);
  const data = state.updates.data;
  return (
    <Tile label="Version">
      {g === "error" ? (
        <LoadFailed onRetry={() => retry("updates")} />
      ) : g === "loading" || !data ? (
        <Skeleton className="h-14 w-28" />
      ) : (
        <VersionBody data={data} now={now} />
      )}
    </Tile>
  );
}

function VersionBody({ data, now }: { data: NonNullable<OverviewState["updates"]["data"]>; now: number }) {
  const v = versionTile(data, now);
  return (
    <div>
      <p className="title-2 tabular-nums text-ink">{v.installed}</p>
      <p className="caption text-ink-3">
        {v.phone ? `Phone app ${v.phone}` : "Phone app not bundled"}
      </p>
      <div className="mt-2">
        {v.state === "available" ? (
          <Link
            href="/admin/updates"
            className="inline-flex min-h-tap items-center bg-hive px-4 text-sm font-semibold text-on-hive hover:bg-hive-hover"
          >
            {v.buttonLabel}
          </Link>
        ) : v.state === "updating" ? (
          <StatusWord tone="warning" icon={Loader}>Updating now</StatusWord>
        ) : v.state === "current" ? (
          <StatusWord tone="positive" icon={CircleCheck}>Up to date</StatusWord>
        ) : (
          <StatusWord tone="neutral" icon={CircleHelp}>Not checked</StatusWord>
        )}
      </div>
      <p className="caption mt-1 text-ink-3">{v.checked}</p>
    </div>
  );
}

function RemoteTile({ state, retry }: Omit<Props, "now">) {
  const g = gate(state.remote);
  const data = state.remote.data;
  return (
    <Tile label="Remote access">
      {g === "error" ? (
        <LoadFailed onRetry={() => retry("remote")} />
      ) : g === "loading" || !data ? (
        <Skeleton className="h-14 w-28" />
      ) : (
        <RemoteBody data={data} />
      )}
    </Tile>
  );
}

function RemoteBody({ data }: { data: NonNullable<OverviewState["remote"]["data"]> }) {
  const r = remoteTile(data);
  const icon = r.status === "Connected" ? CircleCheck
    : r.status === "Not reachable" ? TriangleAlert
    : r.status === "Off" ? Power
    : CircleHelp;
  return (
    <div>
      <p className="title-3 text-ink">{r.method}</p>
      <div className="mt-1">
        <StatusWord tone={r.tone} icon={icon}>{r.status}</StatusWord>
      </div>
      {r.host ? <p className="caption mt-1 break-all text-ink-3">{r.host}</p> : null}
      <Link href="/admin/remote-access" className={linkCls}>Manage</Link>
    </div>
  );
}

function StreamingTile({ state, retry }: Omit<Props, "now">) {
  const g = gate(state.transcodes, state.sessions);
  const t = state.transcodes.data;
  const s = state.sessions.data;
  return (
    <Tile label="Streaming now">
      {g === "error" ? (
        <LoadFailed onRetry={() => { retry("transcodes"); retry("sessions"); }} />
      ) : g === "loading" || !t || !s ? (
        <Skeleton className="h-14 w-28" />
      ) : (
        <StreamingBody tile={streamingTile(t, s)} />
      )}
    </Tile>
  );
}

function StreamingBody({ tile }: { tile: ReturnType<typeof streamingTile> }) {
  return (
    <div>
      <p className="title-1 tabular-nums text-ink">{tile.count}</p>
      <p className="caption text-ink-3 tabular-nums">{tile.summary}</p>
      <p className="caption mt-1 text-ink-3 tabular-nums">{tile.peopleText}</p>
    </div>
  );
}

function StorageTile({ state, retry }: Omit<Props, "now">) {
  const g = gate(state.health);
  const data = state.health.data;
  return (
    <Tile label="Storage">
      {g === "error" ? (
        <LoadFailed onRetry={() => retry("health")} />
      ) : g === "loading" || !data ? (
        <Skeleton className="h-14 w-28" />
      ) : (
        <ul className="space-y-3">
          {storageMeters(data).map((m) => (
            <li key={m.id}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="caption text-ink-2">{m.label}</span>
                <span className="caption tabular-nums text-ink-3">{m.percent}%</span>
              </div>
              <div
                role="meter"
                aria-label={m.label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={m.percent}
                className="mt-1 h-1.5 w-full bg-surface-3"
              >
                <div
                  className={`h-full ${m.warn ? "bg-warning" : "bg-ink-2"}`}
                  style={{ width: `${m.percent}%` }}
                />
              </div>
              <div className="mt-1 flex flex-wrap items-center justify-between gap-x-2">
                <span className="caption tabular-nums text-ink-3">{m.value}</span>
                {m.word ? (
                  <span className="caption inline-flex items-center gap-1 text-warning">
                    <Icon icon={TriangleAlert} size={14} />
                    {m.word}
                  </span>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Tile>
  );
}

function LibraryTile({ state, now, retry }: Props) {
  const g = gate(state.scans);
  const scans = state.scans.data;
  return (
    <Tile label="Library">
      {g === "error" ? (
        <LoadFailed onRetry={() => retry("scans")} />
      ) : g === "loading" || !scans ? (
        <Skeleton className="h-14 w-28" />
      ) : (
        <LibraryBody scans={scans} lastSyncAt={state.health.data?.last_sync_at ?? null} now={now} />
      )}
    </Tile>
  );
}

function LibraryBody({
  scans, lastSyncAt, now,
}: { scans: NonNullable<OverviewState["scans"]["data"]>; lastSyncAt: string | null; now: number }) {
  const lib = libraryTile(buildScanRows({ ...scanInputs(scans), now }), lastSyncAt, now);
  const icon = lib.state === "Scanning" ? Loader : lib.state === "Failed" ? X : Check;
  return (
    <div>
      <StatusWord tone={lib.tone} icon={icon}>{lib.state}</StatusWord>
      {lib.detail ? <p className="caption mt-1 text-ink-3">{lib.detail}</p> : null}
      <p className="caption mt-1 text-ink-3">{lib.lastSync}</p>
      <Link href="/admin/scans" className={linkCls}>Open Scans</Link>
    </div>
  );
}
