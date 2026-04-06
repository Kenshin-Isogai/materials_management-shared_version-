import { Suspense, lazy } from "react";
import {
  createBrowserRouter,
  createRoutesFromElements,
  Navigate,
  Route,
} from "react-router-dom";

import { AppShell } from "@/app/layouts/AppShell";
import { AuthLayout } from "@/app/layouts/AuthLayout";

function lazyNamed<TModule, TKey extends keyof TModule & string>(
  loader: () => Promise<TModule>,
  exportName: TKey,
) {
  return lazy(async () => {
    const mod = await loader();
    return { default: mod[exportName] as React.ComponentType };
  });
}

function RouteFallback() {
  return <div className="panel p-6 text-sm text-slate-500">Loading...</div>;
}

function routeElement(Component: React.ComponentType) {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Component />
    </Suspense>
  );
}

const DashboardPage = lazyNamed(() => import("@/features/dashboard/DashboardPage"), "DashboardPage");
const ProjectsPage = lazyNamed(() => import("@/features/projects/ProjectsPage"), "ProjectsPage");
const ProjectOverviewPage = lazyNamed(() => import("@/features/projects/ProjectOverviewPage"), "ProjectOverviewPage");
const PlanningBoardPage = lazyNamed(() => import("@/features/projects/PlanningBoardPage"), "PlanningBoardPage");
const ProcurementPage = lazyNamed(() => import("@/features/procurement/ProcurementPage"), "ProcurementPage");
const BomPage = lazyNamed(() => import("@/features/bom/BomPage"), "BomPage");
const ItemsPage = lazyNamed(() => import("@/features/items/ItemsPage"), "ItemsPage");
const ItemDetailPage = lazyNamed(() => import("@/features/items/ItemDetailPage"), "ItemDetailPage");
const LocationsPage = lazyNamed(() => import("@/features/inventory/LocationsPage"), "LocationsPage");
const SnapshotPage = lazyNamed(() => import("@/features/inventory/SnapshotPage"), "SnapshotPage");
const MovementsPage = lazyNamed(() => import("@/features/inventory/MovementsPage"), "InventoryPage");
const ReservationsPage = lazyNamed(() => import("@/features/inventory/ReservationsPage"), "ReservationsPage");
const OrdersPage = lazyNamed(() => import("@/features/orders/OrdersPage"), "OrdersPage");
const ArrivalPage = lazyNamed(() => import("@/features/orders/ArrivalPage"), "ArrivalPage");
const MasterPage = lazyNamed(() => import("@/features/admin/MasterPage"), "MasterPage");
const UsersPage = lazyNamed(() => import("@/features/admin/UsersPage"), "UsersPage");
const AuditLogPage = lazyNamed(() => import("@/features/admin/AuditLogPage"), "HistoryPage");
const LoginPage = lazyNamed(() => import("@/features/admin/LoginPage"), "LoginPage");
const RegistrationPage = lazyNamed(() => import("@/features/admin/RegistrationPage"), "RegistrationPage");
const VerifyEmailPage = lazyNamed(() => import("@/features/admin/VerifyEmailPage"), "VerifyEmailPage");

export const appRoutes = createRoutesFromElements(
  <>
    {/* Auth pages — standalone, no sidebar */}
    <Route element={<AuthLayout />}>
      <Route path="/login" element={routeElement(LoginPage)} />
      <Route path="/registration" element={routeElement(RegistrationPage)} />
      <Route path="/verify-email" element={routeElement(VerifyEmailPage)} />
    </Route>

    {/* Main app — sidebar layout */}
    <Route element={<AppShell />}>
      {/* ── Planning ── */}
      <Route path="/" element={routeElement(DashboardPage)} />
      <Route path="/projects" element={routeElement(ProjectsPage)} />
      <Route path="/projects/overview" element={routeElement(ProjectOverviewPage)} />
      <Route path="/projects/board" element={routeElement(PlanningBoardPage)} />
      <Route path="/projects/board/:projectId" element={routeElement(PlanningBoardPage)} />
      <Route path="/procurement" element={routeElement(ProcurementPage)} />
      <Route path="/bom" element={routeElement(BomPage)} />

      {/* ── Inventory ── */}
      <Route path="/items" element={routeElement(ItemsPage)} />
      <Route path="/items/:itemId" element={routeElement(ItemDetailPage)} />
      <Route path="/locations" element={routeElement(LocationsPage)} />
      <Route path="/snapshot" element={routeElement(SnapshotPage)} />
      <Route path="/movements" element={routeElement(MovementsPage)} />
      <Route path="/reservations" element={routeElement(ReservationsPage)} />

      {/* ── Purchasing ── */}
      <Route path="/orders" element={routeElement(OrdersPage)} />
      <Route path="/arrival" element={routeElement(ArrivalPage)} />

      {/* ── Admin ── */}
      <Route path="/master" element={routeElement(MasterPage)} />
      <Route path="/users" element={routeElement(UsersPage)} />
      <Route path="/history" element={routeElement(AuditLogPage)} />

      {/* ── Redirects for old routes ── */}
      <Route path="/dashboard" element={<Navigate to="/" replace />} />
      <Route path="/search" element={<Navigate to="/items" replace />} />
      <Route path="/location" element={<Navigate to="/locations" replace />} />
      <Route path="/inventory" element={<Navigate to="/movements" replace />} />
      <Route path="/reserve" element={<Navigate to="/reservations" replace />} />
      <Route path="/workspace" element={<Navigate to="/projects/overview" replace />} />
      <Route path="/purchase-order-lines" element={<Navigate to="/orders" replace />} />
      <Route path="/audit" element={<Navigate to="/history" replace />} />

      {/* Catch-all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Route>
  </>,
);

export const appRouter = createBrowserRouter(appRoutes);
