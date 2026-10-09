// Admin > Updates. Shows the installed and latest F7FIVE0 versions and the
// phone app that ships with this server, checks GitHub on demand (the server
// also checks once a day), and updates the server in one click, from the latest
// GitHub release or from a Setup you upload.
//
// The work runs on the server in the F7FIVE0-Update scheduled task (SYSTEM),
// started by POST /api/admin/updates/apply or /upload. The server verifies the
// Setup first: a release download must match its published checksum; an upload
// needs your admin password and must be a published release build (or carry the
// F7FIVE0 signature). The updater backs up the database, installs, checks that
// the new version comes up, and goes back to the old one if it doesn't. This
// card polls the run, and keeps polling while the services restart.
//
// Release notes are plain text from GitHub: never rendered as HTML.

"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { apiGet, apiPost, refreshSession, ApiError } from "@/lib/client-api";
import type { UpdateRun, UpdatesStatus } from "@/lib/types";
import { resetUpdateBadge } from "@/lib/update-badge";
import {
  UPDATE_STEPS, blockedText, checkedAgo, encodePasswordHeader, formatBytes, phaseLabel,
  runSummary, stepIndex, upToDateMessages, updateErrorText,
} from "@/lib/updates";

function errorOf(err: unknown): string {
  if (err instanceof ApiError) return updateErrorText(err.detail, err.message);
  return err instanceof Error ? err.message : "Something went wrong.";
}

type UploadResult = { status: number; body: unknown };

export function UpdatesSection() {
  const [status, setStatus] = useState<UpdatesStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [run, setRun] = useState<UpdateRun | null>(null);
  const [dismissedRun, setDismissedRun] = useState<string | null>(null);
  const [lostContact, setLostContact] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkedNow, setCheckedNow] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const wasActive = useRef(false);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<UpdatesStatus>("/api/admin/updates");
      setStatus(data);
      setRun(data.run);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorOf(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const active = run?.active ?? false;

  // Poll the run while it is active. Setup stops the API and web app for a
  // while, so failed polls are expected, not errors.
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await apiGet<UpdateRun>("/api/admin/updates/run");
        if (cancelled) return;
        setLostContact(false);
        setRun(next);
      } catch {
        if (!cancelled) setLostContact(true);
      }
    };
    const id = window.setInterval(tick, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [active]);

  // When a run ends, reload the card (new version, new badge state).
  useEffect(() => {
    if (wasActive.current && !active) {
      resetUpdateBadge();
      void load();
    }
    wasActive.current = active;
  }, [active, load]);

  async function checkNow() {
    setChecking(true);
    setActionError(null);
    setCheckedNow(false);
    try {
      const data = await apiPost<UpdatesStatus>("/api/admin/updates/check", {});
      setStatus(data);
      setRun(data.run);
      resetUpdateBadge();
      setCheckedNow(true);
    } catch (err) {
      setActionError(errorOf(err));
    } finally {
      setChecking(false);
    }
  }

  async function startUpdate() {
    setBusy(true);
    setActionError(null);
    try {
      const next = await apiPost<UpdateRun>("/api/admin/updates/apply", {});
      setRun(next);
      setDismissedRun(null);
      setConfirming(false);
    } catch (err) {
      setActionError(errorOf(err));
    } finally {
      setBusy(false);
    }
  }

  // XMLHttpRequest, not fetch: it reports upload progress. The body is the raw
  // file; the password rides in a header (percent-encoded) and the server
  // checks it before reading the file.
  function sendUpload(f: File, pw: string): Promise<UploadResult> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/admin/updates/upload");
      xhr.setRequestHeader("content-type", "application/octet-stream");
      xhr.setRequestHeader("x-confirm-password", encodePasswordHeader(pw));
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && e.total > 0) setUploadPct(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        let body: unknown = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          // Not JSON: leave it null.
        }
        resolve({ status: xhr.status, body });
      };
      xhr.onerror = () => reject(new Error("network"));
      xhr.send(f);
    });
  }

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) {
      setActionError("Choose the Setup file first.");
      return;
    }
    if (!password) {
      setActionError(updateErrorText("admin_password_required"));
      return;
    }
    const pw = password;
    setPassword("");
    setBusy(true);
    setUploadPct(0);
    setActionError(null);
    try {
      let res = await sendUpload(file, pw);
      if (res.status === 401) {
        // The access token expired mid-session: refresh once and send again.
        if (!(await refreshSession())) {
          window.location.replace("/login");
          return;
        }
        res = await sendUpload(file, pw);
      }
      if (res.status === 202) {
        setRun(res.body as UpdateRun);
        setDismissedRun(null);
        setFile(null);
        setUploadOpen(false);
      } else {
        const detail = (res.body as { detail?: string } | null)?.detail ?? null;
        setActionError(updateErrorText(detail, `The server answered ${res.status}.`));
      }
    } catch {
      setActionError("The upload didn't reach the server. Check the connection and try again.");
    } finally {
      setBusy(false);
      setUploadPct(null);
    }
  }

  const showRun = run !== null && run.phase !== "idle" && run.id !== dismissedRun;
  const blocked = status ? blockedText(status.install_blocked) : null;
  // "You're up to date." shows in one place: the hint, or the notice after Check now.
  const upToDate = status
    ? upToDateMessages({
        latestVersion: status.latest_version,
        updateAvailable: status.update_available,
        checkError: status.check_error,
        checkedNow,
      })
    : null;
  const canUpdate = status !== null && status.can_install && !active && status.rollback_ready;

  return (
    <section className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-6" aria-labelledby="updates-heading">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="updates-heading" className="text-base font-semibold">Updates</h2>
        <button
          type="button"
          onClick={() => void checkNow()}
          disabled={checking || active}
          className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-100 hover:border-neutral-400 disabled:opacity-50"
        >
          {checking ? "Checking…" : "Check now"}
        </button>
      </div>
      <p className="mt-1 text-xs text-neutral-500">
        F7FIVE0 checks GitHub once a day. Updating the server also updates the phone app it hands out.
      </p>

      {loadError ? (
        <div className="mt-4 rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">{loadError}</div>
      ) : status === null ? (
        <div className="mt-4 h-24 animate-pulse rounded-md bg-neutral-900" />
      ) : (
        <div className="mt-4 space-y-4">
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <Fact label="Installed version" value={status.installed_version} testId="installed-version" />
            <Fact
              label="Phone app on this server"
              value={status.phone_app_version ?? "None bundled"}
              testId="phone-app-version"
            />
            <Fact
              label="Latest version"
              value={status.latest_version ?? "Not known yet"}
              testId="latest-version"
              hint={upToDate?.hint}
            />
            <Fact label="Last checked" value={checkedAgo(status.checked_at)} testId="last-checked" />
          </dl>

          {status.check_error ? (
            <div className="rounded-md border border-line bg-hive-tint px-4 py-3 text-sm text-hive-text" role="alert">
              The last check didn&apos;t work: {status.check_error}
            </div>
          ) : null}
          {upToDate?.notice ? <p className="text-sm text-neutral-300">{upToDate.notice}</p> : null}

          {status.update_available && status.notes ? (
            <div>
              <h3 className="text-sm font-medium text-neutral-200">What&apos;s new in {status.latest_version}</h3>
              <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-md border border-neutral-800 bg-neutral-950 p-3 font-sans text-xs text-neutral-300">
                {status.notes}
              </pre>
            </div>
          ) : null}

          {actionError ? (
            <div className="rounded-md border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200" role="alert">
              {actionError}
            </div>
          ) : null}

          {showRun && run ? (
            <RunPanel run={run} lostContact={lostContact} onDismiss={() => setDismissedRun(run.id)} />
          ) : null}

          {!active ? (
            <div className="space-y-3">
              {status.update_available ? (
                <div className="space-y-2">
                  {blocked ? <p className="text-sm text-neutral-400">{blocked}</p> : null}
                  {!status.rollback_ready ? (
                    <p className="text-sm text-neutral-400">
                      This server has no saved copy of the Setup that is installed now, so it couldn&apos;t go back
                      if an update failed. Run the new Setup by hand once; it keeps a copy for next time.
                    </p>
                  ) : null}
                  {confirming ? (
                    <div className="rounded-md border border-neutral-700 bg-neutral-950 p-4 text-sm text-neutral-300">
                      <p>
                        F7FIVE0 will stop for a few minutes, back up the database, install version{" "}
                        {status.latest_version}, and check that it comes up. If it doesn&apos;t, it goes back to{" "}
                        {status.installed_version} and restores the backup.
                      </p>
                      <div className="mt-3 flex gap-2">
                        <button
                          type="button"
                          onClick={() => void startUpdate()}
                          disabled={busy}
                          className="rounded-md bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-950 hover:bg-white disabled:opacity-50"
                        >
                          {busy ? "Starting…" : "Update now"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirming(false)}
                          className="rounded-md border border-neutral-700 px-4 py-2 text-sm text-neutral-200 hover:border-neutral-400"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirming(true)}
                      disabled={!canUpdate}
                      className="rounded-md bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-950 hover:bg-white disabled:opacity-50"
                    >
                      Update to v{status.latest_version}
                    </button>
                  )}
                </div>
              ) : null}

              <div>
                {uploadOpen ? (
                  <form onSubmit={(e) => void upload(e)} className="space-y-3 rounded-md border border-neutral-800 p-4">
                    <p className="text-sm text-neutral-300">
                      Upload a F7FIVE0 Setup (a Setup .exe from a GitHub release). It is installed only if it is
                      exactly a published release
                      {status.signer_configured ? " or carries the F7FIVE0 signature" : ""}
                      , which is checked against GitHub, so this server needs internet for it. Any other file is
                      refused, and so is the same or an older version.
                      {!status.signer_configured
                        ? " Unsigned test builds are always refused."
                        : ""}
                    </p>
                    <label className="block text-sm">
                      <span className="text-neutral-300">Setup file</span>
                      <input
                        type="file"
                        accept=".exe"
                        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                        className="mt-1 block w-full text-sm text-neutral-300"
                      />
                      <span className="mt-1 block text-xs text-neutral-500">Up to {status.max_setup_mb} MB.</span>
                    </label>
                    <label className="block text-sm">
                      <span className="text-neutral-300">Your admin password</span>
                      <input
                        type="password"
                        autoComplete="current-password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        className="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 font-sans text-sm text-neutral-100"
                      />
                      <span className="mt-1 block text-xs text-neutral-500">
                        Asked again every time, because an update changes the whole server.
                      </span>
                    </label>
                    {uploadPct !== null ? (
                      <p className="text-xs text-neutral-400">
                        {uploadPct < 100 ? `Sending the file: ${uploadPct}%` : "Checking the file against the published release…"}
                      </p>
                    ) : null}
                    <div className="flex gap-2">
                      <button
                        type="submit"
                        disabled={busy}
                        className="rounded-md bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-950 hover:bg-white disabled:opacity-50"
                      >
                        {busy ? "Working…" : "Upload and update"}
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setUploadOpen(false);
                          setPassword("");
                          setActionError(null);
                        }}
                        className="rounded-md border border-neutral-700 px-4 py-2 text-sm text-neutral-200 hover:border-neutral-400 disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <button
                    type="button"
                    onClick={() => setUploadOpen(true)}
                    className="text-sm text-neutral-400 underline-offset-2 hover:text-neutral-100 hover:underline"
                  >
                    Upload a Setup
                  </button>
                )}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function Fact({ label, value, hint, testId }: { label: string; value: string; hint?: string; testId: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-neutral-500">{label}</dt>
      <dd className="mt-0.5 text-neutral-100" data-testid={testId}>
        {value}
        {hint ? <span className="ml-2 text-xs text-neutral-500">{hint}</span> : null}
      </dd>
    </div>
  );
}

function RunPanel({ run, lostContact, onDismiss }: { run: UpdateRun; lostContact: boolean; onDismiss: () => void }) {
  const current = stepIndex(run.phase);
  const finished = !run.active;
  const summary = runSummary(run);
  const tone =
    run.phase === "done"
      ? "border-emerald-900/60 bg-emerald-950/30"
      : run.phase === "failed" || run.phase === "rolled_back"
        ? "border-red-900/60 bg-red-950/40"
        : "border-neutral-700 bg-neutral-950";
  const problem = run.phase === "failed" || run.phase === "rolled_back" ? run.error ?? updateErrorText(run.error_code) : null;
  const pct =
    run.phase === "downloading" && run.total_bytes && run.downloaded_bytes !== null
      ? Math.min(100, Math.round((run.downloaded_bytes / run.total_bytes) * 100))
      : null;

  return (
    <div className={`rounded-md border p-4 text-sm ${tone}`} aria-live="polite" data-testid="update-run">
      <div className="flex items-baseline justify-between gap-3">
        <p className="font-medium text-neutral-100">{phaseLabel(run.phase)}</p>
        {run.to_version ? (
          <p className="text-xs text-neutral-500">
            {run.from_version ?? "?"} → {run.to_version}
          </p>
        ) : null}
      </div>

      {current >= 0 ? (
        <ol className="mt-3 grid grid-cols-5 gap-1 text-[11px] text-neutral-500">
          {UPDATE_STEPS.map((s, i) => (
            <li
              key={s}
              className={`rounded px-1.5 py-1 text-center ${
                i < current ? "bg-neutral-800 text-neutral-300" : i === current ? "bg-neutral-100 font-medium text-neutral-950" : "bg-neutral-900"
              }`}
            >
              {phaseLabel(s).split(" ").slice(0, 2).join(" ")}
            </li>
          ))}
        </ol>
      ) : null}

      {run.active && run.step ? <p className="mt-3 text-neutral-300">{run.step}</p> : null}
      {pct !== null ? (
        <div className="mt-2">
          <div className="h-1.5 w-full overflow-hidden rounded bg-neutral-800">
            <div className="h-full bg-neutral-200" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-1 text-xs text-neutral-500">
            {formatBytes(run.downloaded_bytes)} of {formatBytes(run.total_bytes)}
          </p>
        </div>
      ) : null}

      {lostContact && run.active ? (
        <p className="mt-3 text-neutral-400">
          F7FIVE0 is restarting, so this page can&apos;t reach it for a moment. It keeps trying by itself.
        </p>
      ) : null}

      {summary ? <p className="mt-3 text-neutral-200">{summary}</p> : null}
      {problem ? <p className="mt-2 text-red-200">{problem}</p> : null}

      {run.log.length > 0 ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-neutral-500 hover:text-neutral-300">Details</summary>
          <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-neutral-950 p-2 font-mono text-[11px] text-neutral-400">
            {run.log.join("\n")}
          </pre>
        </details>
      ) : null}

      {finished ? (
        <div className="mt-3 flex gap-2">
          {run.phase === "done" ? (
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-md bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-950 hover:bg-white"
            >
              Reload this page
            </button>
          ) : null}
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-200 hover:border-neutral-400"
          >
            Dismiss
          </button>
        </div>
      ) : null}
    </div>
  );
}
