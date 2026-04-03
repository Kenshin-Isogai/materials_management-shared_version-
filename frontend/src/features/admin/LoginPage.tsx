import { useEffect, useRef, useState, type FormEvent } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  getStoredAccessTokenOrNull,
  getStoredAuthSessionSnapshot,
  isIdentityPlatformConfigured,
  sendIdentityPlatformVerificationEmail,
  signInWithIdentityPlatformEmailPassword,
  signUpWithIdentityPlatformEmailPassword,
} from "@/lib/auth";
import { setStoredAccessToken } from "@/lib/api";
import { presentApiError } from "@/lib/errorUtils";

export function LoginPage() {
  const navigate = useNavigate();
  const postLoginPath = "/registration";
  const [accessTokenDraft, setAccessTokenDraft] = useState<string>("");
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [signupBusy, setSignupBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [signupError, setSignupError] = useState<string | null>(null);
  const [signupMessage, setSignupMessage] = useState<string | null>(null);
  const [authStatusMessage, setAuthStatusMessage] = useState<string | null>(null);
  const [authFormMode, setAuthFormMode] = useState<"signin" | "signup">("signin");

  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const allowManualTokenEntry =
    !isIdentityPlatformConfigured() ||
    ["localhost", "127.0.0.1"].includes(window.location.hostname);

  const clearAuthFeedback = () => {
    setLoginError(null);
    setSignupError(null);
    setSignupMessage(null);
  };

  /* Redirect away if already signed-in on mount */
  useEffect(() => {
    const token = getStoredAccessTokenOrNull();
    if (token) {
      navigate(postLoginPath, { replace: true });
    }
  }, [navigate, postLoginPath]);

  const handleTokenChange = (nextToken: string) => {
    setStoredAccessToken(nextToken || null);
    setAccessTokenDraft(nextToken);
    clearAuthFeedback();
    setAuthStatusMessage(null);
    if (nextToken.trim()) {
      navigate(postLoginPath, { replace: true });
    }
  };

  const submitIdentityPlatformLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginBusy(true);
    clearAuthFeedback();
    try {
      await signInWithIdentityPlatformEmailPassword(loginEmail, loginPassword);
      if (!mountedRef.current) return;
      setLoginPassword("");
      setAuthStatusMessage("Signed in. Redirecting...");
      navigate(postLoginPath, { replace: true });
    } catch (error) {
      if (!mountedRef.current) return;
      setLoginError(presentApiError(error));
    } finally {
      if (mountedRef.current) setLoginBusy(false);
    }
  };

  const submitIdentityPlatformSignup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSignupBusy(true);
    clearAuthFeedback();
    try {
      await signUpWithIdentityPlatformEmailPassword(loginEmail, loginPassword);
      await sendIdentityPlatformVerificationEmail();
      if (!mountedRef.current) return;
      setAuthStatusMessage("Account created. Verify your email address before continuing.");
      setSignupMessage("Account created. A verification email has been sent.");
      setLoginPassword("");
      navigate(postLoginPath, { replace: true });
    } catch (error) {
      if (!mountedRef.current) return;
      setSignupError(presentApiError(error));
    } finally {
      if (mountedRef.current) setSignupBusy(false);
    }
  };

  const authSession = getStoredAuthSessionSnapshot();

  return (
    <div className="login-page-bg flex min-h-screen items-center justify-center px-4 py-12">
      <div className="login-card w-full max-w-md px-8 py-10">
        {/* ── Branding ── */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 inline-block rounded-xl bg-slatebrand px-4 py-2.5 font-display text-base font-bold tracking-wide text-white">
            Optical Inventory
          </div>
          <h1 className="font-display text-2xl font-bold text-ink">
            {authFormMode === "signin" ? "Welcome back" : "Create your account"}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {authFormMode === "signin"
              ? "Sign in to access inventory management"
              : "Set up a new account to get started"}
          </p>
        </div>

        {/* ── Mode Toggle ── */}
        {isIdentityPlatformConfigured() && (
          <div className="mb-6 flex rounded-xl bg-slate-100 p-1">
            <button
              className={`flex-1 rounded-lg px-3 py-2 text-sm font-semibold transition ${
                authFormMode === "signin"
                  ? "bg-white text-ink shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
              onClick={() => {
                clearAuthFeedback();
                setAuthFormMode("signin");
              }}
              type="button"
            >
              Sign in
            </button>
            <button
              className={`flex-1 rounded-lg px-3 py-2 text-sm font-semibold transition ${
                authFormMode === "signup"
                  ? "bg-white text-ink shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
              onClick={() => {
                clearAuthFeedback();
                setAuthFormMode("signup");
              }}
              type="button"
            >
              Create account
            </button>
          </div>
        )}

        {/* ── Identity Platform Form ── */}
        {isIdentityPlatformConfigured() && (
          <form
            className="space-y-4"
            onSubmit={authFormMode === "signin" ? submitIdentityPlatformLogin : submitIdentityPlatformSignup}
          >
            <label className="block space-y-1.5 text-sm">
              <span className="font-semibold text-slate-700">Email</span>
              <input
                className="input"
                autoComplete="email"
                onChange={(event) => setLoginEmail(event.target.value)}
                placeholder="user@example.com"
                required
                type="email"
                value={loginEmail}
              />
            </label>
            <label className="block space-y-1.5 text-sm">
              <span className="font-semibold text-slate-700">Password</span>
              <input
                className="input"
                autoComplete={authFormMode === "signin" ? "current-password" : "new-password"}
                onChange={(event) => setLoginPassword(event.target.value)}
                placeholder="••••••••"
                required
                type="password"
                value={loginPassword}
              />
            </label>
            <button
              className="button w-full"
              disabled={
                (authFormMode === "signin" ? loginBusy : signupBusy) ||
                !loginEmail.trim() ||
                !loginPassword
              }
              type="submit"
            >
              {authFormMode === "signin"
                ? loginBusy
                  ? "Signing in…"
                  : "Sign in"
                : signupBusy
                  ? "Creating account…"
                  : "Create account"}
            </button>
          </form>
        )}

        {/* ── Manual Token Fallback ── */}
        {allowManualTokenEntry && (
          <div className={isIdentityPlatformConfigured() ? "mt-6 border-t border-slate-100 pt-5" : ""}>
            <label className="block space-y-1.5 text-sm">
              <span className="font-semibold text-slate-700">
                {isIdentityPlatformConfigured() ? "Fallback token" : "Bearer token"}
              </span>
              <input
                className="input"
                onChange={(event) => handleTokenChange(event.target.value)}
                placeholder="Paste local fixture or OIDC bearer token"
                value={accessTokenDraft}
              />
            </label>
          </div>
        )}

        {/* ── Feedback Messages ── */}
        <div className="mt-5 space-y-2">
          {loginError && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{loginError}</p>}
          {signupError && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{signupError}</p>}
          {signupMessage && (
            <p className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{signupMessage}</p>
          )}
          {authStatusMessage && (
            <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">{authStatusMessage}</p>
          )}
          {authSession?.email && (
            <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
              Session: {authSession.email}
              {authSession.emailVerified === false && " (unverified)"}
            </p>
          )}
        </div>

        {/* ── Registration Guidance ── */}
        {isIdentityPlatformConfigured() && (
          <div className="mt-6 rounded-xl bg-slate-50 px-4 py-3 text-center text-xs text-slate-500">
            New users: create an account, verify the email, then sign in.
            <br />
            Registration opens automatically after verification.
            <div className="mt-2">
              <NavLink className="font-semibold text-signal hover:underline" to="/registration">
                Open registration guidance
              </NavLink>
            </div>
          </div>
        )}

        {!isIdentityPlatformConfigured() && (
          <p className="mt-5 text-center text-xs text-slate-500">
            Paste a valid Bearer token to access protected pages.
          </p>
        )}
      </div>
    </div>
  );
}
