import { Outlet } from "react-router-dom";

/**
 * Minimal full-screen layout for authentication pages
 * (/login, /registration, /verify-email).
 * No sidebar — just the route content.
 */
export function AuthLayout() {
  return <Outlet />;
}
