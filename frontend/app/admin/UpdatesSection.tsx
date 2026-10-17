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
// Release notes are Markdown from GitHub. lib/release-notes.ts reads the small
// part the notes use into data rendered as React elements: never as HTML.

"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { apiGet, apiPut, apiPost, refreshSession, ApiError } from "@/lib/client-api";
import type { UpdateRun, UpdatesStatus } from "@/lib/types";
import { resetUpdateBadge } from "@/lib/update-badge";
import {
  UPDATE_STEPS, blockedText, checkedAgo, encodePasswordHeader, formatBytes, offlineView,
  phaseChipLabel, phaseLabel, runSummary, stepIndex, upToDateMessages, updateErrorText,
} from "@/lib/updates";
import { parseReleaseNotes, type Inline } from "@/lib/release-notes";

type DismissedOut = { run_id: string | null };

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
  // When this page last lost contact during an update (null while in touch).
  const [lostSince, setLostSince] = useState<number | null>(null);
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

  // The dismissed run id lives on the server (app_settings update_run_dismissed),
  // so Dismiss sticks across reloads, browsers and other admins. A new run has a
  // new id, so its result panel shows again.
  useEffect(() => {
    let cancelled = false;
    void apiGet<DismissedOut>("/api/admin/updates/dismissed")
      .then((d) => {
        if (!cancelled) setDismissedRun(d.run_id);
      })
      .catch(() => {
        // Best-effort: fall back to showing the panel.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const dismissRun = useCallback((runId: string) => {
    setDismissedRun(runId);
    void apiPut("/api/admin/updates/dismissed", { run_id: runId }).catch(() => {
      // Best-effort: it still hides for this page load.
    });
  }, []);

  const clearDismissed = useCallback(() => {
    setDismissedRun(null);
    void apiPut("/api/admin/updates/dismissed", { run_id: null }).catch(() => {
      // Best-effort.
    });
  }, []);

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
        setLostSince(null);
        setRun(next);
      } catch {
        if (!cancelled) {
          setLostContact(true);
          setLostSince((t) => t ?? Date.now());
        }
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
      clearDismissed();
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
        const refreshed = await refreshSession();
        if (refreshed === "sign-out") {
          window.location.replace("/login");
          return;
        }
        if (refreshed === "keep-session") {
          setActionError("The server isn't answering right now. You are still signed in; try again in a moment.");
          return;
        }
        res = await sendUpload(file, pw);
      }
      if (res.status === 202) {
        setRun(res.body as UpdateRun);
        clearDismissed();
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
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-xs text-ink-3">
          F7FIVE0 checks GitHub once a day. Updating the server also updates the phone app it hands out.
        </p>
        <button
          type="button"
          onClick={() => void checkNow()}
          disabled={checking || active}
          className="shrink-0 rounded-md border border-line-strong px-3 py-1.5 text-xs font-medium text-ink hover:border-ink-2 disabled:opacity-50"
        >
          {checking ? "Checking…" : "Check now"}
        </button>
      </div>

      {loadError ? (
        <div className="mt-4 rounded-md border border-line bg-hive-tint px-4 py-3 text-sm text-hive-text">{loadError}</div>
      ) : status === null ? (
        <div className="mt-4 h-24 animate-pulse rounded-md bg-surface-2" />
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
          {upToDate?.notice ? <p className="text-sm text-ink-2">{upToDate.notice}</p> : null}

          {status.update_available && status.notes ? (
            <div>
              <h3 className="text-sm font-medium text-ink">What&apos;s new in {status.latest_version}</h3>
              <ReleaseNotes notes={status.notes} />
            </div>
          ) : null}

          {actionError ? (
            <div className="rounded-md border border-line bg-hive-tint px-4 py-3 text-sm text-hive-text" role="alert">
              {actionError}
            </div>
          ) : null}

          {showRun && run ? (
            <RunPanel run={run} lostContact={lostContact} lostSince={lostSince} onDismiss={() => run.id && dismissRun(run.id)} />
          ) : null}

          {!active ? (
            <div className="space-y-3">
              {status.update_available ? (
                <div className="space-y-2">
                  {blocked ? <p className="text-sm text-ink-2">{blocked}</p> : null}
                  {!status.rollback_ready ? (
                    <p className="text-sm text-ink-2">
                      This server has no saved copy of the Setup that is installed now, so it couldn&apos;t go back
                      if an update failed. Run the new Setup by hand once; it keeps a copy for next time.
                    </p>
                  ) : null}
                  {confirming ? (
                    <div className="rounded-md border border-line-strong bg-surface-1 p-4 text-sm text-ink-2">
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
                          className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-bg hover:bg-ink-2 disabled:opacity-50"
                        >
                          {busy ? "Starting…" : "Update now"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirming(false)}
                          className="rounded-md border border-line-strong px-4 py-2 text-sm text-ink hover:border-ink-2"
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
                      className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-bg hover:bg-ink-2 disabled:opacity-50"
                    >
                      Update to v{status.latest_version}
                    </button>
                  )}
                </div>
              ) : null}

              <div>
                {uploadOpen ? (
                  <form onSubmit={(e) => void upload(e)} className="space-y-3 rounded-md border border-line p-4">
                    <p className="text-sm text-ink-2">
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
                      <span className="text-ink-2">Setup file</span>
                      <input
                        type="file"
                        accept=".exe"
                        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                        className="mt-1 block w-full text-sm text-ink-2"
                      />
                      <span className="mt-1 block text-xs text-ink-3">Up to {status.max_setup_mb} MB.</span>
                    </label>
                    <label className="block text-sm">
                      <span className="text-ink-2">Your admin password</span>
                      <input
                        type="password"
                        autoComplete="current-password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        className="mt-1 w-full rounded-md border border-line-strong bg-surface-1 px-3 py-2 font-sans text-sm text-ink"
                      />
                      <span className="mt-1 block text-xs text-ink-3">
                        Asked again every time, because an update changes the whole server.
                      </span>
                    </label>
                    {uploadPct !== null ? (
                      <p className="text-xs text-ink-2">
                        {uploadPct < 100 ? `Sending the file: ${uploadPct}%` : "Checking the file against the published release…"}
                      </p>
                    ) : null}
                    <div className="flex gap-2">
                      <button
                        type="submit"
                        disabled={busy}
                        className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-bg hover:bg-ink-2 disabled:opacity-50"
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
                        className="rounded-md border border-line-strong px-4 py-2 text-sm text-ink hover:border-ink-2 disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <button
                    type="button"
                    onClick={() => setUploadOpen(true)}
                    className="text-sm text-ink-2 underline-offset-2 hover:text-ink hover:underline"
                  >
                    Upload a Setup
                  </button>
                )}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function Fact({ label, value, hint, testId }: { label: string; value: string; hint?: string; testId: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-ink-3">{label}</dt>
      <dd className="mt-0.5 text-ink" data-testid={testId}>
        {value}
        {hint ? <span className="ml-2 text-xs text-ink-3">{hint}</span> : null}
      </dd>
    </div>
  );
}

function RunPanel({
  run,
  lostContact,
  lostSince,
  onDismiss,
}: {
  run: UpdateRun;
  lostContact: boolean;
  lostSince: number | null;
  onDismiss: () => void;
}) {
  // Tick once a second while offline so the timer moves.
  const [now, setNow] = useState(() => Date.now());
  const offlineActive = lostContact && run.active && lostSince !== null;
  useEffect(() => {
    if (!offlineActive) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [offlineActive]);
  const offline = lostContact ? offlineView(run, lostSince, now) : null;
  const shownPhase = offline?.phase ?? run.phase;
  const current = stepIndex(shownPhase);
  const finished = !run.active;
  const summary = runSummary(run);
  const tone =
    run.phase === "done"
      ? "border-line bg-surface-2"
      : run.phase === "failed" || run.phase === "rolled_back"
        ? "border-line bg-hive-tint"
        : "border-line-strong bg-surface-1";
  const problem = run.phase === "failed" || run.phase === "rolled_back" ? run.error ?? updateErrorText(run.error_code) : null;
  const pct =
    run.phase === "downloading" && run.total_bytes && run.downloaded_bytes !== null
      ? Math.min(100, Math.round((run.downloaded_bytes / run.total_bytes) * 100))
      : null;

  return (
    <div className={`rounded-md border p-4 text-sm ${tone}`} aria-live="polite" data-testid="update-run">
      <div className="flex items-baseline justify-between gap-3">
        <p className="font-medium text-ink">{phaseLabel(shownPhase)}</p>
        {run.to_version ? (
          <p className="text-xs text-ink-3">
            {run.from_version ?? "?"} → {run.to_version}
          </p>
        ) : null}
      </div>

      {current >= 0 ? (
        <ol className="mt-3 grid grid-cols-5 gap-1 text-[11px] text-ink-3">
          {UPDATE_STEPS.map((s, i) => (
            <li
              key={s}
              className={`rounded px-1.5 py-1 text-center ${
                i < current ? "bg-surface-3 text-ink-2" : i === current ? "bg-ink font-medium text-bg" : "bg-surface-2"
              }`}
            >
              {phaseChipLabel(s)}
            </li>
          ))}
        </ol>
      ) : null}

      {run.active && run.step && !offline ? <p className="mt-3 text-ink-2">{run.step}</p> : null}
      {pct !== null ? (
        <div className="mt-2">
          <div className="h-1.5 w-full overflow-hidden rounded bg-surface-3">
            <div className="h-full bg-ink-2" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-1 text-xs text-ink-3">
            {formatBytes(run.downloaded_bytes)} of {formatBytes(run.total_bytes)}
          </p>
        </div>
      ) : null}

      {offline ? (
        <div className="mt-3 space-y-2">
          <p className="text-ink-2" data-testid="update-offline">
            {offline.message}
          </p>
          <div className="h-1 w-full overflow-hidden rounded bg-surface-3" aria-hidden="true">
            <div className="h-full w-1/3 animate-pulse bg-ink-2" />
          </div>
          {offline.slowHint ? <p className="text-xs text-ink-3">{offline.slowHint}</p> : null}
        </div>
      ) : lostContact && run.active ? (
        <p className="mt-3 text-ink-2">
          F7FIVE0 is restarting, so this page can&apos;t reach it for a moment. It keeps trying by itself.
        </p>
      ) : null}

      {summary ? <p className="mt-3 text-ink">{summary}</p> : null}
      {problem ? <p className="mt-2 text-hive-text">{problem}</p> : null}

      {run.log.length > 0 ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-ink-3 hover:text-ink">Details</summary>
          <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-surface-1 p-2 font-mono text-[11px] text-ink-2">
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
              className="rounded-md bg-ink px-3 py-1.5 text-xs font-medium text-bg hover:bg-ink-2"
            >
              Reload this page
            </button>
          ) : null}
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:border-ink-2"
          >
            Dismiss
          </button>
        </div>
      ) : null}
    </div>
  );
}

function InlineText({ parts }: { parts: Inline[] }) {
  return (
    <>
      {parts.map((p, i) => {
        if (p.kind === "bold") return <strong key={i} className="font-semibold text-ink">{p.text}</strong>;
        if (p.kind === "code") return <code key={i} className="rounded bg-surface-3 px-1 font-mono text-[11px]">{p.text}</code>;
        if (p.kind === "link") {
          return (
            <a key={i} href={p.href} target="_blank" rel="noopener noreferrer" className="underline hover:text-ink">
              {p.text}
            </a>
          );
        }
        return <span key={i}>{p.text}</span>;
      })}
    </>
  );
}

function ReleaseNotes({ notes }: { notes: string }) {
  const blocks = parseReleaseNotes(notes);
  return (
    <div
      className="mt-2 max-h-56 space-y-2 overflow-auto rounded-md border border-line bg-surface-1 p-3 text-xs leading-relaxed text-ink-2"
      data-testid="release-notes"
    >
      {blocks.map((b, i) => {
        if (b.kind === "heading") {
          return (
            <p key={i} className="text-sm font-medium text-ink">
              <InlineText parts={b.content} />
            </p>
          );
        }
        if (b.kind === "list") {
          const Tag = b.ordered ? "ol" : "ul";
          return (
            <Tag key={i} className={`space-y-1 pl-5 ${b.ordered ? "list-decimal" : "list-disc"}`}>
              {b.items.map((item, j) => (
                <li key={j}>
                  <InlineText parts={item} />
                </li>
              ))}
            </Tag>
          );
        }
        return (
          <p key={i}>
            <InlineText parts={b.content} />
          </p>
        );
      })}
    </div>
  );
}
