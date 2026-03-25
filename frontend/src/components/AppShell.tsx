import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import {
  apiGet,
  getStoredUsernameOrNull,
  setStoredUsername,
  subscribeUsersChanged,
} from "../lib/api";
import type { User } from "../lib/types";

const nav = [
  { to: "/", label: "Dashboard" },
  { to: "/workspace", label: "Workspace" },
  { to: "/search", label: "Search" },
  { to: "/location", label: "Location" },
  { to: "/projects", label: "Projects" },
  { to: "/procurement", label: "Procurement" },
  { to: "/orders", label: "Orders" },
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
  const [users, setUsers] = useState<User[]>([]);
  const [selectedUsername, setSelectedUsernameState] = useState<string>(getStoredUsernameOrNull() ?? "");
  const [usersVersion, setUsersVersion] = useState(0);

  useEffect(() => {
    let active = true;
    apiGet<User[]>("/users")
      .then((rows) => {
        if (!active) return;
        setUsers(rows);
        if (rows.length === 0) {
          setStoredUsername(null);
          setSelectedUsernameState("");
          return;
        }
        if (selectedUsername && !rows.some((row) => row.username === selectedUsername)) {
          const nextUsername = rows[0]?.username ?? "";
          setStoredUsername(nextUsername || null);
          setSelectedUsernameState(nextUsername);
          return;
        }
        if (!selectedUsername && rows.length > 0) {
          const nextUsername = rows[0].username;
          setStoredUsername(nextUsername);
          setSelectedUsernameState(nextUsername);
        }
      })
      .catch(() => {
        if (active) {
          setUsers([]);
        }
      });
    return () => {
      active = false;
    };
  }, [selectedUsername, usersVersion]);

  useEffect(() => subscribeUsersChanged(() => setUsersVersion((value) => value + 1)), []);

  const handleUserChange = (nextUsername: string) => {
    setStoredUsername(nextUsername || null);
    setSelectedUsernameState(nextUsername);
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
          <label className="ml-auto flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm shadow-sm">
            <span className="font-semibold text-slate-600">User</span>
            <select
              className="min-w-36 bg-transparent text-slate-900 outline-none"
              value={selectedUsername}
              onChange={(event) => handleUserChange(event.target.value)}
            >
              <option value="">Select user</option>
              {users.map((user) => (
                <option key={user.username} value={user.username}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>
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
