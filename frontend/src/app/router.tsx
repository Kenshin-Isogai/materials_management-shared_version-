import {
  createBrowserRouter,
  createRoutesFromElements,
  Navigate,
  Route,
} from "react-router-dom";

import { AppShell } from "@/app/layouts/AppShell";
import { AuthLayout } from "@/app/layouts/AuthLayout";

/* ── Pages (existing, will be moved to features/ later) ── */
import { ArrivalPage } from "@/pages/ArrivalPage";
import { BomPage } from "@/pages/BomPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { HistoryPage } from "@/pages/HistoryPage";
import { InventoryPage } from "@/pages/InventoryPage";
import { ItemsPage } from "@/pages/ItemsPage";
import { LocationsPage } from "@/pages/LocationsPage";
import { LoginPage } from "@/pages/LoginPage";
import { MasterPage } from "@/pages/MasterPage";
import { OrdersPage } from "@/pages/OrdersPage";
import { ProcurementPage } from "@/pages/ProcurementPage";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { ReservationsPage } from "@/pages/ReservationsPage";
import { RegistrationPage } from "@/pages/RegistrationPage";
import { SnapshotPage } from "@/pages/SnapshotPage";
import { UsersPage } from "@/pages/UsersPage";
import { VerifyEmailPage } from "@/pages/VerifyEmailPage";
import { WorkspacePage } from "@/pages/WorkspacePage";

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
        <Route path="/projects/overview" element={<WorkspacePage />} />
        <Route path="/procurement" element={<ProcurementPage />} />
        <Route path="/bom" element={<BomPage />} />

        {/* ── Inventory ── */}
        <Route path="/items" element={<ItemsPage />} />
        <Route path="/locations" element={<LocationsPage />} />
        <Route path="/snapshot" element={<SnapshotPage />} />
        <Route path="/movements" element={<InventoryPage />} />
        <Route path="/reservations" element={<ReservationsPage />} />

        {/* ── Purchasing ── */}
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/arrival" element={<ArrivalPage />} />

        {/* ── Admin ── */}
        <Route path="/master" element={<MasterPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/history" element={<HistoryPage />} />

        {/* ── Redirects for old routes ── */}
        <Route path="/dashboard" element={<Navigate to="/" replace />} />
        <Route path="/search" element={<Navigate to="/items" replace />} />
        <Route path="/location" element={<Navigate to="/locations" replace />} />
        <Route path="/inventory" element={<Navigate to="/movements" replace />} />
        <Route path="/reserve" element={<Navigate to="/reservations" replace />} />
        <Route path="/workspace" element={<Navigate to="/projects/overview" replace />} />
        <Route path="/purchase-order-lines" element={<Navigate to="/orders" replace />} />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </>,
  ),
);
