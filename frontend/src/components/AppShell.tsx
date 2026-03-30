import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import {
  apiGet,
  getStoredAccessTokenOrNull,
  setStoredAccessToken,
  subscribeUsersChanged,
} from "../lib/api";
import type { User } from "../lib/types";

const GOOGLE_CLIENT_ID = (import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "").trim();

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
  const [accessToken, setAccessTokenState] = useState<string>(getStoredAccessTokenOrNull() ?? "");
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [googleStatus, setGoogleStatus] = useState<"hidden" | "loading" | "ready" | "error">(
    GOOGLE_CLIENT_ID ? "loading" : "hidden",
  );
  const [usersVersion, setUsersVersion] = useState(0);

  useEffect(() => {
    let active = true;
    if (!accessToken) {
      setCurrentUser(null);
      return () => {
        active = false;
      };
    }
    apiGet<User>("/users/me")
      .then((user) => {
        if (!active) return;
        setCurrentUser(user);
      })
      .catch(() => {
        if (active) {
          setCurrentUser(null);
        }
      });
    return () => {
      active = false;
    };
  }, [accessToken, usersVersion]);

  useEffect(() => subscribeUsersChanged(() => setUsersVersion((value) => value + 1)), []);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) {
      setGoogleStatus("hidden");
      return;
    }
    let active = true;
    const buttonContainer = document.getElementById("google-signin-button");
    if (!buttonContainer) return;

    const renderGoogleButton = () => {
      if (!active || !window.google?.accounts?.id || !buttonContainer) return;
      buttonContainer.innerHTML = "";
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (response) => {
          if (!response.credential) return;
          setStoredAccessToken(response.credential);
          setAccessTokenState(response.credential);
        },
      });
      window.google.accounts.id.renderButton(buttonContainer, {
        theme: "outline",
        size: "medium",
        shape: "pill",
        text: "signin_with",
        width: 240,
      });
      setGoogleStatus("ready");
    };

    if (window.google?.accounts?.id) {
      renderGoogleButton();
      return () => {
        active = false;
      };
    }

    const existingScript = document.querySelector<HTMLScriptElement>(
      'script[data-google-identity-script="true"]',
    );
    const script =
      existingScript ??
      Object.assign(document.createElement("script"), {
        src: "https://accounts.google.com/gsi/client",
        async: true,
        defer: true,
      });

    script.dataset.googleIdentityScript = "true";
    const handleScriptError = () => {
      if (active) setGoogleStatus("error");
    };
    script.addEventListener("load", renderGoogleButton);
    script.addEventListener("error", handleScriptError);
    if (!existingScript) {
      document.head.appendChild(script);
    }
    return () => {
      active = false;
      script.removeEventListener("load", renderGoogleButton);
      script.removeEventListener("error", handleScriptError);
    };
  }, []);

  const handleTokenChange = (nextToken: string) => {
    setStoredAccessToken(nextToken || null);
    setAccessTokenState(nextToken);
  };

  const clearToken = () => {
    setStoredAccessToken(null);
    setAccessTokenState("");
    setCurrentUser(null);
  };

  return (
    <div className="min-h-screen text-ink">
      <header className="sticky top-0 z-40 border-b border-black/5 bg-canvas/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-4">
          <div className="mr-3 rounded-xl bg-slatebrand px-3 py-2 font-display text-sm font-bold tracking-wide text-white">
            Optical Inventory
          </div>
          {nav.map((item) => (
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
                {currentUser ? `${currentUser.display_name} (${currentUser.role})` : "anonymous"}
              </span>
              {accessToken ? (
                <button
                  className="ml-auto rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                  onClick={clearToken}
                  type="button"
                >
                  Sign out
                </button>
              ) : null}
            </div>
            {GOOGLE_CLIENT_ID ? (
              <div className="flex items-center gap-3">
                <div id="google-signin-button" />
                <span className="text-xs text-slate-500">
                  {googleStatus === "loading" ? "Loading Google sign-in..." : null}
                  {googleStatus === "error" ? "Google sign-in could not be loaded." : null}
                  {googleStatus === "ready" ? "Google Identity active" : null}
                </span>
              </div>
            ) : null}
            <label className="flex items-center gap-2">
              <span className="font-semibold text-slate-600">
                {GOOGLE_CLIENT_ID ? "Fallback token" : "Bearer token"}
              </span>
              <input
                className="min-w-0 flex-1 bg-transparent text-slate-900 outline-none"
                onChange={(event) => handleTokenChange(event.target.value)}
                placeholder="Paste local fixture or OIDC bearer token"
                value={accessToken}
              />
            </label>
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
