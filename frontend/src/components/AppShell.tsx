import { useEffect, useMemo, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { StatusCallout } from "./StatusCallout";
import {
  clearStoredAuthSession,
  getStoredAuthSessionSnapshot,
  getStoredAccessTokenOrNull,
  isIdentityPlatformConfigured,
  sendIdentityPlatformVerificationEmail,
  signInWithIdentityPlatformEmailPassword,
  signUpWithIdentityPlatformEmailPassword,
  subscribeAuthSessionChanged,
} from "../lib/auth";
import {
  apiGet,
  setStoredAccessToken,
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
  const [accessTokenDraft, setAccessTokenDraft] = useState<string>("");
  const [isSignedIn, setIsSignedIn] = useState<boolean>(Boolean(getStoredAccessTokenOrNull()));
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [signupBusy, setSignupBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [signupError, setSignupError] = useState<string | null>(null);
  const [signupMessage, setSignupMessage] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [registrationStatus, setRegistrationStatus] = useState<RegistrationStatus | null>(null);
  const [verificationRequired, setVerificationRequired] = useState(false);
  const [authStatusMessage, setAuthStatusMessage] = useState<string | null>(null);
  const [authVersion, setAuthVersion] = useState(0);
  const [usersVersion, setUsersVersion] = useState(0);
  const [authResolutionBusy, setAuthResolutionBusy] = useState(false);
  const onRegistrationPage = location.pathname === "/registration";
  const onVerifyEmailPage = location.pathname === "/verify-email";
  const [authFormMode, setAuthFormMode] = useState<"signin" | "signup">("signin");

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
    setVerificationRequired(false);
    setIsSignedIn(false);
    setLoginError(null);
    setSignupError(null);
    setSignupMessage(null);
    setAuthStatusMessage("Signed out.");
  };

  const submitIdentityPlatformLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginBusy(true);
    setLoginError(null);
    setSignupMessage(null);
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

  const submitIdentityPlatformSignup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSignupBusy(true);
    setSignupError(null);
    setSignupMessage(null);
    try {
      await signUpWithIdentityPlatformEmailPassword(loginEmail, loginPassword);
      await sendIdentityPlatformVerificationEmail();
      setIsSignedIn(true);
      setVerificationRequired(true);
      setAuthStatusMessage("Account created. Verify your email address before continuing.");
      setSignupMessage("Account created. A verification email has been sent.");
      setLoginPassword("");
    } catch (error) {
      setSignupError(presentApiError(error));
    } finally {
      setSignupBusy(false);
    }
  };

  const resendVerificationEmail = async () => {
    setSignupBusy(true);
    setSignupError(null);
    setSignupMessage(null);
    try {
      await sendIdentityPlatformVerificationEmail();
      setSignupMessage("Verification email sent. Complete verification, then sign in again.");
    } catch (error) {
      setSignupError(presentApiError(error));
    } finally {
      setSignupBusy(false);
    }
  };

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

  const helperMessage = !isSignedIn
    ? isIdentityPlatformConfigured()
      ? "Protected pages require an Identity Platform account that is also mapped to an active app user."
      : "Paste a valid Bearer token to access protected pages."
    : currentUser === null && !authStatusMessage
      ? "Signed-in tokens still need an active app-user mapping before protected pages can load."
      : null;

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
              <div className="grid gap-2">
                <div className="flex gap-2">
                  <button
                    className={authFormMode === "signin" ? "button-subtle" : "rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600"}
                    onClick={() => setAuthFormMode("signin")}
                    type="button"
                  >
                    Sign in
                  </button>
                  <button
                    className={authFormMode === "signup" ? "button-subtle" : "rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600"}
                    onClick={() => setAuthFormMode("signup")}
                    type="button"
                  >
                    Create account
                  </button>
                </div>
                <form className="grid gap-2" onSubmit={authFormMode === "signin" ? submitIdentityPlatformLogin : submitIdentityPlatformSignup}>
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
                    disabled={(authFormMode === "signin" ? loginBusy : signupBusy) || !loginEmail.trim() || !loginPassword}
                    type="submit"
                  >
                    {authFormMode === "signin"
                      ? loginBusy
                        ? "Signing in..."
                        : "Sign in"
                      : signupBusy
                        ? "Creating..."
                        : "Create account"}
                  </button>
                  <span className="text-xs text-slate-500">
                    {authFormMode === "signin"
                      ? "Identity Platform email/password"
                      : "Email/password + verification mail"}
                  </span>
                </div>
                </form>
              </div>
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
                  : authSession?.email
                    ? `Signed in as ${authSession.email}${authSession.emailVerified ? "" : " (unverified)"}`
                    : "Signed in"}
              </div>
            )}
            {loginError ? <p className="text-xs text-red-600">{loginError}</p> : null}
            {signupError ? <p className="text-xs text-red-600">{signupError}</p> : null}
            {signupMessage ? <p className="text-xs text-emerald-700">{signupMessage}</p> : null}
            {isSignedIn && verificationRequired ? (
              <button className="button-subtle" disabled={signupBusy} onClick={() => void resendVerificationEmail()} type="button">
                {signupBusy ? "Sending..." : "Resend verification email"}
              </button>
            ) : null}
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
