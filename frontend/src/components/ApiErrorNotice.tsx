import { isAuthError, isBackendUnavailableError, presentApiError } from "../lib/errorUtils";
import { getStoredAccessTokenOrNull, isIdentityPlatformConfigured } from "../lib/auth";
import { StatusCallout } from "./StatusCallout";

type ApiErrorNoticeProps = {
  error: unknown;
  area: string;
  className?: string;
};

export function ApiErrorNotice({ error, area, className }: ApiErrorNoticeProps) {
  const isAnonymousIdentityPlatform = isIdentityPlatformConfigured() && !getStoredAccessTokenOrNull();
  const content = isAuthError(error) ? (
    <StatusCallout
      title="Sign-in required"
      message={`Sign in with an allowed account to load ${area}.`}
      tone="error"
    />
  ) : isBackendUnavailableError(error) ? (
    <StatusCallout
      title={isAnonymousIdentityPlatform ? "Sign in required" : "Environment unavailable"}
      message={
        isAnonymousIdentityPlatform
          ? `Sign in or create an account before loading ${area}. If you are already signed in and still see this later, the backend or database may be unavailable.`
          : `${area} is unavailable because the backend or database is not ready. If this is dev or staging, start Cloud SQL and try again.`
      }
      tone="warning"
    />
  ) : (
    <p className="text-sm text-red-600">{presentApiError(error)}</p>
  );

  if (!className) return content;
  return <div className={className}>{content}</div>;
}
