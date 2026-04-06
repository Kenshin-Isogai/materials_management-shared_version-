import { FormEvent, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Link, useNavigate } from "react-router-dom";
import { apiGet, apiSend } from "@/lib/api";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { StatusCallout } from "@/components/StatusCallout";
import { presentApiError } from "@/lib/errorUtils";
import { shouldPollRegistrationStatus } from "@/lib/registrationStatus";
import type { RegistrationRequest, RegistrationStatus, UserRole } from "@/lib/types";

const REQUESTABLE_ROLES: UserRole[] = ["viewer", "operator", "admin"];

export function RegistrationPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [requestedRole, setRequestedRole] = useState<UserRole>("viewer");
  const [memo, setMemo] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const statusQuery = useSWR("/auth/registration-status", () =>
    apiGet<RegistrationStatus>("/auth/registration-status"),
  );

  const status = statusQuery.data ?? null;
  const latestRequest = status?.request ?? null;
  const canSubmit =
    !status?.current_user &&
    (status?.state === "not_requested" || status?.state === "rejected" || status?.state === "approved");

  useEffect(() => {
    if (status?.current_user) {
      navigate("/", { replace: true });
    }
  }, [navigate, status?.current_user]);

  useEffect(() => {
    if (!shouldPollRegistrationStatus(status)) return;

    const revalidate = () => {
      void statusQuery.mutate();
    };
    const intervalId = window.setInterval(revalidate, 10000);
    window.addEventListener("focus", revalidate);
    window.addEventListener("pageshow", revalidate);
    document.addEventListener("visibilitychange", revalidate);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", revalidate);
      window.removeEventListener("pageshow", revalidate);
      document.removeEventListener("visibilitychange", revalidate);
    };
  }, [status, statusQuery]);

  const title = useMemo(() => {
    switch (status?.state) {
      case "pending":
        return "Registration pending approval";
      case "rejected":
        return "Registration was rejected";
      case "approved":
        return "Registration approved";
      default:
        return "Register for access";
    }
  }, [status?.state]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || !username.trim() || !displayName.trim()) return;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await apiSend<RegistrationRequest>("/auth/register-request", {
        method: "POST",
        body: JSON.stringify({
          username: username.trim(),
          display_name: displayName.trim(),
          requested_role: requestedRole,
          memo: memo.trim() || null,
        }),
      });
      setMessage("Registration request submitted. An admin must approve it before you can use protected pages.");
      setError(null);
      await statusQuery.mutate();
    } catch (submitError) {
      setError(presentApiError(submitError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">{title}</h1>
        <p className="mt-1 text-sm text-slate-600">
          Signed-in identities need admin approval before this application can grant access.
        </p>
      </section>

      {statusQuery.isLoading && <p className="text-sm text-slate-500">Loading registration status...</p>}
      {statusQuery.error ? <ApiErrorNotice area="registration status" error={statusQuery.error} /> : null}
      {!statusQuery.isLoading && statusQuery.error ? (
        <StatusCallout
          title="Sign in or create an account first"
          message="Registration requests require a verified signed-in account. Create an account, verify the email, and sign in from the header before using this page."
          tone="info"
        />
      ) : null}

      {status?.current_user ? (
        <StatusCallout
          title="Access already approved"
          message="This identity is already mapped to an active app user. You can open the main application."
        />
      ) : null}

      {!status?.current_user && status?.state === "pending" && latestRequest ? (
        <StatusCallout
          title="Waiting for admin approval"
          message={`Request submitted as "${latestRequest.username}" on ${latestRequest.created_at}. You cannot use protected pages until an admin approves this request.`}
        />
      ) : null}

      {!status?.current_user && status?.state === "rejected" && latestRequest ? (
        <StatusCallout
          title="Registration was rejected"
          message={`Reason: ${latestRequest.rejection_reason || "No reason recorded."} You can correct the details below and submit a new request.`}
          tone="warning"
        />
      ) : null}

      {!status?.current_user && status?.state === "approved" && latestRequest ? (
        <StatusCallout
          title="Access is currently inactive"
          message="This identity had been approved before, but the mapped app user is not active right now. Submit a new request so an admin can restore access."
          tone="warning"
        />
      ) : null}

      {!status?.current_user && canSubmit && (
        <form className="panel space-y-4 p-5" onSubmit={handleSubmit}>
          <div>
            <h2 className="font-display text-xl font-semibold">Registration request</h2>
            <p className="mt-1 text-sm text-slate-600">
              Email is taken from the signed-in Identity Platform session.
            </p>
            <p className="mt-2 text-sm text-slate-700">
              Signed-in email: <span className="font-semibold">{status?.email || "-"}</span>
            </p>
          </div>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">Username</span>
            <input
              className="input"
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="ren.takeda"
            />
          </label>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">Display name</span>
            <input
              className="input"
              required
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Ren Takeda"
            />
          </label>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">Requested role</span>
            <select
              className="input"
              value={requestedRole}
              onChange={(event) => setRequestedRole(event.target.value as UserRole)}
            >
              {REQUESTABLE_ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-2 text-sm">
            <span className="font-semibold text-slate-700">Memo</span>
            <textarea
              className="input min-h-[96px]"
              value={memo}
              onChange={(event) => setMemo(event.target.value)}
              placeholder="Optional context for the admins reviewing this request."
            />
          </label>

          {message ? <p className="text-sm text-emerald-700">{message}</p> : null}
          {error ? <p className="text-sm text-red-600">{error}</p> : null}

          <button className="button" disabled={busy} type="submit">
            Submit registration request
          </button>
        </form>
      )}

      {status?.current_user ? (
        <div className="flex gap-2">
          <Link className="button" to="/">
            Open dashboard
          </Link>
        </div>
      ) : null}
    </div>
  );
}
