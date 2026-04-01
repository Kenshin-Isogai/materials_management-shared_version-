import { ApiClientError } from "./types";

export function asApiClientError(error: unknown): ApiClientError {
  if (error instanceof ApiClientError) return error;
  if (error instanceof Error) return new ApiClientError({ message: error.message });
  return new ApiClientError({ message: String(error) });
}

export function isAuthError(error: unknown): boolean {
  const apiError = asApiClientError(error);
  return (
    apiError.statusCode === 401 ||
    apiError.statusCode === 403 ||
    apiError.code === "AUTH_REQUIRED" ||
    apiError.code === "USER_REQUIRED" ||
    apiError.code === "USER_NOT_FOUND" ||
    apiError.code === "FORBIDDEN" ||
    apiError.code === "INVALID_TOKEN"
  );
}

export function isEmailVerificationRequiredError(error: unknown): boolean {
  const apiError = asApiClientError(error);
  return (
    apiError.code === "EMAIL_VERIFICATION_REQUIRED" ||
    (apiError.code === "INVALID_TOKEN" &&
      apiError.message.includes("Verified email claim is required"))
  );
}

export function isBackendUnavailableError(error: unknown): boolean {
  const apiError = asApiClientError(error);
  return (
    apiError.isNetworkError ||
    apiError.statusCode === 502 ||
    apiError.statusCode === 503 ||
    apiError.statusCode === 504 ||
    apiError.code === "NOT_READY"
  );
}

export function presentApiError(error: unknown): string {
  const apiError = asApiClientError(error);
  if (isEmailVerificationRequiredError(apiError)) {
    return "Verify your email address before signing in to this application.";
  }
  if (isAuthError(apiError)) {
    return "Sign in with an allowed account to continue.";
  }
  if (isBackendUnavailableError(apiError)) {
    return "The backend is unavailable right now. If this is dev or staging, verify that Cloud SQL is running and try again.";
  }
  return apiError.message || "Request failed.";
}
