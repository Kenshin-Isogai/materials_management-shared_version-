import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { apiDownload, apiGet } from "@/lib/api";
import type { User } from "@/lib/types";

type SnapshotRow = {
  item_id: number;
  item_number: string;
  location: string;
  quantity: number;
  category: string | null;
  description: string | null;
  allocated_quantity: number;
  active_reservation_count: number;
  allocated_project_names: string[];
};

type SnapshotResponse = {
  date: string;
  mode: "past" | "future";
  basis: "raw" | "net_available";
  rows: SnapshotRow[];
};

function todayJst(): string {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return formatter.format(new Date());
}

function canExportSnapshotCsv(user: User | undefined): boolean {
  return user?.role === "operator" || user?.role === "admin";
}

export function SnapshotPage() {
  const currentUserQuery = useSWR("/users/me", () => apiGet<User>("/users/me"));
  const [date, setDate] = useState(() => todayJst());
  const [mode, setMode] = useState<"past" | "future">("future");
  const [basis, setBasis] = useState<"raw" | "net_available">("net_available");
  const [data, setData] = useState<SnapshotResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const ALL_FILTER = "__ALL__";
  const [locationFilter, setLocationFilter] = useState(ALL_FILTER);
  const [categoryFilter, setCategoryFilter] = useState(ALL_FILTER);
  const [descriptionFilter, setDescriptionFilter] = useState("");
  const [shortageOnly, setShortageOnly] = useState(false);
  const [shortageThreshold, setShortageThreshold] = useState("0");
  const [sortKey, setSortKey] = useState<"item_number" | "location" | "quantity" | "category">("quantity");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const hasLoadedInitialSnapshot = useRef(false);

  const locationOptions = useMemo(() => {
    const values = (data?.rows ?? []).map((row) => row.location);
    return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b));
  }, [data?.rows]);

  const categoryOptions = useMemo(() => {
    const values = (data?.rows ?? []).map((row) => row.category ?? "Uncategorized");
    return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b));
  }, [data?.rows]);

  const filteredSortedRows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const parsedThreshold = Number(shortageThreshold);
    const effectiveThreshold = Number.isFinite(parsedThreshold) ? parsedThreshold : 0;
    const rows = (data?.rows ?? []).filter((row) => {
      if (locationFilter !== ALL_FILTER && row.location !== locationFilter) return false;
      const normalizedCategory = row.category ?? "Uncategorized";
      if (categoryFilter !== ALL_FILTER && normalizedCategory !== categoryFilter) return false;
      if (shortageOnly && row.quantity > effectiveThreshold) return false;
      const normalizedDescription = (row.description ?? "").toLowerCase();
      if (descriptionFilter.trim() && !normalizedDescription.includes(descriptionFilter.trim().toLowerCase())) return false;
      if (!normalizedQuery) return true;
      return [row.item_number, row.location, normalizedCategory, row.description ?? "", String(row.quantity)]
        .concat(row.allocated_project_names ?? [])
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    });

    rows.sort((a, b) => {
      if (sortKey === "quantity") {
        return sortDirection === "asc" ? a.quantity - b.quantity : b.quantity - a.quantity;
      }
      const left = (a[sortKey] ?? "Uncategorized").toString();
      const right = (b[sortKey] ?? "Uncategorized").toString();
      const compared = left.localeCompare(right);
      return sortDirection === "asc" ? compared : -compared;
    });

    return rows;
  }, [categoryFilter, data?.rows, descriptionFilter, locationFilter, query, shortageOnly, shortageThreshold, sortDirection, sortKey]);
  const exportAllowed = canExportSnapshotCsv(currentUserQuery.data);

  function toggleSort(nextKey: typeof sortKey) {
    if (nextKey === sortKey) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextKey);
    setSortDirection("asc");
  }

  function sortIndicator(key: typeof sortKey): string {
    if (key !== sortKey) return "↕";
    return sortDirection === "asc" ? "↑" : "↓";
  }

  async function loadSnapshot(nextDate: string, nextMode: "past" | "future", nextBasis: "raw" | "net_available") {
    if (nextBasis === "net_available" && nextMode === "past") {
      setMessage("Net available is supported for current/future snapshots only. Switch mode to future.");
      return;
    }
    const params = new URLSearchParams();
    if (nextDate) params.set("date", nextDate);
    params.set("mode", nextMode);
    params.set("basis", nextBasis);
    setLoading(true);
    setMessage("");
    try {
      const result = await apiGet<SnapshotResponse>(`/inventory/snapshot?${params.toString()}`);
      setData(result);
      if (nextBasis === "net_available") {
        setMessage(
          "Net available subtracts current active reservation allocations from on-hand inventory, then adds open orders due by the selected date.",
        );
      }
    } finally {
      setLoading(false);
    }
  }

  async function run() {
    await loadSnapshot(date, mode, basis);
  }

  async function downloadSnapshotCsv() {
    if (basis === "net_available" && mode === "past") {
      setMessage("Net available is supported for current/future snapshots only. Switch mode to future.");
      return;
    }
    const params = new URLSearchParams();
    if (date) params.set("date", date);
    params.set("mode", mode);
    params.set("basis", basis);
    setMessage("");
    try {
      await apiDownload(
        `/inventory/snapshot/export.csv?${params.toString()}`,
        `inventory_snapshot_${date || "snapshot"}_${mode}_${basis}.csv`,
      );
      setMessage("Snapshot CSV downloaded.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  useEffect(() => {
    if (hasLoadedInitialSnapshot.current) return;
    hasLoadedInitialSnapshot.current = true;
    void loadSnapshot(date, mode, basis);
  }, [basis, date, mode]);

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Snapshot</h1>
        <p className="mt-1 text-sm text-slate-600">
          Reconstruct raw inventory or review net available residual stock at a target date.
        </p>
      </section>

      <section className="panel p-4">
        <div className="grid gap-3 md:grid-cols-6">
          <input
            className="input"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
          <select className="input" value={mode} onChange={(e) => setMode(e.target.value as "past" | "future")}>
            <option value="past">past</option>
            <option value="future">future</option>
          </select>
          <select
            className="input"
            value={basis}
            onChange={(e) => setBasis(e.target.value as "raw" | "net_available")}
          >
            <option value="raw">raw inventory</option>
            <option value="net_available">net available</option>
          </select>
          <button className="button" disabled={loading} onClick={run}>
            Generate Snapshot
          </button>
          {exportAllowed && (
            <button className="button-secondary md:col-span-2" disabled={loading} onClick={() => void downloadSnapshotCsv()}>
              Export CSV
            </button>
          )}
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Use <strong>raw inventory</strong> for location state reconstruction. Use <strong>net available</strong> to focus on residual stock not currently occupied by active reservations.
        </p>
        {message && <p className="mt-2 text-sm text-slate-600">{message}</p>}
      </section>

      <section className="panel p-4">
        {!data && <p className="text-sm text-slate-500">No snapshot yet.</p>}
        {data && (
          <>
            <p className="mb-3 text-sm text-slate-600">
              Basis: <strong>{data.basis}</strong> / Mode: <strong>{data.mode}</strong> / Date: <strong>{data.date}</strong> / Rows:{" "}
              <strong>{filteredSortedRows.length}</strong> / <strong>{data.rows.length}</strong>
            </p>
            <div className="mb-3 grid gap-3 md:grid-cols-6">
              <input
                className="input"
                placeholder="Search item / location / category / description / qty"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <select className="input" value={locationFilter} onChange={(e) => setLocationFilter(e.target.value)}>
                <option value={ALL_FILTER}>All locations</option>
                {locationOptions.map((location) => (
                  <option key={location} value={location}>
                    {location}
                  </option>
                ))}
              </select>
              <select className="input" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
                <option value={ALL_FILTER}>All categories</option>
                {categoryOptions.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
              <input
                className="input"
                placeholder="Description contains (e.g. kinematic)"
                value={descriptionFilter}
                onChange={(e) => setDescriptionFilter(e.target.value)}
              />
              <label className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={shortageOnly}
                  onChange={(e) => setShortageOnly(e.target.checked)}
                />
                Shortage only
              </label>
              <div className="flex items-center gap-2">
                <input
                  className="input"
                  type="number"
                  value={shortageThreshold}
                  onChange={(e) => setShortageThreshold(e.target.value)}
                  disabled={!shortageOnly}
                />
                <button
                  type="button"
                  className="button-secondary"
                  onClick={() => {
                    setQuery("");
                    setLocationFilter(ALL_FILTER);
                    setCategoryFilter(ALL_FILTER);
                    setShortageOnly(false);
                    setShortageThreshold("0");
                    setDescriptionFilter("");
                  }}
                >
                  Clear
                </button>
              </div>
            </div>
            <p className="mb-3 text-xs text-slate-500">
              {shortageOnly ? `Showing rows with quantity ≤ ${shortageThreshold || "0"}.` : "Shortage filter is off."}
            </p>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("item_number")}>Item {sortIndicator("item_number")}</button></th>
                    <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("location")}>Location {sortIndicator("location")}</button></th>
                    <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("quantity")}>Quantity {sortIndicator("quantity")}</button></th>
                    {data.basis === "net_available" && <th className="px-2 py-2">Allocated</th>}
                    {data.basis === "net_available" && <th className="px-2 py-2">Reservations</th>}
                    {data.basis === "net_available" && <th className="px-2 py-2">Projects</th>}
                    <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("category")}>Category {sortIndicator("category")}</button></th>
                    <th className="px-2 py-2">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSortedRows.map((row) => (
                    <tr key={`${row.item_id}-${row.location}`} className="border-b border-slate-100">
                      <td className="px-2 py-2">{row.item_number}</td>
                      <td className="px-2 py-2">{row.location}</td>
                      <td className="px-2 py-2">{row.quantity}</td>
                      {data.basis === "net_available" && <td className="px-2 py-2">{row.allocated_quantity}</td>}
                      {data.basis === "net_available" && <td className="px-2 py-2">{row.active_reservation_count}</td>}
                      {data.basis === "net_available" && (
                        <td className="px-2 py-2 text-slate-600">
                          {row.allocated_project_names.length ? row.allocated_project_names.join(", ") : "-"}
                        </td>
                      )}
                      <td className="px-2 py-2">{row.category ?? "-"}</td>
                      <td className="px-2 py-2 text-slate-600">{row.description ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
