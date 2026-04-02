import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { apiGet, apiSend, notifyUsersChanged } from "../lib/api";
import { presentApiError } from "../lib/errorUtils";
import type { RegistrationRequest, User, UserRole } from "../lib/types";

const USER_ROLES: UserRole[] = ["admin", "operator", "viewer"];

type UserDraft = {
  display_name: string;
  role: UserRole;
  is_active: boolean;
};

type ApprovalDraft = {
  username: string;
  display_name: string;
  role: UserRole;
  rejection_reason: string;
};

function makeApprovalDraft(request: RegistrationRequest): ApprovalDraft {
  return {
    username: request.username,
    display_name: request.display_name,
    role: request.requested_role || "viewer",
    rejection_reason: "",
  };
}

export function UsersPage() {
  const currentUserQuery = useSWR("/users/me", () => apiGet<User>("/users/me"));
  const [showResolvedRequests, setShowResolvedRequests] = useState(false);
  const registrationRequestsPath = `/registration-requests?include_resolved=${showResolvedRequests ? "true" : "false"}`;
  const usersQuery = useSWR("/users?include_inactive=true", () =>
    apiGet<User[]>("/users?include_inactive=true"),
  );
  const registrationRequestsQuery = useSWR(registrationRequestsPath, () =>
    apiGet<RegistrationRequest[]>(registrationRequestsPath),
  );
  const [createForm, setCreateForm] = useState({
    username: "",
    display_name: "",
    email: "",
    external_subject: "",
    role: "operator" as UserRole,
    is_active: true,
  });
  const [showAdvancedIdentityMapping, setShowAdvancedIdentityMapping] = useState(false);
  const [editingUserId, setEditingUserId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<UserDraft | null>(null);
  const [approvalDrafts, setApprovalDrafts] = useState<Record<number, ApprovalDraft>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const users = usersQuery.data ?? [];
  const registrationRequests = registrationRequestsQuery.data ?? [];
  const canViewIdentityInternals = currentUserQuery.data?.role === "admin";
  const pendingRequests = registrationRequests.filter((request) => request.status === "pending");
  const hasActiveUsers = users.some((user) => user.is_active);
  const summary = useMemo(
    () =>
      usersQuery.data
        ? {
            total: users.length,
            active: users.filter((user) => user.is_active).length,
            inactive: users.filter((user) => !user.is_active).length,
            pending: registrationRequestsQuery.data ? pendingRequests.length : null,
          }
        : {
            total: null,
            active: null,
            inactive: null,
            pending: registrationRequestsQuery.data ? pendingRequests.length : null,
          },
    [pendingRequests.length, registrationRequestsQuery.data, users, usersQuery.data],
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

  function getApprovalDraft(request: RegistrationRequest): ApprovalDraft {
    return approvalDrafts[request.request_id] ?? makeApprovalDraft(request);
  }

  function setApprovalDraft(request: RegistrationRequest, updater: (draft: ApprovalDraft) => ApprovalDraft) {
    setApprovalDrafts((current) => ({
      ...current,
      [request.request_id]: updater(current[request.request_id] ?? makeApprovalDraft(request)),
    }));
  }

  async function reloadAll(successMessage?: string) {
    const results = await Promise.allSettled([usersQuery.mutate(), registrationRequestsQuery.mutate()]);
    notifyUsersChanged();
    if (successMessage) {
      setMessage(successMessage);
    }
    const refreshFailure = results.find((result) => result.status === "rejected");
    if (refreshFailure?.status === "rejected") {
      setError("The change was saved, but one of the follow-up refreshes failed. Refresh the page and verify the latest state.");
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
              ? "identity_platform"
              : null,
            hosted_domain: null,
            role: createForm.role,
            is_active: createForm.is_active,
          }),
        },
        {
          allowAnonymousMutation: !hasActiveUsers,
        },
      );
      setCreateForm({
        username: "",
        display_name: "",
        email: "",
        external_subject: "",
        role: "operator",
        is_active: true,
      });
      await reloadAll("User created.");
    } catch (err) {
      setError(presentApiError(err));
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
      await reloadAll("User updated.");
    } catch (err) {
      setError(presentApiError(err));
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
      await reloadAll(`User "${user.display_name}" deactivated.`);
    } catch (err) {
      setError(presentApiError(err));
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
      await reloadAll(
        isActive ? `User "${user.display_name}" reactivated.` : `User "${user.display_name}" deactivated.`,
      );
    } catch (err) {
      setError(presentApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleApprove(request: RegistrationRequest) {
    const draft = getApprovalDraft(request);
    if (!draft.username.trim() || !draft.display_name.trim()) return;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await apiSend(`/registration-requests/${request.request_id}/approve`, {
        method: "POST",
        body: JSON.stringify({
          username: draft.username.trim(),
          display_name: draft.display_name.trim(),
          role: draft.role,
        }),
      });
      setApprovalDrafts((current) => {
        const next = { ...current };
        delete next[request.request_id];
        return next;
      });
      await reloadAll(`Approved registration for "${request.email}".`);
    } catch (err) {
      setError(presentApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleReject(request: RegistrationRequest) {
    const draft = getApprovalDraft(request);
    if (!draft.rejection_reason.trim()) {
      setError("Rejection reason is required.");
      return;
    }
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await apiSend(`/registration-requests/${request.request_id}/reject`, {
        method: "POST",
        body: JSON.stringify({
          rejection_reason: draft.rejection_reason.trim(),
        }),
      });
      setApprovalDrafts((current) => {
        const next = { ...current };
        delete next[request.request_id];
        return next;
      });
      await reloadAll(`Rejected registration for "${request.email}".`);
    } catch (err) {
      setError(presentApiError(err));
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
            Create manual recovery users and review self-registration requests.
          </p>
        </div>
        <div className="flex gap-3 text-sm">
          <div className="panel min-w-28 px-4 py-3">
            <div className="text-slate-500">Total</div>
            <div className="font-display text-2xl font-bold">{summary.total ?? "—"}</div>
          </div>
          <div className="panel min-w-28 px-4 py-3">
            <div className="text-slate-500">Active</div>
            <div className="font-display text-2xl font-bold text-emerald-700">{summary.active ?? "—"}</div>
          </div>
          <div className="panel min-w-28 px-4 py-3">
            <div className="text-slate-500">Inactive</div>
            <div className="font-display text-2xl font-bold text-slate-500">{summary.inactive ?? "—"}</div>
          </div>
          <div className="panel min-w-28 px-4 py-3">
            <div className="text-slate-500">Pending</div>
            <div className="font-display text-2xl font-bold text-amber-700">{summary.pending ?? "—"}</div>
          </div>
        </div>
      </section>

      {message ? <div className="rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</div> : null}
      {error ? <div className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div> : null}
      {registrationRequestsQuery.error ? <ApiErrorNotice area="registration requests" error={registrationRequestsQuery.error} /> : null}
      {usersQuery.error ? <ApiErrorNotice area="users" error={usersQuery.error} /> : null}

      <section className="panel space-y-4 p-5">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="font-display text-xl font-semibold">Pending registrations</h2>
            <p className="mt-1 text-sm text-slate-600">
              New sign-ins land here until an admin approves or rejects the request.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input
                checked={showResolvedRequests}
                onChange={(event) => setShowResolvedRequests(event.target.checked)}
                type="checkbox"
              />
              <span>Show resolved history</span>
            </label>
            <button
              className="button-subtle"
              disabled={busy || registrationRequestsQuery.isLoading}
              onClick={() => {
                setMessage(null);
                setError(null);
                void registrationRequestsQuery.mutate();
              }}
              type="button"
            >
              Refresh
            </button>
          </div>
        </div>

        {!registrationRequests.length && !registrationRequestsQuery.isLoading ? (
          <div className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-500">
            No registration requests yet.
          </div>
        ) : null}

        <div className="space-y-4">
          {registrationRequests.map((request) => {
            const draft = getApprovalDraft(request);
            const resolved = request.status !== "pending";
            return (
              <article
                key={request.request_id}
                className={`rounded-2xl border px-4 py-4 ${
                  request.status === "pending"
                    ? "border-amber-200 bg-amber-50/70"
                    : request.status === "rejected"
                      ? "border-rose-200 bg-rose-50/70"
                      : "border-emerald-200 bg-emerald-50/70"
                }`}
              >
                <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-display text-lg font-semibold">{request.display_name}</span>
                      <span
                        className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${
                          request.status === "pending"
                            ? "bg-amber-200 text-amber-900"
                            : request.status === "rejected"
                              ? "bg-rose-200 text-rose-900"
                              : "bg-emerald-200 text-emerald-900"
                        }`}
                      >
                        {request.status}
                      </span>
                    </div>
                    <div className="text-sm text-slate-700">
                      <span className="font-semibold">Email:</span> {request.email}
                    </div>
                    <div className="text-sm text-slate-700">
                      <span className="font-semibold">Requested username:</span> {request.username}
                    </div>
                    <div className="text-sm text-slate-700">
                      <span className="font-semibold">Requested role:</span> {request.requested_role}
                    </div>
                    <div className="text-sm text-slate-700">
                      <span className="font-semibold">Submitted:</span> {request.created_at}
                    </div>
                    {request.memo ? (
                      <div className="rounded-lg bg-white/80 px-3 py-2 text-sm text-slate-700">
                        <span className="font-semibold">Memo:</span> {request.memo}
                      </div>
                    ) : null}
                    {canViewIdentityInternals && (request.identity_provider || request.external_subject) ? (
                      <div className="rounded-lg bg-white/80 px-3 py-2 text-xs text-slate-600">
                        <div className="font-semibold text-slate-700">Identity mapping</div>
                        <div>provider: {request.identity_provider || "-"}</div>
                        <div className="break-all">sub: {request.external_subject || "-"}</div>
                      </div>
                    ) : null}
                    {resolved ? (
                      <div className="text-xs text-slate-600">
                        Reviewed at {request.reviewed_at || "-"} by {request.reviewed_by_username || "-"}
                        {request.rejection_reason ? ` | Reason: ${request.rejection_reason}` : ""}
                      </div>
                    ) : null}
                  </div>

                  {request.status === "pending" ? (
                    <div className="grid min-w-[18rem] gap-3 rounded-xl bg-white/90 p-3 shadow-sm">
                      <label className="block space-y-1 text-sm">
                        <span className="font-semibold text-slate-700">Approved username</span>
                        <input
                          className="input"
                          value={draft.username}
                          onChange={(event) =>
                            setApprovalDraft(request, (current) => ({
                              ...current,
                              username: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <label className="block space-y-1 text-sm">
                        <span className="font-semibold text-slate-700">Approved display name</span>
                        <input
                          className="input"
                          value={draft.display_name}
                          onChange={(event) =>
                            setApprovalDraft(request, (current) => ({
                              ...current,
                              display_name: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <label className="block space-y-1 text-sm">
                        <span className="font-semibold text-slate-700">Approved role</span>
                        <select
                          className="input"
                          value={draft.role}
                          onChange={(event) =>
                            setApprovalDraft(request, (current) => ({
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
                      <label className="block space-y-1 text-sm">
                        <span className="font-semibold text-slate-700">Rejection reason</span>
                        <textarea
                          className="input min-h-[88px]"
                          value={draft.rejection_reason}
                          onChange={(event) =>
                            setApprovalDraft(request, (current) => ({
                              ...current,
                              rejection_reason: event.target.value,
                            }))
                          }
                          placeholder="Required if you reject this request."
                        />
                      </label>
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="button"
                          disabled={busy || !draft.username.trim() || !draft.display_name.trim()}
                          onClick={() => void handleApprove(request)}
                          type="button"
                        >
                          Approve
                        </button>
                        <button
                          className="button-subtle"
                          disabled={busy || !draft.rejection_reason.trim()}
                          onClick={() => void handleReject(request)}
                          type="button"
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[22rem,1fr]">
        <form className="panel space-y-4 p-5" onSubmit={handleCreate}>
          <div>
            <h2 className="font-display text-xl font-semibold">Create User</h2>
            <p className="mt-1 text-sm text-slate-600">
              Keep manual user creation as a recovery path for the first admin or incident handling. Standard users should onboard through self-registration.
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

          <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm">
            <label className="flex items-center gap-2">
              <input
                checked={showAdvancedIdentityMapping}
                onChange={(event) => setShowAdvancedIdentityMapping(event.target.checked)}
                type="checkbox"
              />
              <span className="font-semibold text-slate-700">Advanced identity mapping</span>
            </label>
            <p className="mt-1 text-xs text-slate-500">
              Normally email matching is enough. Use external subject only for recovery or stricter identity pinning.
            </p>
          </div>

          {showAdvancedIdentityMapping ? (
            <label className="block space-y-2 text-sm">
              <span className="font-semibold text-slate-700">External subject</span>
              <input
                className="input"
                value={createForm.external_subject}
                onChange={(event) =>
                  setCreateForm((current) => ({ ...current, external_subject: event.target.value }))
                }
                placeholder="identity-platform-subject"
              />
            </label>
          ) : null}

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
                Active users keep their identity mapping and stay visible here for review or reactivation.
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

          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="px-3 py-2">Username</th>
                  <th className="px-3 py-2">Display name</th>
                  <th className="px-3 py-2">Email</th>
                  <th className="px-3 py-2">Identity</th>
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
                                current ? { ...current, display_name: event.target.value } : current,
                              )
                            }
                          />
                        ) : (
                          <span>{user.display_name}</span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-slate-600">{user.email || "-"}</td>
                      <td className="px-3 py-3 text-xs text-slate-600">
                        {user.external_subject ? (
                          <div className="space-y-1">
                            <div className="font-semibold text-slate-700">Email + subject linked</div>
                            {canViewIdentityInternals ? (
                              <div className="font-mono break-all">{user.external_subject}</div>
                            ) : null}
                          </div>
                        ) : user.email ? (
                          <span>Email-only</span>
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
                                current ? { ...current, role: event.target.value as UserRole } : current,
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
                                  current ? { ...current, is_active: event.target.checked } : current,
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
