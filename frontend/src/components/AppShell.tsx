import { useEffect, useMemo, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { StatusCallout } from "./StatusCallout";
import {
  clearStoredAuthSession,
  getStoredAccessTokenOrNull,
  isIdentityPlatformConfigured,
  signInWithIdentityPlatformEmailPassword,
  subscribeAuthSessionChanged,
} from "../lib/auth";
import {
  apiGet,
  setStoredAccessToken,
  subscribeUsersChanged,
} from "../lib/api";
import { isAuthError, presentApiError } from "../lib/errorUtils";
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
  const [accessTokenDraft, setAccessTokenDraft] = useState<string>("");
  const [isSignedIn, setIsSignedIn] = useState<boolean>(Boolean(getStoredAccessTokenOrNull()));
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [registrationStatus, setRegistrationStatus] = useState<RegistrationStatus | null>(null);
  const [authStatusMessage, setAuthStatusMessage] = useState<string | null>(null);
  const [authVersion, setAuthVersion] = useState(0);
  const [usersVersion, setUsersVersion] = useState(0);
  const [authResolutionBusy, setAuthResolutionBusy] = useState(false);
  const onRegistrationPage = location.pathname === "/registration";

  useEffect(() => {
    if (!isSignedIn) {
      setCurrentUser(null);
      setRegistrationStatus(null);
      setAuthResolutionBusy(false);
      return;
    }

    let active = true;
    setAuthResolutionBusy(true);
    apiGet<User>("/users/me")
      .then((user) => {
        if (!active) return;
        setCurrentUser(user);
        setRegistrationStatus({
          state: "approved",
          email: user.email ?? null,
          identity_provider: user.identity_provider ?? null,
          external_subject: user.external_subject ?? null,
          current_user: user,
          request: null,
        });
        setAuthStatusMessage(`Signed in as ${user.display_name} (${user.role}).`);
      })
      .catch((error) => {
        if (!active) return;
        setCurrentUser(null);
        if (!isAuthError(error)) {
          setRegistrationStatus(null);
          setAuthStatusMessage(presentApiError(error));
          return;
        }
        apiGet<RegistrationStatus>("/auth/registration-status")
          .then((status) => {
            if (!active) return;
            setRegistrationStatus(status);
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
              default:
                setAuthStatusMessage("Sign-in succeeded. Complete a registration request to access the app.");
                break;
            }
          })
          .catch((statusError) => {
            if (!active) return;
            setRegistrationStatus(null);
            setAuthStatusMessage(presentApiError(statusError));
          })
          .finally(() => {
            if (active) setAuthResolutionBusy(false);
          });
      })
      .finally(() => {
        if (active) setAuthResolutionBusy(false);
      });
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
      }),
    [],
  );

  const handleTokenChange = (nextToken: string) => {
    setStoredAccessToken(nextToken || null);
    setAccessTokenDraft(nextToken);
    setIsSignedIn(Boolean(nextToken.trim()));
    setLoginError(null);
    setAuthStatusMessage(null);
  };

  const clearToken = () => {
    clearStoredAuthSession();
    setAccessTokenDraft("");
    setLoginEmail("");
    setLoginPassword("");
    setCurrentUser(null);
    setRegistrationStatus(null);
    setIsSignedIn(false);
    setLoginError(null);
    setAuthStatusMessage("Signed out.");
  };

  const submitIdentityPlatformLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginBusy(true);
    setLoginError(null);
    try {
      await signInWithIdentityPlatformEmailPassword(loginEmail, loginPassword);
      setLoginPassword("");
      setAccessTokenDraft("");
      setIsSignedIn(true);
      setAuthStatusMessage("Signed in. Loading your user profile...");
    } catch (error) {
      setLoginError(presentApiError(error));
    } finally {
      setLoginBusy(false);
    }
  };

  useEffect(() => {
    if (!isSignedIn || authResolutionBusy) return;
    if (currentUser && onRegistrationPage) {
      navigate("/", { replace: true });
      return;
    }
    if (!currentUser && registrationStatus && !registrationStatus.current_user && !onRegistrationPage) {
      navigate("/registration", { replace: true });
    }
  }, [authResolutionBusy, currentUser, isSignedIn, navigate, onRegistrationPage, registrationStatus]);

  const helperMessage = !isSignedIn
    ? isIdentityPlatformConfigured()
      ? "Protected pages require an Identity Platform account that is also mapped to an active app user."
      : "Paste a valid Bearer token to access protected pages."
    : currentUser === null && !authStatusMessage
      ? "Signed-in tokens still need an active app-user mapping before protected pages can load."
      : null;

  const visibleNav = useMemo(() => {
    if (!isSignedIn) return nav;
    if (!currentUser) return [{ to: "/registration", label: "Registration" }];
    return nav;
  }, [currentUser, isSignedIn]);

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
          <div className="ml-auto flex min-w-[22rem] flex-col gap-2 rounded-lg bg-white px-3 py-2 text-sm shadow-sm">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-slate-600">Login</span>
              <span className="text-xs text-slate-500">
                {currentUser ? `${currentUser.display_name} (${currentUser.role})` : isSignedIn ? "signed in" : "anonymous"}
              </span>
              {isSignedIn ? (
                <button
                  className="ml-auto rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                  onClick={clearToken}
                  type="button"
                >
                  Sign out
                </button>
              ) : null}
            </div>
            {!isSignedIn && isIdentityPlatformConfigured() ? (
              <form className="grid gap-2" onSubmit={submitIdentityPlatformLogin}>
                <label className="flex items-center gap-2">
                  <span className="w-24 font-semibold text-slate-600">Email</span>
                  <input
                    className="min-w-0 flex-1 rounded-md border border-slate-200 px-2 py-1 text-slate-900 outline-none"
                    autoComplete="email"
                    onChange={(event) => setLoginEmail(event.target.value)}
                    placeholder="user@example.com"
                    required
                    type="email"
                    value={loginEmail}
                  />
                </label>
                <label className="flex items-center gap-2">
                  <span className="w-24 font-semibold text-slate-600">Password</span>
                  <input
                    className="min-w-0 flex-1 rounded-md border border-slate-200 px-2 py-1 text-slate-900 outline-none"
                    autoComplete="current-password"
                    onChange={(event) => setLoginPassword(event.target.value)}
                    placeholder="Identity Platform password"
                    required
                    type="password"
                    value={loginPassword}
                  />
                </label>
                <div className="flex items-center gap-2">
                  <button
                    className="button-subtle"
                    disabled={loginBusy || !loginEmail.trim() || !loginPassword}
                    type="submit"
                  >
                    {loginBusy ? "Signing in..." : "Sign in"}
                  </button>
                  <span className="text-xs text-slate-500">
                    Identity Platform email/password
                  </span>
                </div>
              </form>
            ) : null}
            {!isSignedIn ? (
              <label className="flex items-center gap-2">
                <span className="font-semibold text-slate-600">
                  {isIdentityPlatformConfigured() ? "Fallback token" : "Bearer token"}
                </span>
                <input
                  className="min-w-0 flex-1 bg-transparent text-slate-900 outline-none"
                  onChange={(event) => handleTokenChange(event.target.value)}
                  placeholder="Paste local fixture or OIDC bearer token"
                  value={accessTokenDraft}
                />
              </label>
            ) : (
              <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                {currentUser
                  ? `Signed in as ${currentUser.display_name} (${currentUser.role})`
                  : registrationStatus?.email
                    ? `Signed in as ${registrationStatus.email}`
                    : "Signed in"}
              </div>
            )}
            {loginError ? <p className="text-xs text-red-600">{loginError}</p> : null}
            {authStatusMessage ? <p className="text-xs text-slate-500">{authStatusMessage}</p> : null}
            {!loginError && helperMessage ? <p className="text-xs text-slate-500">{helperMessage}</p> : null}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8">
        {!isSignedIn && (
          <div className="mb-6">
            <StatusCallout
              title="Sign in to use protected pages"
              message={
                isIdentityPlatformConfigured()
                  ? "Use your provisioned email/password above. The account must also be registered as an active app user."
                  : "Set a Bearer token above before opening protected pages."
              }
            />
          </div>
        )}
        <RouteErrorBoundary location={location}>
          <Outlet />
        </RouteErrorBoundary>
      </main>
    </div>
  );
}
