import {
  createBrowserRouter,
  createRoutesFromElements,
  Navigate,
  Route,
} from "react-router-dom";

import { AppShell } from "@/app/layouts/AppShell";
import { AuthLayout } from "@/app/layouts/AuthLayout";

/* ── Feature modules ── */
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { ProjectsPage } from "@/features/projects/ProjectsPage";
import { ProjectOverviewPage } from "@/features/projects/ProjectOverviewPage";
import { PlanningBoardPage } from "@/features/projects/PlanningBoardPage";
import { ProcurementPage } from "@/features/procurement/ProcurementPage";
import { BomPage } from "@/features/bom/BomPage";
import { ItemsPage } from "@/features/items/ItemsPage";
import { ItemDetailPage } from "@/features/items/ItemDetailPage";
import { LocationsPage } from "@/features/inventory/LocationsPage";
import { SnapshotPage } from "@/features/inventory/SnapshotPage";
import { InventoryPage as MovementsPage } from "@/features/inventory/MovementsPage";
import { ReservationsPage } from "@/features/inventory/ReservationsPage";
import { OrdersPage } from "@/features/orders/OrdersPage";
import { ArrivalPage } from "@/features/orders/ArrivalPage";
import { MasterPage } from "@/features/admin/MasterPage";
import { UsersPage } from "@/features/admin/UsersPage";
import { HistoryPage as AuditLogPage } from "@/features/admin/AuditLogPage";
import { LoginPage } from "@/features/admin/LoginPage";
import { RegistrationPage } from "@/features/admin/RegistrationPage";
import { VerifyEmailPage } from "@/features/admin/VerifyEmailPage";

export const appRouter = createBrowserRouter(
  createRoutesFromElements(
    <>
      {/* Auth pages — standalone, no sidebar */}
      <Route element={<AuthLayout />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/registration" element={<RegistrationPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
      </Route>

      {/* Main app — sidebar layout */}
      <Route element={<AppShell />}>
        {/* ── Planning ── */}
        <Route path="/" element={<DashboardPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/overview" element={<ProjectOverviewPage />} />
        <Route path="/projects/board" element={<PlanningBoardPage />} />
        <Route path="/projects/board/:projectId" element={<PlanningBoardPage />} />
        <Route path="/procurement" element={<ProcurementPage />} />
        <Route path="/bom" element={<BomPage />} />

        {/* ── Inventory ── */}
        <Route path="/items" element={<ItemsPage />} />
        <Route path="/items/:itemId" element={<ItemDetailPage />} />
        <Route path="/locations" element={<LocationsPage />} />
        <Route path="/snapshot" element={<SnapshotPage />} />
        <Route path="/movements" element={<MovementsPage />} />
        <Route path="/reservations" element={<ReservationsPage />} />

        {/* ── Purchasing ── */}
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/arrival" element={<ArrivalPage />} />

        {/* ── Admin ── */}
        <Route path="/master" element={<MasterPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/history" element={<AuditLogPage />} />

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
  ),
);
