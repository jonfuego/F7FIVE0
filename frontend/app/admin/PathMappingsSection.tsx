// Admin > Library folders > Path mappings.
//
// Radarr, Sonarr and Lidarr often report files on a drive letter (N:\Movies\...)
// that is mapped only in one person's Windows login. The F7FIVE0 services run
// as a system account that has no N:, so those files look missing and the
// library looks nearly empty. A mapping says what the letter means (N: is
// \\fuegonas\The Hive). Mappings take effect without a restart, and saving one
// also rewrites the paths already stored, so watch history is kept.
//
// The block also checks each *arr app's root folders from the server's side and
// warns about one the service cannot open, naming the drive.

"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { TriangleAlert } from "lucide-react";
import { Icon } from "@/components/Icon";
import { apiDelete, apiGet, apiPost, ApiError } from "@/lib/client-api";
import { plural } from "@/lib/admin-dashboard";
import type { ArrRoot, ArrRoots, PathMapping, PathMappings } from "@/lib/types";
import { inputCls, primaryButtonCls, smallButtonCls } from "./admin-ui";

const BASE = "/api/admin/path-mappings";

const FRIENDLY: Record<string, string> = {
  bad_drive: "The drive must be one letter and a colon, like N:.",
  bad_target: "The path must be a network path like \\\\server\\share, or a full folder path like D:\\Media.",
  loop: "A drive can't be mapped to itself.",
  mapping_not_found: "That mapping is already gone.",
};

function errorText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return FRIENDLY[err.detail] ?? err.detail;
  return err instanceof Error ? err.message : "Something went wrong.";
}

export function PathMappingsSection() {
  const [data, setData] = useState<PathMappings | null>(null);
  const [roots, setRoots] = useState<ArrRoots | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [drive, setDrive] = useState("");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const loadRoots = useCallback(async () => {
    try {
      setRoots(await apiGet<ArrRoots>(`${BASE}/arr-roots`));
    } catch {
      setRoots(null);
    }
  }, []);

  const load = useCallback(async () => {
    try {
      setData(await apiGet<PathMappings>(BASE));
      setLoadError(null);
    } catch (err) {
      setLoadError(errorText(err));
    }
    void loadRoots();
  }, [loadRoots]);

  useEffect(() => {
    void load();
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setMessage(null);
    try {
      const saved = await apiPost<PathMappings>(BASE, { src: drive.trim(), dst: target.trim() });
      setData(saved);
      setDrive("");
      setTarget("");
      const moved = saved.rewritten + saved.merged;
      setMessage({
        ok: true,
        text: moved > 0
          ? `Saved. ${plural(moved, "stored path was", "stored paths were")} updated, and watch history was kept. Run Sync now under Scans.`
          : "Saved. Run Sync now under Scans so the files are found.",
      });
      void loadRoots();
    } catch (err) {
      setMessage({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function remove(m: PathMapping) {
    if (busy) return;
    if (!window.confirm(`Remove the mapping ${m.src} to ${m.dst}? Paths already updated stay as they are.`)) return;
    setBusy(true);
    setMessage(null);
    try {
      setData(await apiDelete<PathMappings>(`${BASE}?src=${encodeURIComponent(m.src)}`));
      void loadRoots();
    } catch (err) {
      setMessage({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  const unreachable: ArrRoot[] = (roots?.roots ?? []).filter((r) => !r.reachable);

  return (
    <section aria-labelledby="path-mappings-heading" className="mt-7" data-testid="path-mappings">
      <h2 id="path-mappings-heading" className="title-2 text-ink">Path mappings</h2>
      <p className="body mt-1 max-w-2xl text-ink-2">
        Radarr, Sonarr or Lidarr may list files on a drive letter like N:, mapped only in your own
        Windows login. The F7FIVE0 service can&apos;t see it. Say what the letter means here, and
        the library finds those files. No restart needed.
      </p>

      {unreachable.length > 0 ? (
        <div role="alert" className="mt-4 border border-line bg-surface-1 p-4" data-testid="unreachable-roots">
          <p className="flex items-center gap-2 font-semibold text-warning">
            <Icon icon={TriangleAlert} size={16} />
            The service can&apos;t open {plural(unreachable.length, "folder", "folders")} your *arr apps use
          </p>
          <ul className="mt-2 space-y-2 text-sm text-ink-2">
            {unreachable.map((r) => (
              <li key={`${r.app}:${r.path}`} className="flex flex-wrap items-center justify-between gap-2">
                <span className="min-w-0 break-all">
                  {r.label}: <span className="text-ink">{r.path}</span>
                  {r.drive ? ` (drive ${r.drive} is not visible to the service)` : ""}
                </span>
                {r.drive ? (
                  <button type="button" className={smallButtonCls} onClick={() => setDrive(r.drive ?? "")}>
                    Map {r.drive}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {roots && roots.errors.length > 0 ? (
        <p className="mt-3 text-xs text-ink-3">
          {roots.errors.map((e) => `${e.label} did not answer, so its folders were not checked.`).join(" ")}
        </p>
      ) : null}

      <div className="mt-4">
        {loadError ? (
          <p role="alert" className="text-sm text-hive-text">{loadError}</p>
        ) : data === null ? (
          <div className="h-16 animate-pulse bg-surface-2" />
        ) : (
          <>
            {data.mappings.length === 0 && data.env_rules.length === 0 ? (
              <p className="py-2 text-[15px] text-ink-3">No mappings yet.</p>
            ) : (
              <ul className="divide-y divide-line border-y border-line">
                {data.mappings.map((m) => (
                  <li key={m.src} className="flex flex-wrap items-center justify-between gap-3 py-2">
                    <span className="min-w-0 break-all text-[15px] text-ink">
                      <span className="font-semibold">{m.src}</span> → {m.dst}
                    </span>
                    <button type="button" className={smallButtonCls} disabled={busy} onClick={() => void remove(m)}>
                      Remove
                    </button>
                  </li>
                ))}
                {data.env_rules.map((m) => (
                  <li key={`env:${m.src}`} className="flex flex-wrap items-center justify-between gap-3 py-2">
                    <span className="min-w-0 break-all text-[15px] text-ink-2">
                      <span className="font-semibold">{m.src}</span> → {m.dst}
                    </span>
                    <span className="text-xs text-ink-3">From PATH_REWRITE_RULES in .env</span>
                  </li>
                ))}
              </ul>
            )}

            <form onSubmit={add} className="mt-4 grid grid-cols-1 gap-3 min-[720px]:grid-cols-[120px_minmax(0,1fr)_auto]">
              <label className="block">
                <span className="caption text-ink-2">Drive</span>
                <input
                  type="text"
                  value={drive}
                  onChange={(e) => setDrive(e.target.value)}
                  placeholder="N:"
                  maxLength={3}
                  autoCapitalize="characters"
                  autoComplete="off"
                  spellCheck={false}
                  className={`${inputCls} mt-1`}
                />
              </label>
              <label className="block">
                <span className="caption text-ink-2">Network path</span>
                <input
                  type="text"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  placeholder="\\fuegonas\The Hive"
                  autoComplete="off"
                  spellCheck={false}
                  className={`${inputCls} mt-1`}
                />
              </label>
              <div className="self-end">
                <button type="submit" disabled={busy || !drive.trim() || !target.trim()} className={primaryButtonCls}>
                  {busy ? "Saving..." : "Add mapping"}
                </button>
              </div>
            </form>
          </>
        )}
        {message ? (
          <p role={message.ok ? "status" : "alert"} className={`mt-3 text-sm ${message.ok ? "text-ink-2" : "text-hive-text"}`}>
            {message.text}{" "}
            {message.ok ? (
              <Link href="/admin/scans" className="font-semibold text-hive-text hover:underline">Open Scans</Link>
            ) : null}
          </p>
        ) : null}
      </div>
    </section>
  );
}
