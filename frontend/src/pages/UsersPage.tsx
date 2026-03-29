import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";
import { apiGet, apiSend, notifyUsersChanged } from "../lib/api";
import type { User, UserRole } from "../lib/types";

const USER_ROLES: UserRole[] = ["admin", "operator", "viewer"];

type UserDraft = {
  display_name: string;
  role: UserRole;
  is_active: boolean;
};

export function UsersPage() {
  const usersQuery = useSWR("/users?include_inactive=true", () =>
    apiGet<User[]>("/users?include_inactive=true")
  );
  const [createForm, setCreateForm] = useState({
    username: "",
    display_name: "",
    email: "",
    external_subject: "",
    identity_provider: "test-oidc",
    hosted_domain: "",
    role: "operator" as UserRole,
    is_active: true,
  });
  const [editingUserId, setEditingUserId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<UserDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const users = usersQuery.data ?? [];
  const hasActiveUsers = users.some((user) => user.is_active);
  const summary = useMemo(
    () => ({
      total: users.length,
      active: users.filter((user) => user.is_active).length,
      inactive: users.filter((user) => !user.is_active).length,
    }),
    [users]
  );

  function beginEdit(user: User) {
    setEditingUserId(user.user_id);
    setEditDraft({
      display_name: user.display_name,
      role: user.role,
      is_active: user.is_active,
    });
    setMessage(null);
    setError(null);
  }

  function resetEdit() {
    setEditingUserId(null);
    setEditDraft(null);
  }

  async function reloadUsers(successMessage?: string) {
    await usersQuery.mutate();
    notifyUsersChanged();
    if (successMessage) {
      setMessage(successMessage);
    }
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!createForm.username.trim() || !createForm.display_name.trim()) return;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await apiSend(
        "/users",
        {
          method: "POST",
          body: JSON.stringify({
            username: createForm.username.trim(),
            display_name: createForm.display_name.trim(),
            email: createForm.email.trim() || null,
            external_subject: createForm.external_subject.trim() || null,
            identity_provider: createForm.external_subject.trim()
              ? createForm.identity_provider.trim() || null
              : null,
            hosted_domain: createForm.hosted_domain.trim() || null,
            role: createForm.role,
            is_active: createForm.is_active,
          }),
        },
        {
          allowAnonymousMutation: !hasActiveUsers,
        }
      );
      setCreateForm({
        username: "",
        display_name: "",
        email: "",
        external_subject: "",
        identity_provider: "test-oidc",
        hosted_domain: "",
        role: "operator",
        is_active: true,
      });
      await reloadUsers("User created.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSave(userId: number) {
    if (!editDraft) return;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await apiSend(`/users/${userId}`, {
        method: "PUT",
        body: JSON.stringify({
          display_name: editDraft.display_name.trim(),
          role: editDraft.role,
          is_active: editDraft.is_active,
        }),
      });
      resetEdit();
      await reloadUsers("User updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update user.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeactivate(user: User) {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await apiSend(`/users/${user.user_id}`, {
        method: "DELETE",
        body: JSON.stringify({}),
      });
      if (editingUserId === user.user_id) {
        resetEdit();
      }
      await reloadUsers(`User "${user.display_name}" deactivated.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to deactivate user.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSetActive(user: User, isActive: boolean) {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await apiSend(`/users/${user.user_id}`, {
        method: "PUT",
        body: JSON.stringify({
          display_name: user.display_name,
          role: user.role,
          is_active: isActive,
        }),
      });
      if (editingUserId === user.user_id) {
        resetEdit();
      }
      await reloadUsers(
        isActive ? `User "${user.display_name}" reactivated.` : `User "${user.display_name}" deactivated.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update user status.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-display text-3xl font-bold">Users</h1>
          <p className="mt-1 text-sm text-slate-600">
            Create, update, activate, and deactivate browser users for shared-server operation.
          </p>
        </div>
        <div className="flex gap-3 text-sm">
          <div className="panel min-w-28 px-4 py-3">
            <div className="text-slate-500">Total</div>
            <div className="font-display text-2xl font-bold">{summary.total}</div>
          </div>
          <div className="panel min-w-28 px-4 py-3">
            <div className="text-slate-500">Active</div>
            <div className="font-display text-2xl font-bold text-emerald-700">{summary.active}</div>
          </div>
          <div className="panel min-w-28 px-4 py-3">
            <div className="text-slate-500">Inactive</div>
            <div className="font-display text-2xl font-bold text-slate-500">{summary.inactive}</div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[22rem,1fr]">
        <form className="panel space-y-4 p-5" onSubmit={handleCreate}>
          <div>
            <h2 className="font-display text-xl font-semibold">Create User</h2>
            <p className="mt-1 text-sm text-slate-600">
              Map app users to OIDC claims so Bearer tokens resolve cleanly in the browser and on Cloud Run.
            </p>
            {!hasActiveUsers ? (
              <p className="mt-2 text-sm text-amber-700">
                No active user exists yet. Creating the first active user is allowed without a Bearer token bootstrap.
              </p>
            ) : null}
          </div>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">Username</span>
            <input
              className="input"
              value={createForm.username}
              onChange={(event) =>
                setCreateForm((current) => ({ ...current, username: event.target.value }))
              }
              placeholder="shared.operator"
              required
            />
          </label>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">Display name</span>
            <input
              className="input"
              value={createForm.display_name}
              onChange={(event) =>
                setCreateForm((current) => ({ ...current, display_name: event.target.value }))
              }
              placeholder="Shared Operator"
              required
            />
          </label>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">Email</span>
            <input
              className="input"
              value={createForm.email}
              onChange={(event) =>
                setCreateForm((current) => ({ ...current, email: event.target.value }))
              }
              placeholder="operator@example.com"
            />
          </label>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">Identity provider</span>
            <input
              className="input"
              value={createForm.identity_provider}
              onChange={(event) =>
                setCreateForm((current) => ({ ...current, identity_provider: event.target.value }))
              }
              placeholder="google"
            />
          </label>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">External subject</span>
            <input
              className="input"
              value={createForm.external_subject}
              onChange={(event) =>
                setCreateForm((current) => ({ ...current, external_subject: event.target.value }))
              }
              placeholder="google-oauth2|1234567890"
            />
          </label>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">Hosted domain</span>
            <input
              className="input"
              value={createForm.hosted_domain}
              onChange={(event) =>
                setCreateForm((current) => ({ ...current, hosted_domain: event.target.value }))
              }
              placeholder="example.com"
            />
          </label>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">Role</span>
            <select
              className="input"
              value={createForm.role}
              onChange={(event) =>
                setCreateForm((current) => ({
                  ...current,
                  role: event.target.value as UserRole,
                }))
              }
            >
              {USER_ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm">
            <input
              checked={createForm.is_active}
              onChange={(event) =>
                setCreateForm((current) => ({ ...current, is_active: event.target.checked }))
              }
              type="checkbox"
            />
            <span>Active immediately</span>
          </label>

          <button className="button w-full" disabled={busy} type="submit">
            Create User
          </button>
        </form>

        <section className="panel space-y-4 p-5">
          <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div>
              <h2 className="font-display text-xl font-semibold">User Directory</h2>
              <p className="mt-1 text-sm text-slate-600">
                 Active users keep their OIDC mapping and stay visible here for review or reactivation.
               </p>
            </div>
            <button
              className="button-subtle"
              disabled={busy || usersQuery.isLoading}
              onClick={() => {
                setMessage(null);
                setError(null);
                void usersQuery.mutate();
                notifyUsersChanged();
              }}
              type="button"
            >
              Refresh
            </button>
          </div>

          {message ? <div className="rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</div> : null}
          {error ? <div className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div> : null}
          {usersQuery.error ? (
            <div className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800">
              {usersQuery.error instanceof Error ? usersQuery.error.message : "Failed to load users."}
            </div>
          ) : null}

          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="px-3 py-2">Username</th>
                  <th className="px-3 py-2">Display name</th>
                  <th className="px-3 py-2">Email</th>
                  <th className="px-3 py-2">OIDC mapping</th>
                  <th className="px-3 py-2">Role</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Updated</th>
                  <th className="px-3 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => {
                  const isEditing = editingUserId === user.user_id && editDraft !== null;
                  return (
                    <tr key={user.user_id} className="border-t border-slate-100 align-top">
                      <td className="px-3 py-3 font-mono text-xs text-slate-700">{user.username}</td>
                      <td className="px-3 py-3">
                        {isEditing ? (
                          <input
                            className="input"
                            value={editDraft.display_name}
                            onChange={(event) =>
                              setEditDraft((current) =>
                                current ? { ...current, display_name: event.target.value } : current
                              )
                            }
                          />
                        ) : (
                          <span>{user.display_name}</span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-slate-600">{user.email || "-"}</td>
                      <td className="px-3 py-3 text-xs text-slate-600">
                        {user.identity_provider && user.external_subject ? (
                          <div className="space-y-1">
                            <div className="font-mono">{user.identity_provider}</div>
                            <div className="font-mono">{user.external_subject}</div>
                            <div>{user.hosted_domain || "-"}</div>
                          </div>
                        ) : (
                          <span>-</span>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        {isEditing ? (
                          <select
                            className="input"
                            value={editDraft.role}
                            onChange={(event) =>
                              setEditDraft((current) =>
                                current ? { ...current, role: event.target.value as UserRole } : current
                              )
                            }
                          >
                            {USER_ROLES.map((role) => (
                              <option key={role} value={role}>
                                {role}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="capitalize">{user.role}</span>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        {isEditing ? (
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              checked={editDraft.is_active}
                              onChange={(event) =>
                                setEditDraft((current) =>
                                  current ? { ...current, is_active: event.target.checked } : current
                                )
                              }
                              type="checkbox"
                            />
                            <span>{editDraft.is_active ? "Active" : "Inactive"}</span>
                          </label>
                        ) : (
                          <span
                            className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${
                              user.is_active
                                ? "bg-emerald-100 text-emerald-800"
                                : "bg-slate-200 text-slate-700"
                            }`}
                          >
                            {user.is_active ? "Active" : "Inactive"}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-slate-600">{user.updated_at.slice(0, 10)}</td>
                      <td className="px-3 py-3">
                        <div className="flex flex-wrap gap-2">
                          {isEditing ? (
                            <>
                              <button
                                className="button"
                                disabled={busy || !editDraft.display_name.trim()}
                                onClick={() => void handleSave(user.user_id)}
                                type="button"
                              >
                                Save
                              </button>
                              <button className="button-subtle" disabled={busy} onClick={resetEdit} type="button">
                                Cancel
                              </button>
                            </>
                          ) : (
                            <>
                              <button className="button-subtle" disabled={busy} onClick={() => beginEdit(user)} type="button">
                                Edit
                              </button>
                              {user.is_active ? (
                                <button
                                  className="button-subtle"
                                  disabled={busy}
                                  onClick={() => void handleDeactivate(user)}
                                  type="button"
                                >
                                  Deactivate
                                </button>
                              ) : (
                                <button
                                  className="button-subtle"
                                  disabled={busy}
                                  onClick={() => void handleSetActive(user, true)}
                                  type="button"
                                >
                                  Reactivate
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </div>
  );
}
