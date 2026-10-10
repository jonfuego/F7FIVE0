// Admin panel. Users, library sync, active streams, recent history.
//
// Admin-only. The client renders a friendly 403 for members; the backend
// enforces the same rule on every call. All traffic goes through the
// Next BFF at /api/admin/*, which attaches the Bearer from the httpOnly
// cookie and aliases user-management paths back to /api/auth/users/*.

"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { AuthShell } from "@/components/AuthShell";
import { CollapsibleSection } from "@/components/CollapsibleSection";
import { RemoteAccessSection } from "./RemoteAccessSection";
import { UpdatesSection } from "./UpdatesSection";
import { LibraryFoldersSection } from "./LibraryFoldersSection";
import { MusicVideosScanBlock } from "./MusicVideosScanBlock";
import { MetadataSection } from "./MetadataSection";
import { apiGet, apiPatch, apiPost, apiDelete, ApiError } from "@/lib/client-api";
import { loadMe } from "@/lib/load-me";
import { useFeatures } from "@/lib/features";
import { showArrSync, type FolderScanStatus } from "@/lib/library-scan";
import { remoteAccessSummary, scanSummary, updatesSummary, type SectionSummary } from "@/lib/admin-sections";
import { useViewPref } from "@/lib/use-view-pref";
import type { AdminSectionId } from "@/lib/view-prefs";
import type {
  ActiveTranscode, AdminSession, AdminUser, AuthEvent, Me, RemoteAccessStatus,
  ServerHealth, UpdatesStatus, WatchHistoryRow,
} from "@/lib/types";

// Lightweight status probes for the section summaries shown when a card is
// folded. These run whether or not the section is expanded, so a collapsed
// section can still surface a running scan, a failed scan, an update available
// or a running update. They are cheap on a home-scale instance; the section
// bodies keep their own fetches for the full view.
type SectionStatuses = {
  updates: SectionSummary;
  remote: SectionSummary;
  scan: SectionSummary;
};

function useSectionSummaries(enabled: boolean): SectionStatuses {
  const [updates, setUpdates] = useState<UpdatesStatus | null>(null);
  const [remote, setRemote] = useState<RemoteAccessStatus | null>(null);
  const [scan, setScan] = useState<FolderScanStatus | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const load = async () => {
      const [u, r, s] = await Promise.allSettled([
        apiGet<UpdatesStatus>("/api/admin/updates"),
        apiGet<RemoteAccessStatus>("/api/admin/remote-access"),
        apiGet<FolderScanStatus>("/api/admin/library/scan"),
      ]);
      if (cancelled) return;
      if (u.status === "fulfilled") setUpdates(u.value);
      if (r.status === "fulfilled") setRemote(r.value);
      if (s.status === "fulfilled") setScan(s.value);
    };
    void load();
    // Refresh so a scan or update that starts while the admin watches shows up
    // in a folded summary.
    const id = window.setInterval(() => void load(), 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [enabled]);

  return {
    updates: updatesSummary(updates),
    remote: remoteAccessSummary(remote),
    scan: scanSummary(scan),
  };
}

export default function AdminPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // loadMe goes through apiGet (single-flight refresh + retry), so the page
  // renders on first navigation even right after the 15-min access token
  // expired. See lib/load-me.ts for the cause this fixes.
  const load = useCallback(async (signal?: AbortSignal) => {
    setLoadError(null);
    try {
      const profile = await loadMe(apiGet, signal);
      if (!profile) return;
      setMe(profile);
      if (profile.role !== "admin") setForbidden(true);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setLoadError(err instanceof Error ? err.message : "Could not load the admin page.");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => {
      controller.abort();
    };
  }, [load]);

  const isAdmin = me?.role === "admin";
  // Collapsed sections, remembered per user on the server (admin.collapsed).
  const [collapsedList, setCollapsedList] = useViewPref("admin.collapsed");
  const collapsed = useMemo(() => new Set<string>(collapsedList), [collapsedList]);
  const toggle = useCallback(
    (id: string) => {
      setCollapsedList(
        (collapsed.has(id)
          ? collapsedList.filter((x) => x !== id)
          : [...collapsedList, id]) as AdminSectionId[],
      );
    },
    [collapsed, collapsedList, setCollapsedList],
  );

  const summaries = useSectionSummaries(isAdmin);

  // A reminder banner links to /admin#metadata: force Metadata open on that hash
  // so a collapsed card can't hide where the admin was sent.
  const [metadataHash, setMetadataHash] = useState(false);
  useEffect(() => {
    if (typeof window !== "undefined" && window.location.hash === "#metadata") setMetadataHash(true);
  }, []);

  if (forbidden) {
    return (
      <AuthShell>
        <div className="mx-auto max-w-lg text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Admin</h1>
          <p className="mt-4 text-sm text-neutral-400">
            This area is limited to administrators.
          </p>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <div className="mx-auto max-w-5xl">
        <header className="mb-4">
          <h1 className="text-2xl font-semibold tracking-tight">Admin</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Manage users, updates, remote access, and library folders, trigger library sync, inspect active streams and recent history.
          </p>
        </header>

        {me ? (
          <div className="space-y-3">
            <CollapsibleSection id="users" title="Users" collapsed={collapsed.has("users")} onToggle={toggle}>
              <UsersSection me={me} />
            </CollapsibleSection>
            <CollapsibleSection
              id="updates"
              title="Updates"
              collapsed={collapsed.has("updates")}
              onToggle={toggle}
              summary={summaries.updates.text}
              attention={summaries.updates.attention}
              forceOpen={summaries.updates.attention}
            >
              <UpdatesSection />
            </CollapsibleSection>
            <CollapsibleSection
              id="remote-access"
              title="Remote access"
              collapsed={collapsed.has("remote-access")}
              onToggle={toggle}
              summary={summaries.remote.text}
              attention={summaries.remote.attention}
            >
              <RemoteAccessSection />
            </CollapsibleSection>
            <CollapsibleSection
              id="library-folders"
              title="Library folders"
              collapsed={collapsed.has("library-folders")}
              onToggle={toggle}
              summary={summaries.scan.text}
              attention={summaries.scan.attention}
              forceOpen={summaries.scan.attention}
            >
              <LibraryFoldersSection />
            </CollapsibleSection>
            <CollapsibleSection
              id="metadata"
              title="Metadata"
              collapsed={collapsed.has("metadata")}
              onToggle={toggle}
              forceOpen={metadataHash}
            >
              <MetadataSection />
            </CollapsibleSection>
            <CollapsibleSection id="library" title="Library" collapsed={collapsed.has("library")} onToggle={toggle}>
              <LibrarySection />
            </CollapsibleSection>
            <CollapsibleSection id="audio-analysis" title="Audio analysis" collapsed={collapsed.has("audio-analysis")} onToggle={toggle}>
              <AudioAnalysisSection />
            </CollapsibleSection>
            <CollapsibleSection id="health" title="Server health" collapsed={collapsed.has("health")} onToggle={toggle}>
              <HealthSection />
            </CollapsibleSection>
            <CollapsibleSection id="active-streams" title="Active streams" collapsed={collapsed.has("active-streams")} onToggle={toggle}>
              <ActiveStreamsSection />
            </CollapsibleSection>
            <CollapsibleSection id="sessions" title="Active sessions" collapsed={collapsed.has("sessions")} onToggle={toggle}>
              <SessionsSection />
            </CollapsibleSection>
            <CollapsibleSection id="auth-events" title="Auth events" collapsed={collapsed.has("auth-events")} onToggle={toggle}>
              <AuthEventsSection />
            </CollapsibleSection>
            <CollapsibleSection id="history" title="Recent history" collapsed={collapsed.has("history")} onToggle={toggle}>
              <RecentHistorySection />
            </CollapsibleSection>
          </div>
        ) : loadError ? (
          <div className="rounded-xl border border-red-900/60 bg-red-950/40 px-4 py-6 text-sm text-red-200">
            <p>{loadError}</p>
            <button
              type="button"
              onClick={() => load()}
              className="mt-3 rounded-md border border-red-800/60 px-3 py-1.5 text-xs text-red-100 hover:border-red-600"
            >
              Try again
            </button>
          </div>
        ) : (
          <div className="h-32 animate-pulse rounded-xl border border-neutral-800 bg-neutral-900/40" />
        )}
      </div>
    </AuthShell>
  );
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
function UsersSection({ me }: { me: Me }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<AdminUser[]>("/api/admin/users");
      setUsers(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function patchUser(id: string, body: Record<string, unknown>) {
    setNotice(null);
    try {
      const updated = await apiPatch<AdminUser>(`/api/admin/users/${id}`, body);
      setUsers((prev) => (prev ? prev.map((u) => (u.id === id ? updated : u)) : prev));
      setNotice("Saved.");
    } catch (err) {
      if (err instanceof ApiError && err.detail === "cannot_disable_last_admin") {
        setNotice("Cannot disable the last active admin.");
        return;
      }
      if (err instanceof ApiError && err.detail === "cannot_demote_last_admin") {
        setNotice("Cannot demote the last active admin.");
        return;
      }
      setNotice(err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  async function resetPassword(id: string) {
    const next = window.prompt("New password (min 8 chars):");
    if (!next) return;
    if (next.length < 8) {
      setNotice("Password must be at least 8 characters.");
      return;
    }
    setNotice(null);
    try {
      await apiPost(`/api/admin/users/${id}/password`, { new_password: next });
      setNotice("Password reset. The user will need to sign in again.");
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Password reset failed.");
    }
  }

  return (
    <div>
      {notice ? <div className="mb-2 text-xs text-neutral-400">{notice}</div> : null}

      <NewUserForm onCreated={(u) => {
        setUsers((prev) => (prev ? [...prev, u] : [u]));
        setNotice(`Created ${u.username}.`);
      }} />

      <div className="mt-6 overflow-x-auto">
        {error ? (
          <div className="rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        ) : users === null ? (
          <div className="h-24 animate-pulse rounded-md bg-neutral-900" />
        ) : users.length === 0 ? (
          <div className="rounded-md border border-dashed border-neutral-800 bg-neutral-900/30 px-4 py-6 text-sm text-neutral-500">
            No users yet.
          </div>
        ) : (
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-neutral-500">
              <tr className="border-b border-neutral-800">
                <th className="px-2 py-2 font-medium">Username</th>
                <th className="px-2 py-2 font-medium">Name</th>
                <th className="px-2 py-2 font-medium">Role</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-neutral-900 last:border-b-0">
                  <td className="px-2 py-2 font-sans text-xs text-neutral-300">{u.username}</td>
                  <td className="px-2 py-2">{u.display_name}</td>
                  <td className="px-2 py-2">
                    <select
                      className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs"
                      value={u.role}
                      disabled={u.id === me.id}
                      onChange={(e) => patchUser(u.id, { role: e.target.value })}
                    >
                      <option value="member">member</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td className="px-2 py-2">
                    {u.is_active ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-900/40 px-2 py-0.5 text-[11px] text-emerald-300">
                        Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-neutral-800 px-2 py-0.5 text-[11px] text-neutral-400">
                        Disabled
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => patchUser(u.id, { is_active: !u.is_active })}
                        disabled={u.id === me.id}
                        className={smallButtonCls}
                      >
                        {u.is_active ? "Disable" : "Enable"}
                      </button>
                      <button
                        type="button"
                        onClick={() => resetPassword(u.id)}
                        className={smallButtonCls}
                      >
                        Reset password
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function NewUserForm({ onCreated }: { onCreated: (u: AdminUser) => void }) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"member" | "admin">("member");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Username must match the backend's [a-z0-9._-]{3,64} charset. We
  // restrict the input as the user types so a stray capital or space
  // can never silently block native form validation later.
  const sanitizeUsername = (raw: string): string =>
    raw.toLowerCase().replace(/[^a-z0-9._-]/g, "");

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;
    setError(null);

    const cleanUsername = sanitizeUsername(username.trim());
    const cleanDisplayName = displayName.trim();

    if (cleanUsername.length < 3 || cleanUsername.length > 64) {
      setError("Username must be 3–64 characters of a–z, 0–9, dot, underscore, or hyphen.");
      return;
    }
    if (cleanDisplayName.length === 0) {
      setError("Display name is required.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setSubmitting(true);
    try {
      const created = await apiPost<AdminUser>("/api/admin/users", {
        username: cleanUsername,
        display_name: cleanDisplayName,
        password,
        role,
      });
      onCreated(created);
      setUsername("");
      setDisplayName("");
      setPassword("");
      setRole("member");
    } catch (err) {
      if (err instanceof ApiError && err.detail === "username_already_exists") {
        setError("That username is already in use.");
      } else if (err instanceof ApiError) {
        setError(`Create user failed (${err.status}${err.detail ? `: ${err.detail}` : ""}).`);
      } else {
        setError(err instanceof Error ? err.message : "Could not create user.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      className="mt-4 grid grid-cols-1 gap-3 rounded-lg border border-neutral-800 bg-neutral-950/40 p-4 sm:grid-cols-5"
    >
      <input
        type="text"
        placeholder="username"
        autoCapitalize="none"
        autoComplete="off"
        spellCheck={false}
        value={username}
        onChange={(e) => setUsername(sanitizeUsername(e.target.value))}
        className={inputCls}
      />
      <input
        type="text"
        placeholder="display name"
        maxLength={120}
        value={displayName}
        onChange={(e) => setDisplayName(e.target.value)}
        className={inputCls}
      />
      <input
        type="password"
        placeholder="password (min 8)"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        className={inputCls}
      />
      <select
        value={role}
        onChange={(e) => setRole(e.target.value as "member" | "admin")}
        className={inputCls}
      >
        <option value="member">member</option>
        <option value="admin">admin</option>
      </select>
      <button type="submit" disabled={submitting} className={primaryButtonCls}>
        {submitting ? "Creating..." : "Create user"}
      </button>
      {error ? (
        <p role="alert" className="text-sm text-rose-400 sm:col-span-5">
          {error}
        </p>
      ) : null}
    </form>
  );
}

// ---------------------------------------------------------------------------
// Library sync
// ---------------------------------------------------------------------------
function LibrarySection() {
  // "Run *arr sync now" only shows when Radarr, Sonarr or Lidarr is set up;
  // folder libraries are scanned from Admin > Library folders. Music videos
  // are scanned off the filesystem on demand, in their own status block below.
  const features = useFeatures();
  const showArr = showArrSync(features?.arr);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  async function runSync() {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      await apiPost("/api/admin/library/sync", {});
      setStatus("Sync queued. Full *arr fetch runs in the background.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Failed to enqueue sync.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <p className="text-xs text-neutral-500">
        {showArr ? "The *arr sync scheduler already runs every 5 minutes. " : ""}
        Music videos are scanned off the filesystem on demand; trigger one
        after dropping new files into the Music Videos share. Scan the movie,
        TV and music folders from Library folders above.
      </p>
      {showArr ? (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={runSync}
            disabled={busy}
            className={primaryButtonCls}
          >
            {busy ? "Queuing..." : "Run *arr sync now"}
          </button>
          {status ? <span className="text-xs text-neutral-400">{status}</span> : null}
        </div>
      ) : null}

      <MusicVideosScanBlock />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audio analysis (smart-audio backfill)
// ---------------------------------------------------------------------------
type AudioAnalysisProgress = { analyzed: number; total: number; pending: number };

function AudioAnalysisSection() {
  const [progress, setProgress] = useState<AudioAnalysisProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<AudioAnalysisProgress>("/api/admin/audio/progress");
      setProgress(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load progress.");
    }
  }, []);

  useEffect(() => {
    load();
    // Poll while a backfill is running so analyzed / total climbs live.
    const id = window.setInterval(load, 5_000);
    return () => window.clearInterval(id);
  }, [load]);

  async function analyzeNow() {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      await apiPost("/api/admin/audio/analyze", {});
      setStatus(
        progress && progress.total === 0
          ? "No music to analyze."
          : "Analysis queued. It runs one track at a time in the background.",
      );
      load();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Failed to start analysis.");
    } finally {
      setBusy(false);
    }
  }

  const pct =
    progress && progress.total > 0
      ? Math.min(100, Math.round((progress.analyzed / progress.total) * 100))
      : 0;

  return (
    <div>
      <p className="text-xs text-neutral-500">
        Loudness leveling, the waveform scrubber, and similar-track radio need
        each track analyzed once. New music is analyzed automatically after a
        folder scan, one track at a time. Use this to kick it off right away.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={analyzeNow}
          disabled={busy}
          className={primaryButtonCls}
        >
          {busy ? "Queuing..." : "Analyze music now"}
        </button>
        {progress ? (
          <span className="text-xs text-neutral-400">
            {progress.total > 0 ? (
              <>
                {progress.analyzed} / {progress.total} tracks analyzed
                {progress.pending > 0 ? ` (${progress.pending} pending)` : ""}
              </>
            ) : (
              "No music to analyze."
            )}
          </span>
        ) : error ? (
          <span className="text-xs text-rose-400">{error}</span>
        ) : null}
      </div>
      {progress && progress.total > 0 ? (
        <div className="mt-3 h-1.5 w-full max-w-md overflow-hidden rounded-full bg-neutral-800">
          <div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} />
        </div>
      ) : null}
      {status ? <p className="mt-3 text-xs text-neutral-400">{status}</p> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Active streams
// ---------------------------------------------------------------------------
// Seconds an encode must stay below 1.0x realtime before we warn the operator.
// A brief dip is normal (keyframe-heavy scene, a second job starting); a
// sustained window means the box genuinely can't encode fast enough.
const CANT_KEEP_UP_SEC = 30;

function TranscodeSpeedCell({ row }: { row: ActiveTranscode }) {
  // Direct play has no ffmpeg and no speed; nothing to show.
  if (row.direct_play || row.speed === null || row.speed === undefined) {
    return <span className="text-neutral-600">-</span>;
  }
  const behind =
    row.speed < 1.0 && row.below_realtime_sec >= CANT_KEEP_UP_SEC;
  return (
    <span className={behind ? "text-red-300" : "text-neutral-300"}>
      <span className="font-sans">{row.speed.toFixed(2)}x</span>
      {behind ? (
        <span className="ml-2 rounded bg-red-950/60 px-1.5 py-0.5 text-xs font-medium text-red-200">
          Server can&apos;t keep up
        </span>
      ) : null}
    </span>
  );
}

function ActiveStreamsSection() {
  const [rows, setRows] = useState<ActiveTranscode[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<ActiveTranscode[]>("/api/admin/transcodes/active");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load streams.");
    }
  }, []);

  useEffect(() => {
    load();
    // Poll every 10s so the view stays fresh without flooding the API.
    const id = window.setInterval(load, 10_000);
    return () => window.clearInterval(id);
  }, [load]);

  return (
    <div>
      <div className="flex items-baseline justify-end gap-3">
        <button
          type="button"
          onClick={load}
          className="text-xs text-neutral-500 hover:text-neutral-200"
        >
          Refresh
        </button>
      </div>
      <div className="mt-4 overflow-x-auto">
        {error ? (
          <div className="rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        ) : rows === null ? (
          <div className="h-16 animate-pulse rounded-md bg-neutral-900" />
        ) : rows.length === 0 ? (
          <div className="rounded-md border border-dashed border-neutral-800 bg-neutral-900/30 px-4 py-6 text-sm text-neutral-500">
            Nothing streaming right now.
          </div>
        ) : (
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-neutral-500">
              <tr className="border-b border-neutral-800">
                <th className="px-2 py-2 font-medium">User</th>
                <th className="px-2 py-2 font-medium">Title</th>
                <th className="px-2 py-2 font-medium">Mode</th>
                <th className="px-2 py-2 font-medium">Speed</th>
                <th className="px-2 py-2 font-medium">Started</th>
                <th className="px-2 py-2 font-medium text-right">Bytes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-neutral-900 last:border-b-0">
                  <td className="px-2 py-2">{r.user_display_name}</td>
                  <td className="px-2 py-2 text-neutral-200">{r.title}</td>
                  <td className="px-2 py-2 text-neutral-300">
                    {r.direct_play ? "Direct" : `HLS ${r.variant}`}
                  </td>
                  <td className="px-2 py-2">
                    <TranscodeSpeedCell row={r} />
                  </td>
                  <td className="px-2 py-2 text-neutral-300">
                    {formatRelative(r.started_at)}
                  </td>
                  <td className="px-2 py-2 text-right font-sans text-xs text-neutral-400">
                    {formatBytes(r.bytes_served)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recent watch history
// ---------------------------------------------------------------------------
function RecentHistorySection() {
  const [rows, setRows] = useState<WatchHistoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<WatchHistoryRow[]>("/api/admin/history/recent?limit=25");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load history.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <div className="flex items-baseline justify-end gap-3">
        <button
          type="button"
          onClick={load}
          className="text-xs text-neutral-500 hover:text-neutral-200"
        >
          Refresh
        </button>
      </div>
      <div className="mt-4 overflow-x-auto">
        {error ? (
          <div className="rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        ) : rows === null ? (
          <div className="h-16 animate-pulse rounded-md bg-neutral-900" />
        ) : rows.length === 0 ? (
          <div className="rounded-md border border-dashed border-neutral-800 bg-neutral-900/30 px-4 py-6 text-sm text-neutral-500">
            Nothing played yet.
          </div>
        ) : (
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-neutral-500">
              <tr className="border-b border-neutral-800">
                <th className="px-2 py-2 font-medium">When</th>
                <th className="px-2 py-2 font-medium">User</th>
                <th className="px-2 py-2 font-medium">Title</th>
                <th className="px-2 py-2 font-medium text-right">Position</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-neutral-900 last:border-b-0">
                  <td className="px-2 py-2 text-neutral-300">
                    {formatRelative(r.started_at)}
                  </td>
                  <td className="px-2 py-2">{r.user_display_name}</td>
                  <td className="px-2 py-2 text-neutral-200">{r.title}</td>
                  <td className="px-2 py-2 text-right font-sans text-xs text-neutral-400">
                    {formatPosition(r.last_position_sec)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Server health
// ---------------------------------------------------------------------------
function HealthSection() {
  const [health, setHealth] = useState<ServerHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<ServerHealth>("/api/admin/health");
      setHealth(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load health.");
    }
  }, []);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 10_000);
    return () => window.clearInterval(id);
  }, [load]);

  const cachePct =
    health && health.transcode_cache_max_bytes > 0
      ? Math.min(100, Math.round((health.transcode_cache_bytes / health.transcode_cache_max_bytes) * 100))
      : 0;

  return (
    <div>
      <div className="flex items-baseline justify-end gap-3">
        <button
          type="button"
          onClick={load}
          className="text-xs text-neutral-500 hover:text-neutral-200"
        >
          Refresh
        </button>
      </div>
      {error ? (
        <div className="mt-4 rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      ) : health === null ? (
        <div className="mt-4 h-24 animate-pulse rounded-md bg-neutral-900" />
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <HealthStat label="Transcode cache">
            <div className="text-neutral-200">
              {formatBytes(health.transcode_cache_bytes)}
              <span className="text-neutral-500"> / {formatBytes(health.transcode_cache_max_bytes)}</span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
              <div
                className={`h-full ${cachePct >= 90 ? "bg-rose-500" : "bg-emerald-500"}`}
                style={{ width: `${cachePct}%` }}
              />
            </div>
            <div className="mt-1 text-[11px] text-neutral-500">{cachePct}% of cap</div>
          </HealthStat>
          <HealthStat label="Cache drive free">
            <div className="text-neutral-200">{formatBytes(health.cache_disk_free_bytes)}</div>
            <div className="mt-1 text-[11px] text-neutral-500">
              of {formatBytes(health.cache_disk_total_bytes)}
            </div>
          </HealthStat>
          <HealthStat label="Art drive free">
            <div className="text-neutral-200">{formatBytes(health.art_disk_free_bytes)}</div>
            <div className="mt-1 text-[11px] text-neutral-500">
              of {formatBytes(health.art_disk_total_bytes)}
            </div>
          </HealthStat>
          <HealthStat label="Open transcodes">
            <div className="text-neutral-200">{health.open_transcode_sessions}</div>
            <div className="mt-1 text-[11px] text-neutral-500">
              last sync {health.last_sync_at ? formatRelative(health.last_sync_at) : "n/a"}
            </div>
          </HealthStat>
        </div>
      )}
    </div>
  );
}

function HealthStat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-950/40 p-4">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="mt-2 text-sm">{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Active sessions
// ---------------------------------------------------------------------------
function SessionsSection() {
  const [rows, setRows] = useState<AdminSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<AdminSession[]>("/api/admin/sessions");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions.");
    }
  }, []);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 10_000);
    return () => window.clearInterval(id);
  }, [load]);

  async function revoke(id: string, label: string) {
    if (!window.confirm(`Revoke this session for ${label}? The device will have to sign in again.`)) {
      return;
    }
    try {
      await apiDelete(`/api/admin/sessions/${id}`);
      setRows((prev) => (prev ? prev.filter((s) => s.id !== id) : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revoke failed.");
    }
  }

  return (
    <div>
      <div className="flex items-baseline justify-end gap-3">
        <button
          type="button"
          onClick={load}
          className="text-xs text-neutral-500 hover:text-neutral-200"
        >
          Refresh
        </button>
      </div>
      <div className="mt-4 overflow-x-auto">
        {error ? (
          <div className="rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        ) : rows === null ? (
          <div className="h-16 animate-pulse rounded-md bg-neutral-900" />
        ) : rows.length === 0 ? (
          <div className="rounded-md border border-dashed border-neutral-800 bg-neutral-900/30 px-4 py-6 text-sm text-neutral-500">
            No active sessions.
          </div>
        ) : (
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-neutral-500">
              <tr className="border-b border-neutral-800">
                <th className="px-2 py-2 font-medium">User</th>
                <th className="px-2 py-2 font-medium">Client</th>
                <th className="px-2 py-2 font-medium">Device</th>
                <th className="px-2 py-2 font-medium">Last seen</th>
                <th className="px-2 py-2 font-medium">Expires</th>
                <th className="px-2 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-b border-neutral-900 last:border-b-0">
                  <td className="px-2 py-2">{s.display_name}</td>
                  <td className="px-2 py-2">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] ${
                        s.client_type === "pwa"
                          ? "bg-sky-900/40 text-sky-300"
                          : "bg-neutral-800 text-neutral-300"
                      }`}
                    >
                      {s.client_type}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-neutral-300">{s.device_label ?? "-"}</td>
                  <td className="px-2 py-2 text-neutral-300">
                    {s.last_seen_at ? formatRelative(s.last_seen_at) : "-"}
                  </td>
                  <td className="px-2 py-2 text-neutral-400">{formatDate(s.expires_at)}</td>
                  <td className="px-2 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => revoke(s.id, s.display_name)}
                      className={smallButtonCls}
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Auth events
// ---------------------------------------------------------------------------
function AuthEventsSection() {
  const [rows, setRows] = useState<AuthEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<AuthEvent[]>("/api/admin/auth-events?limit=50");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load auth events.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <div className="flex items-baseline justify-end gap-3">
        <button
          type="button"
          onClick={load}
          className="text-xs text-neutral-500 hover:text-neutral-200"
        >
          Refresh
        </button>
      </div>
      <div className="mt-4 overflow-x-auto">
        {error ? (
          <div className="rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        ) : rows === null ? (
          <div className="h-16 animate-pulse rounded-md bg-neutral-900" />
        ) : rows.length === 0 ? (
          <div className="rounded-md border border-dashed border-neutral-800 bg-neutral-900/30 px-4 py-6 text-sm text-neutral-500">
            No auth events recorded.
          </div>
        ) : (
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-neutral-500">
              <tr className="border-b border-neutral-800">
                <th className="px-2 py-2 font-medium">When</th>
                <th className="px-2 py-2 font-medium">User</th>
                <th className="px-2 py-2 font-medium">Event</th>
                <th className="px-2 py-2 font-medium">IP</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className="border-b border-neutral-900 last:border-b-0">
                  <td className="px-2 py-2 text-neutral-300">{formatRelative(e.at)}</td>
                  <td className="px-2 py-2">{e.username ?? <span className="text-neutral-500">unknown</span>}</td>
                  <td className="px-2 py-2 text-neutral-200">{e.event}</td>
                  <td className="px-2 py-2 font-sans text-xs text-neutral-400">{e.ip ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared style + formatting helpers
// ---------------------------------------------------------------------------
const inputCls =
  "w-full rounded-lg border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-500";

const primaryButtonCls =
  "rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60";

const smallButtonCls =
  "rounded-md border border-neutral-800 px-2.5 py-1 text-xs text-neutral-200 transition hover:border-neutral-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-50";

function formatRelative(iso: string): string {
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

function formatDate(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
}

function formatPosition(sec: number): string {
  if (sec <= 0) return "0:00";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}
