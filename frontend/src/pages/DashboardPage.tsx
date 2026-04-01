import { useMemo, useState } from "react";
import useSWR from "swr";
import { apiGet } from "../lib/api";
import { StatCard } from "../components/StatCard";
import { StatusCallout } from "../components/StatusCallout";
import { isAuthError, isBackendUnavailableError, presentApiError } from "../lib/errorUtils";

type Summary = {
  overdue_orders: Array<Record<string, unknown>>;
  expiring_reservations: Array<Record<string, unknown>>;
  low_stock_alerts: Array<Record<string, unknown>>;
  recent_activity: Array<Record<string, unknown>>;
  pending_registration_requests: number;
};

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

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-600">
          Overdue arrivals, expiring reservations, low stock, and recent inventory activity.
        </p>
      </section>

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
          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <StatCard label="Overdue Orders" value={data.overdue_orders.length} tone="brass" />
            <StatCard label="Expiring Reservations" value={data.expiring_reservations.length} tone="signal" />
            <StatCard label="Low Stock Alerts" value={data.low_stock_alerts.length} />
            <StatCard label="Recent Logs" value={data.recent_activity.length} />
            <StatCard label="Pending Registrations" value={data.pending_registration_requests} tone="brass" />
          </section>

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
              <ul className="mt-3 space-y-2 text-sm">
                {filteredOverdueOrders.slice(0, 8).map((order, idx) => (
                  <li key={idx} className="rounded-lg bg-slate-50 px-3 py-2">
                    #{String(order.order_id)} {String(order.item_number)} ({String(order.supplier_name)}) -{" "}
                    {String(order.expected_arrival)}
                  </li>
                ))}
                {!filteredOverdueOrders.length && <li className="text-slate-500">None</li>}
              </ul>
              {filteredOverdueOrders.length > 8 && (
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
          </section>
        </>
      )}
    </div>
  );
}
