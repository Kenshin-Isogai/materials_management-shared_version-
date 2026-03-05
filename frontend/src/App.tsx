import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AssembliesPage } from "./pages/AssembliesPage";
import { BomPage } from "./pages/BomPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { InventoryPage } from "./pages/InventoryPage";
import { ItemsPage } from "./pages/ItemsPage";
import { LocationsPage } from "./pages/LocationsPage";
import { MasterPage } from "./pages/MasterPage";
import { OrdersPage } from "./pages/OrdersPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { PurchaseCandidatesPage } from "./pages/PurchaseCandidatesPage";
import { ReservationsPage } from "./pages/ReservationsPage";
import { SnapshotPage } from "./pages/SnapshotPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/items" element={<ItemsPage />} />
        <Route path="/inventory" element={<InventoryPage />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/reservations" element={<ReservationsPage />} />
        <Route path="/assemblies" element={<AssembliesPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/purchase-candidates" element={<PurchaseCandidatesPage />} />
        <Route path="/bom" element={<BomPage />} />
        <Route path="/locations" element={<LocationsPage />} />
        <Route path="/snapshot" element={<SnapshotPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/master" element={<MasterPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
