import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { apiGetAllPages, apiSend } from "../lib/api";
import type { ArrivalScheduleEntry } from "../lib/types";

type ArrivalBucketFilter = "all" | "overdue" | "scheduled" | "no_eta";
type SupplyScope = "all" | "generic" | "dedicated";

function renderDocumentLink(url: string | null | undefined, label = "Open document") {
  if (!url) return "-";
  return (
    <a className="text-sky-700 underline underline-offset-2" href={url} target="_blank" rel="noreferrer noopener">
      {label}
    </a>
  );
}

function summaryMetric(
  label: string,
  value: string | number,
  tone: "slate" | "sky" | "emerald" | "amber" | "rose" = "slate"
) {
  const toneClass =
    tone === "sky"
      ? "border-sky-200 bg-sky-50 text-sky-900"
      : tone === "emerald"
        ? "border-emerald-200 bg-emerald-50 text-emerald-900"
        : tone === "amber"
          ? "border-amber-200 bg-amber-50 text-amber-900"
          : tone === "rose"
            ? "border-rose-200 bg-rose-50 text-rose-900"
            : "border-slate-200 bg-slate-50 text-slate-900";
  return (
    <div className={`rounded-xl border px-3 py-3 ${toneClass}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-bold">{value}</p>
    </div>
  );
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    weekday: "short",
  });
}

function arrivalStatusCopy(row: ArrivalScheduleEntry): string {
  if (row.arrival_bucket === "overdue") {
    return `${row.overdue_days} day${row.overdue_days === 1 ? "" : "s"} overdue`;
  }
  if (row.arrival_bucket === "no_eta") {
    return "ETA not set";
  }
  if (row.days_until_expected === 0) {
    return "Due today";
  }
  if ((row.days_until_expected ?? 0) > 0) {
    return `Due in ${row.days_until_expected} day${row.days_until_expected === 1 ? "" : "s"}`;
  }
  return "Scheduled";
}

function bucketTone(bucket: ArrivalScheduleEntry["arrival_bucket"]): string {
  switch (bucket) {
    case "overdue":
      return "border-rose-300 bg-rose-50";
    case "scheduled":
      return "border-sky-300 bg-sky-50";
    case "no_eta":
      return "border-amber-300 bg-amber-50";
    default:
      return "border-slate-200 bg-white";
  }
}

function groupScheduledRows(rows: ArrivalScheduleEntry[]): Array<{ date: string; rows: ArrivalScheduleEntry[] }> {
  const groups = new Map<string, ArrivalScheduleEntry[]>();
  rows.forEach((row) => {
    if (!row.expected_arrival) return;
    groups.set(row.expected_arrival, [...(groups.get(row.expected_arrival) ?? []), row]);
  });
  return Array.from(groups.entries())
    .sort((left, right) => left[0].localeCompare(right[0]))
    .map(([date, groupedRows]) => ({ date, rows: groupedRows }));
}

function ArrivalRowCard({
  row,
  selected,
  onSelect,
}: {
  row: ArrivalScheduleEntry;
  selected: boolean;
  onSelect: (orderId: number) => void;
}) {
  return (
    <button
      type="button"
      className={`w-full rounded-2xl border px-4 py-3 text-left transition hover:border-slate-300 ${selected ? bucketTone(row.arrival_bucket) : "border-slate-200 bg-white"}`}
      onClick={() => onSelect(row.order_id)}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-slate-900">
            Line #{row.order_id} · {row.canonical_item_number}
          </p>
          <p className="text-sm text-slate-600">
            {row.supplier_name} · PO #{row.purchase_order_id} · Quote {row.quotation_number}
          </p>
          <p className="text-xs text-slate-500">
            ETA {formatDate(row.expected_arrival)} · Qty {row.order_amount}
            {row.project_name ? ` · ${row.project_name}` : ""}
          </p>
        </div>
        <span className="rounded-full bg-white/80 px-2 py-1 text-xs font-semibold text-slate-700">
          {arrivalStatusCopy(row)}
        </span>
      </div>
    </button>
  );
}

export function ArrivalPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [bucketFilter, setBucketFilter] = useState<ArrivalBucketFilter>("all");
  const [supplyScope, setSupplyScope] = useState<SupplyScope>("all");
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
  const [partialArrivalQuantity, setPartialArrivalQuantity] = useState("");
  const [message, setMessage] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  const { data: arrivalsData, error, isLoading, mutate } = useSWR("/arrival-schedule", () =>
    apiGetAllPages<ArrivalScheduleEntry>("/arrival-schedule?per_page=200")
  );

  const filteredRows = useMemo(() => {
    const query = deferredSearch.trim().toLowerCase();
    return (arrivalsData ?? []).filter((row) => {
      if (bucketFilter !== "all" && row.arrival_bucket !== bucketFilter) return false;
      if (supplyScope === "generic" && row.project_id !== null) return false;
      if (supplyScope === "dedicated" && row.project_id === null) return false;
      if (!query) return true;
      return [
        row.order_id,
        row.purchase_order_id,
        row.quotation_number,
        row.canonical_item_number,
        row.ordered_item_number,
        row.supplier_name,
        row.project_name ?? "",
        row.expected_arrival ?? "",
      ]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [arrivalsData, bucketFilter, deferredSearch, supplyScope]);

  useEffect(() => {
    if (!filteredRows.length) {
      setSelectedOrderId(null);
      return;
    }
    if (!filteredRows.some((row) => row.order_id === selectedOrderId)) {
      setSelectedOrderId(filteredRows[0].order_id);
    }
  }, [filteredRows, selectedOrderId]);

  const selectedOrder = useMemo(
    () => filteredRows.find((row) => row.order_id === selectedOrderId) ?? null,
    [filteredRows, selectedOrderId]
  );
  const overdueRows = useMemo(() => filteredRows.filter((row) => row.arrival_bucket === "overdue"), [filteredRows]);
  const scheduledRows = useMemo(() => filteredRows.filter((row) => row.arrival_bucket === "scheduled"), [filteredRows]);
  const noEtaRows = useMemo(() => filteredRows.filter((row) => row.arrival_bucket === "no_eta"), [filteredRows]);
  const sameItemRows = useMemo(() => {
    if (!selectedOrder) return [];
    return filteredRows.filter((row) => row.item_id === selectedOrder.item_id && row.order_id !== selectedOrder.order_id);
  }, [filteredRows, selectedOrder]);
  const timelineGroups = useMemo(() => groupScheduledRows(scheduledRows), [scheduledRows]);
  const supplierCount = useMemo(() => new Set(filteredRows.map((row) => row.supplier_name)).size, [filteredRows]);

  async function refreshDataWithMessage(nextMessage: string) {
    await mutate();
    setMessage(nextMessage);
  }

  async function markArrived(orderId: number) {
    setActionLoading(true);
    setMessage("");
    try {
      await apiSend(`/purchase-order-lines/${orderId}/arrival`, { method: "POST", body: JSON.stringify({}) });
      await refreshDataWithMessage(`Marked order line #${orderId} as arrived.`);
      setPartialArrivalQuantity("");
    } catch (actionError) {
      setMessage(actionError instanceof Error ? actionError.message : String(actionError));
    } finally {
      setActionLoading(false);
    }
  }

  async function submitPartialArrival() {
    if (!selectedOrder) return;
    const parsedQuantity = Number.parseInt(partialArrivalQuantity, 10);
    if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) {
      setMessage("Enter a positive integer for partial arrival quantity.");
      return;
    }
    setActionLoading(true);
    setMessage("");
    try {
      await apiSend(`/purchase-order-lines/${selectedOrder.order_id}/partial-arrival`, {
        method: "POST",
        body: JSON.stringify({ quantity: parsedQuantity }),
      });
      await refreshDataWithMessage(
        `Recorded partial arrival of ${parsedQuantity} units for order line #${selectedOrder.order_id}.`
      );
      setPartialArrivalQuantity("");
    } catch (actionError) {
      setMessage(actionError instanceof Error ? actionError.message : String(actionError));
    } finally {
      setActionLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="font-display text-2xl font-semibold text-slate-900">Arrival</h1>
            <p className="mt-2 max-w-3xl text-sm text-slate-600">
              Track open arrivals by ETA, identify late lines, and process full or partial arrivals without mixing that
              workflow into the broader purchase-order ledger.
            </p>
          </div>
          <button type="button" className="button-subtle" onClick={() => navigate("/purchase-order-lines")}>
            Open Purchase Orders
          </button>
        </div>

        <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
          {summaryMetric("Open lines", arrivalsData?.length ?? 0, "sky")}
          {summaryMetric("Filtered", filteredRows.length, "slate")}
          {summaryMetric("Overdue", overdueRows.length, "rose")}
          {summaryMetric("No ETA", noEtaRows.length, "amber")}
          {summaryMetric("Suppliers", supplierCount, "emerald")}
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1.3fr)_minmax(18rem,0.7fr)]">
          <div className="space-y-3">
            <input
              className="input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by line #, PO #, item, supplier, quotation, project, or ETA"
            />
            <div className="flex flex-wrap gap-2">
              {[
                ["all", "All"],
                ["overdue", "Overdue"],
                ["scheduled", "Scheduled"],
                ["no_eta", "No ETA"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`rounded-full border px-3 py-1.5 text-sm font-semibold transition ${
                    bucketFilter === value
                      ? "border-sky-300 bg-sky-50 text-sky-700"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                  }`}
                  onClick={() => setBucketFilter(value as ArrivalBucketFilter)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Supply scope</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {[
                ["all", "All lines"],
                ["generic", "Generic supply"],
                ["dedicated", "Project-dedicated"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={`rounded-full border px-3 py-1.5 text-sm font-semibold transition ${
                    supplyScope === value
                      ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                  }`}
                  onClick={() => setSupplyScope(value as SupplyScope)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {message ? (
        <section className="panel p-4">
          <p className="text-sm text-slate-700">{message}</p>
        </section>
      ) : null}

      {isLoading ? (
        <section className="panel p-4">
          <p className="text-sm text-slate-500">Loading arrival schedule...</p>
        </section>
      ) : null}
      {error ? <ApiErrorNotice error={error} area="arrival schedule" /> : null}

      {!isLoading && !error ? (
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(20rem,0.8fr)]">
          <div className="panel p-4">
            <div className="space-y-5">
              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <h2 className="font-display text-lg font-semibold text-slate-900">Overdue</h2>
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{overdueRows.length} lines</span>
                </div>
                {overdueRows.length === 0 ? (
                  <p className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500">No overdue arrivals.</p>
                ) : (
                  <div className="space-y-2">
                    {overdueRows.map((row) => (
                      <ArrivalRowCard key={row.order_id} row={row} selected={row.order_id === selectedOrderId} onSelect={setSelectedOrderId} />
                    ))}
                  </div>
                )}
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <h2 className="font-display text-lg font-semibold text-slate-900">Scheduled</h2>
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{scheduledRows.length} lines</span>
                </div>
                {timelineGroups.length === 0 ? (
                  <p className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500">No dated arrivals match the current filters.</p>
                ) : (
                  <div className="space-y-4">
                    {timelineGroups.map((group) => (
                      <div key={group.date} className="space-y-2">
                        <div className="flex items-center justify-between gap-3">
                          <h3 className="text-sm font-semibold text-slate-900">{formatDate(group.date)}</h3>
                          <span className="text-xs text-slate-500">{group.rows.length} lines</span>
                        </div>
                        <div className="space-y-2">
                          {group.rows.map((row) => (
                            <ArrivalRowCard key={row.order_id} row={row} selected={row.order_id === selectedOrderId} onSelect={setSelectedOrderId} />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <h2 className="font-display text-lg font-semibold text-slate-900">No ETA</h2>
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{noEtaRows.length} lines</span>
                </div>
                {noEtaRows.length === 0 ? (
                  <p className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500">All remaining open lines have an ETA.</p>
                ) : (
                  <div className="space-y-2">
                    {noEtaRows.map((row) => (
                      <ArrivalRowCard key={row.order_id} row={row} selected={row.order_id === selectedOrderId} onSelect={setSelectedOrderId} />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="panel p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="font-display text-lg font-semibold text-slate-900">Arrival Details</h2>
            </div>
            {!selectedOrder ? (
              <p className="text-sm text-slate-500">Select an arrival line to inspect documents, ETA, and arrival actions.</p>
            ) : (
              <div className="space-y-4 text-sm">
                <div className="grid gap-2 md:grid-cols-2">
                  {summaryMetric("Line", `#${selectedOrder.order_id}`, "sky")}
                  {summaryMetric("Status", arrivalStatusCopy(selectedOrder), selectedOrder.arrival_bucket === "overdue" ? "rose" : selectedOrder.arrival_bucket === "no_eta" ? "amber" : "emerald")}
                  {summaryMetric("Qty", selectedOrder.order_amount, "slate")}
                  {summaryMetric("Supply", selectedOrder.project_id === null ? "Generic" : "Dedicated", selectedOrder.project_id === null ? "slate" : "emerald")}
                </div>

                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Item</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrder.canonical_item_number}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Supplier</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrder.supplier_name}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Purchase Order</p>
                      <p className="mt-1 font-medium text-slate-900">#{selectedOrder.purchase_order_id}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Quotation</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrder.quotation_number}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Order Date</p>
                      <p className="mt-1 font-medium text-slate-900">{formatDate(selectedOrder.order_date)}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Expected Arrival</p>
                      <p className="mt-1 font-medium text-slate-900">{formatDate(selectedOrder.expected_arrival)}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Project</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrder.project_name ?? "Generic supply"}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Ordered Item Number</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrder.ordered_item_number}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Quotation Document</p>
                      <p className="mt-1">{renderDocumentLink(selectedOrder.quotation_document_url)}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Purchase-order Document</p>
                      <p className="mt-1">{renderDocumentLink(selectedOrder.purchase_order_document_url)}</p>
                    </div>
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Arrival actions</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" className="button-subtle" disabled={actionLoading} onClick={() => markArrived(selectedOrder.order_id)}>
                      Mark Arrived
                    </button>
                    <button type="button" className="button-subtle" onClick={() => navigate("/purchase-order-lines")}>
                      Open Purchase Orders
                    </button>
                  </div>
                  <div className="mt-3 flex flex-wrap items-end gap-2">
                    <div>
                      <label className="text-xs font-semibold uppercase tracking-wide text-slate-500" htmlFor="partial-arrival-qty">
                        Partial arrival quantity
                      </label>
                      <input
                        id="partial-arrival-qty"
                        className="input mt-1 w-40"
                        type="number"
                        min={1}
                        max={selectedOrder.order_amount - 1}
                        value={partialArrivalQuantity}
                        onChange={(event) => setPartialArrivalQuantity(event.target.value)}
                        placeholder={`1-${Math.max(1, selectedOrder.order_amount - 1)}`}
                      />
                    </div>
                    <button type="button" className="button-subtle" disabled={actionLoading || selectedOrder.order_amount <= 1} onClick={submitPartialArrival}>
                      Record Partial Arrival
                    </button>
                  </div>
                  {selectedOrder.order_amount <= 1 ? <p className="mt-2 text-xs text-slate-500">Partial arrival is unavailable because this line quantity is 1.</p> : null}
                </div>

                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Same item, other open lines</p>
                    <span className="text-xs text-slate-500">{sameItemRows.length} lines</span>
                  </div>
                  {sameItemRows.length === 0 ? (
                    <p className="text-sm text-slate-500">No other open arrival lines for this item under the current filters.</p>
                  ) : (
                    <div className="space-y-2">
                      {sameItemRows.slice(0, 6).map((row) => (
                        <button key={row.order_id} type="button" className="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-left transition hover:border-slate-300" onClick={() => setSelectedOrderId(row.order_id)}>
                          <p className="font-semibold text-slate-900">Line #{row.order_id}</p>
                          <p className="text-sm text-slate-600">{row.supplier_name} · ETA {formatDate(row.expected_arrival)} · Qty {row.order_amount}</p>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}
