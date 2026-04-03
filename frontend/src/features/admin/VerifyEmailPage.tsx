import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  applyIdentityPlatformEmailVerificationCode,
  refreshStoredAuthSessionNow,
  sendIdentityPlatformVerificationEmail,
} from "@/lib/auth";
import { presentApiError } from "@/lib/errorUtils";
import { StatusCallout } from "@/components/StatusCallout";

type VerifyEmailPageProps = {
  email?: string | null;
};

export function VerifyEmailPage({ email }: VerifyEmailPageProps) {
  const navigate = useNavigate();
  const postVerificationPath = "/registration";
  const [searchParams] = useSearchParams();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verificationApplied, setVerificationApplied] = useState(false);

  useEffect(() => {
    const mode = searchParams.get("mode");
    const oobCode = searchParams.get("oobCode");
    if (mode !== "verifyEmail" || !oobCode || verificationApplied) {
      return;
    }
    const verificationCode = oobCode;
    let active = true;
    async function applyVerificationCode() {
      setBusy(true);
      setMessage(null);
      setError(null);
      try {
        await applyIdentityPlatformEmailVerificationCode(verificationCode);
        if (!active) return;
        setVerificationApplied(true);
        setMessage("Email verification completed. Refreshing the sign-in session now.");
        await refreshStoredAuthSessionNow();
        if (!active) return;
        navigate(postVerificationPath, { replace: true });
      } catch (applyError) {
        if (!active) return;
        setError(presentApiError(applyError));
      } finally {
        if (active) {
          setBusy(false);
        }
      }
    }
    void applyVerificationCode();
    return () => {
      active = false;
    };
  }, [navigate, postVerificationPath, searchParams, verificationApplied]);

  async function resendVerificationEmail() {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await sendIdentityPlatformVerificationEmail();
      setMessage("Verification email sent. Open the inbox for this account, complete verification, then sign in again.");
    } catch (sendError) {
      setError(presentApiError(sendError));
    } finally {
      setBusy(false);
    }
  }

  async function refreshVerifiedSession() {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await refreshStoredAuthSessionNow();
      setMessage("Verification state refreshed. If the account is verified, you can continue into registration.");
      navigate(postVerificationPath, { replace: true });
    } catch (refreshError) {
      setError(presentApiError(refreshError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Verify your email</h1>
        <p className="mt-1 text-sm text-slate-600">
          This environment only accepts verified email/password identities.
        </p>
      </section>

      <StatusCallout
        title="Email verification required"
        message={
          email
            ? `A verification email is required before ${email} can access this application. Complete verification, then sign in again.`
            : "Complete email verification for this account, then sign in again."
        }
        tone="warning"
      />

      <div className="panel space-y-4 p-5">
        <p className="text-sm text-slate-600">
          If you opened a verification link, this page now applies that code automatically. If you have not received the verification mail yet, resend it from here.
        </p>
        {message ? <p className="text-sm text-emerald-700">{message}</p> : null}
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <div className="flex flex-wrap gap-2">
          <button className="button" disabled={busy} onClick={() => void resendVerificationEmail()} type="button">
            {busy ? "Sending..." : "Resend verification email"}
          </button>
          <button className="button-subtle" disabled={busy} onClick={() => void refreshVerifiedSession()} type="button">
            {busy ? "Checking..." : "I have verified this email"}
          </button>
        </div>
      </div>
    </div>
  );
}
