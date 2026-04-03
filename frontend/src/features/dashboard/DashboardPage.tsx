import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import useSWR from "swr";
import { apiGet } from "@/lib/api";
import { StatCard } from "@/components/StatCard";
import { StatusCallout } from "@/components/StatusCallout";
import { PageHeader } from "@/components/layout";
import { isAuthError, isBackendUnavailableError, presentApiError } from "@/lib/errorUtils";

type Summary = {
  overdue_orders: Array<Record<string, unknown>>;
  expiring_reservations: Array<Record<string, unknown>>;
  low_stock_alerts: Array<Record<string, unknown>>;
  recent_activity: Array<Record<string, unknown>>;
  pending_registration_requests: number;
};

function QuickActionCard({ to, icon, label, description }: { to: string; icon: string; label: string; description: string }) {
  return (
    <Link
      to={to}
      className="group flex items-start gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 transition hover:border-signal/30 hover:bg-signal/5 hover:shadow-sm"
    >
      <span className="mt-0.5 text-lg">{icon}</span>
      <div>
        <p className="text-sm font-semibold text-slate-900 group-hover:text-signal">{label}</p>
        <p className="text-xs text-slate-500">{description}</p>
      </div>
    </Link>
  );
}

export function DashboardPage() {
  const [overdueQuery, setOverdueQuery] = useState("");
  const { data, error, isLoading } = useSWR<Summary>(
    "/dashboard",
    () => apiGet<Summary>("/dashboard/summary"),
    { refreshInterval: 20_000 }
  );

  const filteredOverdueOrders = useMemo(() => {
    if (!data) return [];
    const needle = overdueQuery.trim().toLowerCase();
    if (!needle) return data.overdue_orders;
    return data.overdue_orders.filter((order) =>
      [
        String(order.order_id ?? ""),
        String(order.item_number ?? ""),
        String(order.supplier_name ?? ""),
        String(order.expected_arrival ?? ""),
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle)
    );
  }, [data, overdueQuery]);
  const showOverdueTable = filteredOverdueOrders.length > 8;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Overdue arrivals, expiring reservations, low stock, and recent inventory activity."
      />

      {isLoading && <div className="panel p-6 text-sm text-slate-500">Loading...</div>}
      {error && (
        <StatusCallout
          title={
            isAuthError(error)
              ? "Sign-in required"
              : isBackendUnavailableError(error)
                ? "Environment unavailable"
                : "Dashboard request failed"
          }
          message={
            isAuthError(error)
              ? "Sign in with an allowed account to load dashboard data."
              : isBackendUnavailableError(error)
                ? "Dashboard is unavailable because the backend or database is not ready. If this is dev or staging, start Cloud SQL and try again."
                : presentApiError(error)
          }
          tone={isBackendUnavailableError(error) ? "warning" : "error"}
        />
      )}

      {data && (
        <>
          {/* ── Quick Actions ── */}
          <section>
            <h2 className="mb-3 font-display text-sm font-semibold uppercase tracking-wide text-slate-500">Quick Actions</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <QuickActionCard to="/projects" icon="📋" label="Projects" description="View and create projects" />
              <QuickActionCard to="/items" icon="🔍" label="Import Items" description="Search or import items" />
              <QuickActionCard to="/orders" icon="📄" label="Purchase Orders" description="Import and manage orders" />
              <QuickActionCard to="/arrival" icon="🚚" label="Record Arrival" description="Record incoming deliveries" />
            </div>
          </section>

          {/* ── Summary Stats ── */}
          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <StatCard label="Overdue Orders" value={data.overdue_orders.length} tone="brass" />
            <StatCard label="Expiring Reservations" value={data.expiring_reservations.length} tone="signal" />
            <StatCard label="Low Stock Alerts" value={data.low_stock_alerts.length} />
            <StatCard label="Recent Logs" value={data.recent_activity.length} />
            <StatCard label="Pending Registrations" value={data.pending_registration_requests} tone="brass" />
          </section>

          {/* ── Alert Details ── */}
          <section className="grid gap-5 lg:grid-cols-2">
            <article className="panel p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="font-display text-lg font-semibold">Overdue Orders</h2>
                <input
                  className="input w-72"
                  placeholder="Filter overdue orders"
                  value={overdueQuery}
                  onChange={(e) => setOverdueQuery(e.target.value)}
                />
              </div>
              {!filteredOverdueOrders.length ? (
                <p className="mt-3 text-sm text-slate-500">None</p>
              ) : showOverdueTable ? (
                <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
                  <table className="min-w-[560px] text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-left text-slate-500">
                        <th className="px-2 py-2">Order</th>
                        <th className="px-2 py-2">Item</th>
                        <th className="px-2 py-2">Supplier</th>
                        <th className="px-2 py-2">Expected Arrival</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredOverdueOrders.map((order, idx) => (
                        <tr key={`${String(order.order_id)}-${idx}`} className="border-b border-slate-100">
                          <td className="px-2 py-2">#{String(order.order_id)}</td>
                          <td className="px-2 py-2">{String(order.item_number)}</td>
                          <td className="px-2 py-2">{String(order.supplier_name)}</td>
                          <td className="px-2 py-2">{String(order.expected_arrival)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <ul className="mt-3 space-y-2 text-sm">
                  {filteredOverdueOrders.map((order, idx) => (
                    <li key={idx} className="rounded-lg bg-slate-50 px-3 py-2">
                      #{String(order.order_id)} {String(order.item_number)} ({String(order.supplier_name)}) -{" "}
                      {String(order.expected_arrival)}
                    </li>
                  ))}
                </ul>
              )}
            </article>

            <article className="panel p-4">
              <h2 className="font-display text-lg font-semibold">Low Stock</h2>
              <ul className="mt-3 space-y-2 text-sm">
                {data.low_stock_alerts.slice(0, 8).map((row, idx) => (
                  <li key={idx} className="rounded-lg bg-slate-50 px-3 py-2">
                    {String(row.item_number)} - {String(row.quantity)}
                  </li>
                ))}
                {!data.low_stock_alerts.length && <li className="text-slate-500">None</li>}
              </ul>
            </article>

            <article className="panel p-4">
              <h2 className="font-display text-lg font-semibold">Expiring Reservations</h2>
              <ul className="mt-3 space-y-2 text-sm">
                {data.expiring_reservations.slice(0, 8).map((row, idx) => (
                  <li key={idx} className="rounded-lg bg-slate-50 px-3 py-2">
                    {String(row.item_number ?? row.canonical_item_number ?? "")} - expires {String(row.expiration_date ?? "")}
                  </li>
                ))}
                {!data.expiring_reservations.length && <li className="text-slate-500">None</li>}
              </ul>
            </article>

            <article className="panel p-4">
              <h2 className="font-display text-lg font-semibold">Recent Activity</h2>
              <ul className="mt-3 space-y-2 text-sm">
                {data.recent_activity.slice(0, 8).map((row, idx) => (
                  <li key={idx} className="rounded-lg bg-slate-50 px-3 py-2">
                    <span className="font-medium">{String(row.action ?? row.event_type ?? "")}</span>
                    {row.entity_type ? <span className="text-slate-500"> · {String(row.entity_type)}</span> : null}
                    {row.created_at ? <span className="text-xs text-slate-400"> · {String(row.created_at)}</span> : null}
                  </li>
                ))}
                {!data.recent_activity.length && <li className="text-slate-500">None</li>}
              </ul>
            </article>
          </section>
        </>
      )}
    </div>
  );
}
