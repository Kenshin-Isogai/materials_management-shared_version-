import { NavLink, Outlet } from "react-router-dom";

const nav = [
  { to: "/", label: "Dashboard" },
  { to: "/items", label: "Items" },
  { to: "/inventory", label: "Movements" },
  { to: "/orders", label: "Orders" },
  { to: "/reservations", label: "Reservations" },
  { to: "/assemblies", label: "Assemblies" },
  { to: "/projects", label: "Projects" },
  { to: "/workspace", label: "Workspace" },
  { to: "/purchase-candidates", label: "Purchase Candidates" },
  { to: "/planning", label: "Planning" },
  { to: "/rfq", label: "RFQ" },
  { to: "/bom", label: "BOM" },
  { to: "/locations", label: "Location" },
  { to: "/snapshot", label: "Snapshot" },
  { to: "/history", label: "History" },
  { to: "/master", label: "Master" }
];

export function AppShell() {
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
                `rounded-lg px-3 py-2 text-sm font-semibold transition ${
                  isActive
                    ? "bg-signal text-white"
                    : "text-slate-700 hover:bg-white hover:text-slate-900"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
