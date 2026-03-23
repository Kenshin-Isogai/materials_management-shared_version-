import {
  createBrowserRouter,
  createRoutesFromElements,
  Navigate,
  Route,
  RouterProvider,
} from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { BomPage } from "./pages/BomPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { InventoryPage } from "./pages/InventoryPage";
import { ItemsPage } from "./pages/ItemsPage";
import { LocationsPage } from "./pages/LocationsPage";
import { MasterPage } from "./pages/MasterPage";
import { OrdersPage } from "./pages/OrdersPage";
import { ProcurementPage } from "./pages/ProcurementPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ReservationsPage } from "./pages/ReservationsPage";
import { SnapshotPage } from "./pages/SnapshotPage";
import { WorkspacePage } from "./pages/WorkspacePage";

export const appRoutes = createRoutesFromElements(
  <Route element={<AppShell />}>
    <Route path="/" element={<DashboardPage />} />
    <Route path="/dashboard" element={<Navigate to="/" replace />} />
    <Route path="/search" element={<ItemsPage />} />
    <Route path="/location" element={<LocationsPage />} />
    <Route path="/arrival" element={<OrdersPage />} />
    <Route path="/movements" element={<InventoryPage />} />
    <Route path="/reserve" element={<ReservationsPage />} />
    <Route path="/items" element={<ItemsPage />} />
    <Route path="/inventory" element={<Navigate to="/movements" replace />} />
    <Route path="/orders" element={<OrdersPage />} />
    <Route path="/reservations" element={<Navigate to="/reserve" replace />} />
    <Route path="/projects" element={<ProjectsPage />} />
    <Route path="/workspace" element={<WorkspacePage />} />
    <Route path="/procurement" element={<ProcurementPage />} />
    <Route path="/bom" element={<BomPage />} />
    <Route path="/locations" element={<Navigate to="/location" replace />} />
    <Route path="/snapshot" element={<SnapshotPage />} />
    <Route path="/history" element={<HistoryPage />} />
    <Route path="/master" element={<MasterPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Route>,
);

const appRouter = createBrowserRouter(appRoutes);

export default function App() {
  return <RouterProvider router={appRouter} />;
}
