import { useState } from "react";
import { sendIdentityPlatformVerificationEmail } from "../lib/auth";
import { presentApiError } from "../lib/errorUtils";
import { StatusCallout } from "../components/StatusCallout";

type VerifyEmailPageProps = {
  email?: string | null;
};

export function VerifyEmailPage({ email }: VerifyEmailPageProps) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
          If you have not received the verification mail yet, resend it from here.
        </p>
        {message ? <p className="text-sm text-emerald-700">{message}</p> : null}
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <button className="button" disabled={busy} onClick={() => void resendVerificationEmail()} type="button">
          {busy ? "Sending..." : "Resend verification email"}
        </button>
      </div>
    </div>
  );
}
