import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  FolderKanban,
  ShoppingCart,
  Layers,
  Package,
  MapPin,
  Camera,
  ArrowLeftRight,
  Lock,
  FileText,
  Truck,
  Database,
  Users,
  History,
  LogOut,
  LogIn,
} from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
} from "@/components/ui/breadcrumb";
import { Separator } from "@/components/ui/separator";
import { RouteErrorBoundary } from "@/components/RouteErrorBoundary";

import {
  clearStoredAuthSession,
  getStoredAuthSessionSnapshot,
  getStoredAccessTokenOrNull,
  isIdentityPlatformConfigured,
  subscribeAuthSessionChanged,
} from "@/lib/auth";
import { apiGet, subscribeUsersChanged } from "@/lib/api";
import {
  isAuthError,
  isEmailVerificationRequiredError,
  presentApiError,
} from "@/lib/errorUtils";
import type { RegistrationStatus, User } from "@/lib/types";

/* ------------------------------------------------------------------ */
/*  Navigation definitions                                            */
/* ------------------------------------------------------------------ */

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

type NavGroup = {
  label: string;
  items: NavItem[];
};

const navGroups: NavGroup[] = [
  {
    label: "Planning",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard },
      { to: "/projects", label: "Projects", icon: FolderKanban },
      { to: "/procurement", label: "Procurement", icon: ShoppingCart },
      { to: "/bom", label: "BOM Analysis", icon: Layers },
    ],
  },
  {
    label: "Inventory",
    items: [
      { to: "/items", label: "Items", icon: Package },
      { to: "/locations", label: "Locations", icon: MapPin },
      { to: "/snapshot", label: "Stock Snapshot", icon: Camera },
      { to: "/movements", label: "Movements", icon: ArrowLeftRight },
      { to: "/reservations", label: "Reservations", icon: Lock },
    ],
  },
  {
    label: "Purchasing",
    items: [
      { to: "/orders", label: "Purchase Orders", icon: FileText },
      { to: "/arrival", label: "Arrivals", icon: Truck },
    ],
  },
  {
    label: "Admin",
    items: [
      { to: "/master", label: "Master Data", icon: Database },
      { to: "/users", label: "Users", icon: Users },
      { to: "/history", label: "Audit Log", icon: History },
    ],
  },
];

const allNavItems = navGroups.flatMap((g) => g.items);

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

/** Resolve the page title from the current pathname. */
function usePageTitle(): string {
  const { pathname } = useLocation();
  const match = allNavItems.find((item) =>
    item.to === "/" ? pathname === "/" : pathname.startsWith(item.to),
  );
  return match?.label ?? "Page";
}

/* ------------------------------------------------------------------ */
/*  AppShell                                                          */
/* ------------------------------------------------------------------ */

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const pageTitle = usePageTitle();

  /* ── Auth state (ported from old AppShell) ── */
  const [isSignedIn, setIsSignedIn] = useState<boolean>(
    Boolean(getStoredAccessTokenOrNull()),
  );
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [registrationStatus, setRegistrationStatus] =
    useState<RegistrationStatus | null>(null);
  const [verificationRequired, setVerificationRequired] = useState(false);
  const [authStatusMessage, setAuthStatusMessage] = useState<string | null>(
    null,
  );
  const [authVersion, setAuthVersion] = useState(0);
  const [usersVersion, setUsersVersion] = useState(0);
  const [authResolutionBusy, setAuthResolutionBusy] = useState(false);

  const onRegistrationPage = location.pathname === "/registration";
  const onVerifyEmailPage = location.pathname === "/verify-email";

  /* ── Resolve signed-in identity ── */
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
        setAuthStatusMessage(
          `Signed in as ${user.display_name} (${user.role}).`,
        );
      } catch (error) {
        if (!active) return;
        setCurrentUser(null);
        if (isEmailVerificationRequiredError(error)) {
          setVerificationRequired(true);
          setRegistrationStatus(null);
          setAuthStatusMessage(
            "Verify your email address before accessing this environment.",
          );
          return;
        }
        if (!isAuthError(error)) {
          setRegistrationStatus(null);
          setAuthStatusMessage(presentApiError(error));
          return;
        }
        try {
          const status = await apiGet<RegistrationStatus>(
            "/auth/registration-status",
          );
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
              setAuthStatusMessage(
                "Registration is pending admin approval.",
              );
              break;
            case "rejected":
              setAuthStatusMessage(
                "Registration was rejected. Review the reason and resubmit.",
              );
              break;
            case "approved":
              setAuthStatusMessage(
                "This account was approved before, but the mapped app user is inactive.",
              );
              break;
            default:
              setAuthStatusMessage(
                "Sign-in succeeded. Complete a registration request to access the app.",
              );
              break;
          }
        } catch (statusError) {
          if (!active) return;
          if (isEmailVerificationRequiredError(statusError)) {
            setVerificationRequired(true);
            setRegistrationStatus(null);
            setAuthStatusMessage(
              "Verify your email address before accessing this environment.",
            );
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

  /* ── External event subscriptions ── */
  useEffect(
    () => subscribeUsersChanged(() => setUsersVersion((v) => v + 1)),
    [],
  );
  useEffect(
    () =>
      subscribeAuthSessionChanged(() => {
        setIsSignedIn(Boolean(getStoredAccessTokenOrNull()));
        setAuthVersion((v) => v + 1);
        setAuthStatusMessage(null);
        setRegistrationStatus(null);
        setVerificationRequired(false);
      }),
    [],
  );

  /* ── Sign out handler ── */
  const clearToken = () => {
    clearStoredAuthSession();
    setCurrentUser(null);
    setRegistrationStatus(null);
    setVerificationRequired(false);
    setIsSignedIn(false);
    setAuthStatusMessage(null);
  };

  /* ── Redirect unauthenticated users to /login ── */
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

  /* ── Redirect based on registration / verification state ── */
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
    if (
      !currentUser &&
      registrationStatus &&
      !registrationStatus.current_user &&
      !onRegistrationPage
    ) {
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

  /* ── Conditional navigation ── */
  const visibleGroups = useMemo<NavGroup[]>(() => {
    if (!isSignedIn) return navGroups;
    if (verificationRequired) {
      return [
        {
          label: "Account",
          items: [
            { to: "/verify-email", label: "Verify Email", icon: LogIn },
          ],
        },
      ];
    }
    if (!currentUser) {
      return [
        {
          label: "Account",
          items: [
            { to: "/registration", label: "Registration", icon: FileText },
          ],
        },
      ];
    }
    return navGroups;
  }, [currentUser, isSignedIn, verificationRequired]);

  const authSession = getStoredAuthSessionSnapshot();

  /* ── Render ── */
  return (
    <SidebarProvider>
      {/* ── Sidebar ── */}
      <Sidebar className="border-r-0">
        {/* Header / logo */}
        <SidebarHeader className="px-4 py-5">
          <div className="rounded-xl bg-slatebrand px-3 py-2 text-center font-display text-sm font-bold tracking-wide text-white">
            Optical Inventory
          </div>
        </SidebarHeader>

        <SidebarSeparator />

        {/* Navigation groups */}
        <SidebarContent>
          {visibleGroups.map((group) => (
            <SidebarGroup key={group.label}>
              <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {group.items.map((item) => (
                    <SidebarMenuItem key={item.to}>
                      <SidebarMenuButton asChild>
                        <NavLink
                          to={item.to}
                          end={item.to === "/"}
                          className={({ isActive }) =>
                            isActive
                              ? "bg-sidebar-primary text-sidebar-primary-foreground"
                              : ""
                          }
                        >
                          <item.icon className="size-4" />
                          <span>{item.label}</span>
                        </NavLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </SidebarContent>

        <SidebarSeparator />

        {/* Footer — user info & sign out */}
        <SidebarFooter className="px-4 py-4">
          {isSignedIn ? (
            <div className="space-y-3">
              {/* Auth status message */}
              {authStatusMessage && (
                <p className="text-xs text-sidebar-foreground/70">
                  {authStatusMessage}
                </p>
              )}

              {/* User identity */}
              <div className="flex items-center gap-2">
                <span className="inline-block size-2 rounded-full bg-emerald-400" />
                <span className="truncate text-sm font-semibold text-sidebar-foreground">
                  {currentUser
                    ? currentUser.display_name
                    : authSession?.email
                      ? authSession.email
                      : "Signed in"}
                </span>
              </div>

              {currentUser && (
                <span className="inline-block rounded-md bg-sidebar-accent px-1.5 py-0.5 text-xs font-medium text-sidebar-accent-foreground">
                  {currentUser.role}
                </span>
              )}

              {authSession?.emailVerified === false && (
                <span className="inline-block rounded-md bg-amber-500/20 px-1.5 py-0.5 text-xs font-medium text-amber-300">
                  unverified
                </span>
              )}

              {/* Sign out button */}
              <button
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-sidebar-foreground/80 transition hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                onClick={clearToken}
                type="button"
              >
                <LogOut className="size-4" />
                Sign out
              </button>
            </div>
          ) : (
            <NavLink
              to="/login"
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-sidebar-foreground/80 transition hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
            >
              <LogIn className="size-4" />
              Sign in
            </NavLink>
          )}
        </SidebarFooter>
      </Sidebar>

      {/* ── Main content area ── */}
      <SidebarInset>
        {/* Top header bar with sidebar trigger + breadcrumb */}
        <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-black/5 bg-canvas/90 px-4 backdrop-blur">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-2 h-4" />
          <Breadcrumb>
            <BreadcrumbList>
              <BreadcrumbItem>
                <BreadcrumbPage>{pageTitle}</BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
        </header>

        {/* Page content */}
        <main className="mx-auto max-w-7xl px-6 py-8">
          <RouteErrorBoundary location={location}>
            <Outlet />
          </RouteErrorBoundary>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
