import type { RegistrationStatus } from "@/lib/types";

export function shouldPollRegistrationStatus(
  status: RegistrationStatus | null | undefined,
): boolean {
  if (!status || status.current_user) {
    return false;
  }
  return status.state === "pending" || status.state === "approved";
}
