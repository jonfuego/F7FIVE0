// Admin > Users: the user list with role, enable/disable and password reset, and
// the new-user form. Admin only; the layout checks the role before this renders.

"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { apiGet, apiPatch, apiPost, ApiError } from "@/lib/client-api";
import {
  errorMessage, okMessage, ownRowReason, rowMessageFor, userActionErrorText, type RowMessage,
} from "@/lib/admin-users";
import type { AdminUser, Me } from "@/lib/types";
import { inputCls, primaryButtonCls, smallButtonCls } from "./admin-ui";

export function UsersSection({ me }: { me: Me }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The result of the last action, shown next to the row it belongs to.
  const [rowMsg, setRowMsg] = useState<RowMessage | null>(null);

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
    setRowMsg(null);
    try {
      const updated = await apiPatch<AdminUser>(`/api/admin/users/${id}`, body);
      setUsers((prev) => (prev ? prev.map((u) => (u.id === id ? updated : u)) : prev));
      setRowMsg(okMessage(id, "Saved."));
    } catch (err) {
      setRowMsg(errorMessage(id, userActionErrorText(err)));
    }
  }

  async function resetPassword(id: string) {
    const next = window.prompt("New password (min 8 chars):");
    if (!next) return;
    if (next.length < 8) {
      setRowMsg(errorMessage(id, "Password must be at least 8 characters."));
      return;
    }
    setRowMsg(null);
    try {
      await apiPost(`/api/admin/users/${id}/password`, { new_password: next });
      setRowMsg(okMessage(id, "Password reset. The user will need to sign in again."));
    } catch (err) {
      setRowMsg(errorMessage(id, userActionErrorText(err, "Password reset failed.")));
    }
  }

  return (
    <div>
      <NewUserForm onCreated={(u) => {
        setUsers((prev) => (prev ? [...prev, u] : [u]));
        setRowMsg(okMessage(u.id, `Created ${u.username}.`));
      }} />

      <div className="mt-6 overflow-x-auto">
        {error ? (
          <div className="rounded-md border border-line bg-hive-tint px-4 py-3 text-sm text-hive-text">
            {error}
          </div>
        ) : users === null ? (
          <div className="h-24 animate-pulse rounded-md bg-surface-2" />
        ) : users.length === 0 ? (
          <div className="rounded-md border border-dashed border-line bg-surface-2 px-4 py-6 text-sm text-ink-3">
            No users yet.
          </div>
        ) : (
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-ink-3">
              <tr className="border-b border-line">
                <th className="px-2 py-2 font-medium">Username</th>
                <th className="px-2 py-2 font-medium">Name</th>
                <th className="px-2 py-2 font-medium">Role</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const ownReason = ownRowReason(u.id, me.id);
                const msg = rowMessageFor(rowMsg, u.id);
                return (
                <tr key={u.id} className="border-b border-line last:border-b-0">
                  <td className="px-2 py-2 font-sans text-xs text-ink-2">{u.username}</td>
                  <td className="px-2 py-2">{u.display_name}</td>
                  <td className="px-2 py-2">
                    <select
                      className="rounded border border-line bg-surface-1 px-2 py-1 text-xs"
                      value={u.role}
                      disabled={ownReason !== null}
                      title={ownReason ?? undefined}
                      onChange={(e) => patchUser(u.id, { role: e.target.value })}
                    >
                      <option value="member">member</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td className="px-2 py-2">
                    {u.is_active ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-positive">
                        Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2">
                        Disabled
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => patchUser(u.id, { is_active: !u.is_active })}
                        disabled={ownReason !== null}
                        title={ownReason ?? undefined}
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
                    {ownReason ? (
                      <p className="mt-1 text-right text-xs text-ink-3">{ownReason}</p>
                    ) : null}
                    {msg ? (
                      <p
                        role={msg.kind === "error" ? "alert" : "status"}
                        className={`mt-1 text-right text-xs ${msg.kind === "error" ? "text-hive-text" : "text-positive"}`}
                      >
                        {msg.text}
                      </p>
                    ) : null}
                  </td>
                </tr>
                );
              })}
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
      className="mt-4 grid grid-cols-1 gap-3 rounded-lg border border-line bg-surface-1 p-4 sm:grid-cols-5"
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
        <p role="alert" className="text-sm text-hive-text sm:col-span-5">
          {error}
        </p>
      ) : null}
    </form>
  );
}
