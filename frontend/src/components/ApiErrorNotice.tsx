import { isAuthError, isBackendUnavailableError, presentApiError } from "../lib/errorUtils";
import { StatusCallout } from "./StatusCallout";

type ApiErrorNoticeProps = {
  error: unknown;
  area: string;
  className?: string;
};

export function ApiErrorNotice({ error, area, className }: ApiErrorNoticeProps) {
  const content = isAuthError(error) ? (
    <StatusCallout
      title="Sign-in required"
      message={`Sign in with an allowed account to load ${area}.`}
      tone="error"
    />
  ) : isBackendUnavailableError(error) ? (
    <StatusCallout
      title="Environment unavailable"
      message={`${area} is unavailable because the backend or database is not ready. If this is dev or staging, start Cloud SQL and try again.`}
      tone="warning"
    />
  ) : (
    <p className="text-sm text-red-600">{presentApiError(error)}</p>
  );

  if (!className) return content;
  return <div className={className}>{content}</div>;
}
