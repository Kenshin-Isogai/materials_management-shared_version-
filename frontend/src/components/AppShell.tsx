import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import {
  clearStoredAuthSession,
  getStoredAuthSessionSnapshot,
  getStoredAccessTokenOrNull,
  isIdentityPlatformConfigured,
  subscribeAuthSessionChanged,
} from "../lib/auth";
import {
  apiGet,
  subscribeUsersChanged,
} from "../lib/api";
import { isAuthError, isEmailVerificationRequiredError, presentApiError } from "../lib/errorUtils";
import type { RegistrationStatus, User } from "../lib/types";

const nav = [
  { to: "/", label: "Dashboard" },
  { to: "/workspace", label: "Workspace" },
  { to: "/search", label: "Search" },
  { to: "/location", label: "Location" },
  { to: "/projects", label: "Projects" },
  { to: "/procurement", label: "Procurement" },
  { to: "/purchase-order-lines", label: "Purchase Orders" },
  { to: "/arrival", label: "Arrival" },
  { to: "/movements", label: "Movements" },
  { to: "/reserve", label: "Reserve" },
  { to: "/bom", label: "BOM" },
  { to: "/items", label: "Items" },
  { to: "/history", label: "History" },
  { to: "/snapshot", label: "Snapshot" },
  { to: "/master", label: "Master" },
  { to: "/users", label: "Users" }
];

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [isSignedIn, setIsSignedIn] = useState<boolean>(Boolean(getStoredAccessTokenOrNull()));
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [registrationStatus, setRegistrationStatus] = useState<RegistrationStatus | null>(null);
  const [verificationRequired, setVerificationRequired] = useState(false);
  const [authStatusMessage, setAuthStatusMessage] = useState<string | null>(null);
  const [authVersion, setAuthVersion] = useState(0);
  const [usersVersion, setUsersVersion] = useState(0);
  const [authResolutionBusy, setAuthResolutionBusy] = useState(false);
  const onRegistrationPage = location.pathname === "/registration";
  const onVerifyEmailPage = location.pathname === "/verify-email";

  useEffect(() => {
    if (!isSignedIn) {
      setCurrentUser(null);
      setRegistrationStatus(null);
      setVerificationRequired(false);
      setAuthResolutionBusy(false);
      return;
    }

    let active = true;
    async function resolveSignedInState() {
      setAuthResolutionBusy(true);
      try {
        const user = await apiGet<User>("/users/me");
        if (!active) return;
        setCurrentUser(user);
        setVerificationRequired(false);
        setRegistrationStatus({
          state: "approved",
          email: user.email ?? null,
          identity_provider: user.identity_provider ?? null,
          external_subject: user.external_subject ?? null,
          current_user: user,
          request: null,
        });
        setAuthStatusMessage(`Signed in as ${user.display_name} (${user.role}).`);
      } catch (error) {
        if (!active) return;
        setCurrentUser(null);
        if (isEmailVerificationRequiredError(error)) {
          setVerificationRequired(true);
          setRegistrationStatus(null);
          setAuthStatusMessage("Verify your email address before accessing this environment.");
          return;
        }
        if (!isAuthError(error)) {
          setRegistrationStatus(null);
          setAuthStatusMessage(presentApiError(error));
          return;
        }
        try {
          const status = await apiGet<RegistrationStatus>("/auth/registration-status");
          if (!active) return;
          setRegistrationStatus(status);
          setVerificationRequired(false);
          if (status.current_user) {
            setCurrentUser(status.current_user);
            setAuthStatusMessage(
              `Signed in as ${status.current_user.display_name} (${status.current_user.role}).`,
            );
            return;
          }
          switch (status.state) {
            case "pending":
              setAuthStatusMessage("Registration is pending admin approval.");
              break;
            case "rejected":
              setAuthStatusMessage("Registration was rejected. Review the reason and resubmit.");
              break;
            case "approved":
              setAuthStatusMessage("This account was approved before, but the mapped app user is inactive.");
              break;
            default:
              setAuthStatusMessage("Sign-in succeeded. Complete a registration request to access the app.");
              break;
          }
        } catch (statusError) {
          if (!active) return;
          if (isEmailVerificationRequiredError(statusError)) {
            setVerificationRequired(true);
            setRegistrationStatus(null);
            setAuthStatusMessage("Verify your email address before accessing this environment.");
            return;
          }
          setRegistrationStatus(null);
          setAuthStatusMessage(presentApiError(statusError));
        }
      } finally {
        if (active) setAuthResolutionBusy(false);
      }
    }
    void resolveSignedInState();
    return () => {
      active = false;
    };
  }, [isSignedIn, authVersion, usersVersion]);

  useEffect(() => subscribeUsersChanged(() => setUsersVersion((value) => value + 1)), []);
  useEffect(
    () =>
      subscribeAuthSessionChanged(() => {
        setIsSignedIn(Boolean(getStoredAccessTokenOrNull()));
        setAuthVersion((value) => value + 1);
        setAuthStatusMessage(null);
        setRegistrationStatus(null);
        setVerificationRequired(false);
      }),
    [],
  );

  const clearToken = () => {
    clearStoredAuthSession();
    setCurrentUser(null);
    setRegistrationStatus(null);
    setVerificationRequired(false);
    setIsSignedIn(false);
    setAuthStatusMessage(null);
  };

  /* ── Redirect unauthenticated users to /login ── */
  /* Exclude /verify-email (handles oobCode action links from fresh browser sessions)
     and /registration (shows guidance for anonymous users). */
  useEffect(() => {
    if (
      !isSignedIn &&
      isIdentityPlatformConfigured() &&
      !onVerifyEmailPage &&
      !onRegistrationPage
    ) {
      navigate("/login", { replace: true });
    }
  }, [isSignedIn, navigate, onVerifyEmailPage, onRegistrationPage]);

  useEffect(() => {
    if (!isSignedIn || authResolutionBusy) return;
    if (currentUser && (onRegistrationPage || onVerifyEmailPage)) {
      navigate("/", { replace: true });
      return;
    }
    if (!currentUser && verificationRequired && !onVerifyEmailPage) {
      navigate("/verify-email", { replace: true });
      return;
    }
    if (!currentUser && registrationStatus && !registrationStatus.current_user && !onRegistrationPage) {
      navigate("/registration", { replace: true });
    }
  }, [
    authResolutionBusy,
    currentUser,
    isSignedIn,
    navigate,
    onRegistrationPage,
    onVerifyEmailPage,
    registrationStatus,
    verificationRequired,
  ]);

  const visibleNav = useMemo(() => {
    if (!isSignedIn) return nav;
    if (verificationRequired) return [{ to: "/verify-email", label: "Verify Email" }];
    if (!currentUser) return [{ to: "/registration", label: "Registration" }];
    return nav;
  }, [currentUser, isSignedIn, verificationRequired]);

  const authSession = getStoredAuthSessionSnapshot();

  return (
    <div className="min-h-screen text-ink">
      <header className="sticky top-0 z-40 border-b border-black/5 bg-canvas/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-4">
          <div className="mr-3 rounded-xl bg-slatebrand px-3 py-2 font-display text-sm font-bold tracking-wide text-white">
            Optical Inventory
          </div>
          {visibleNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm font-semibold transition ${isActive
                  ? "bg-signal text-white"
                  : "text-slate-700 hover:bg-white hover:text-slate-900"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}

          {/* ── Compact Auth Status ── */}
          <div className="ml-auto flex items-center gap-3">
            {isSignedIn ? (
              <>
                <div className="flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm shadow-sm">
                  <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
                  <span className="font-semibold text-slate-700">
                    {currentUser
                      ? currentUser.display_name
                      : authSession?.email
                        ? authSession.email
                        : "Signed in"}
                  </span>
                  {currentUser && (
                    <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-500">
                      {currentUser.role}
                    </span>
                  )}
                  {authSession?.emailVerified === false && (
                    <span className="rounded-md bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-700">
                      unverified
                    </span>
                  )}
                </div>
                <button
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-600 shadow-sm transition hover:bg-slate-50"
                  onClick={clearToken}
                  type="button"
                >
                  Sign out
                </button>
              </>
            ) : (
              <NavLink
                to="/login"
                className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
              >
                Sign in
              </NavLink>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8">
        <RouteErrorBoundary location={location}>
          <Outlet />
        </RouteErrorBoundary>
      </main>
    </div>
  );
}
