import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { apiGet, apiGetAllPages, apiGetWithPagination, apiSend } from "../lib/api";
import { areRfqLineDraftsEqual, type RfqLineDraft } from "../lib/editorDrafts";
import {
  buildLinkedOrderSelectOptions,
  buildLineDraftMap,
  createRfqBatchBaseline,
  mergeRehydratedLineDrafts,
  orderVisibleRfqLines,
  paginateRfqLines,
} from "../lib/rfqEditorState";
import type {
  Order,
  ProjectRow,
  RfqBatchDetail,
  RfqBatchStatus,
  RfqBatchSummary,
  RfqLine,
} from "../lib/types";

type RfqBatchEditorProps = {
  fixedProjectId?: number | null;
  highlightedItemId?: number | null;
  title?: string;
  showFilters?: boolean;
  onDirtyChange?: (isDirty: boolean) => void;
  onSaved?: () => Promise<void> | void;
  onOpenItem?: (itemId: number, label: string) => void;
  active?: boolean;
};

function messageFromError(prefix: string, error: unknown): string {
  const text = error instanceof Error ? error.message : String(error ?? "");
  return text.trim() ? `${prefix}: ${text}` : prefix;
}

export function RfqBatchEditor({
  fixedProjectId = null,
  highlightedItemId = null,
  title,
  showFilters = true,
  onDirtyChange,
  onSaved,
  onOpenItem,
  active = true,
}: RfqBatchEditorProps) {
  const linePageSizeOptions = [25, 50, 100] as const;
  const [statusFilter, setStatusFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [linePage, setLinePage] = useState(1);
  const [linePageSize, setLinePageSize] = useState<(typeof linePageSizeOptions)[number]>(25);
  const [batchTitle, setBatchTitle] = useState("");
  const [batchStatus, setBatchStatus] = useState<RfqBatchStatus>("OPEN");
  const [batchNote, setBatchNote] = useState("");
  const [lineDrafts, setLineDrafts] = useState<Record<number, RfqLineDraft>>({});
  const [batchBaseline, setBatchBaseline] = useState<{
    title: string;
    status: RfqBatchStatus;
    note: string;
  }>({
    title: "",
    status: "OPEN",
    note: "",
  });
  const [lineDraftBaseline, setLineDraftBaseline] = useState<Record<number, RfqLineDraft>>({});
  const [loadedBatchId, setLoadedBatchId] = useState<number | null>(null);
  const [pendingBatchRehydrate, setPendingBatchRehydrate] = useState(false);
  const [pendingLineRehydrateIds, setPendingLineRehydrateIds] = useState<number[]>([]);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [activeLinkedOrderLineId, setActiveLinkedOrderLineId] = useState<number | null>(null);
  const [loadedOrdersByItemId, setLoadedOrdersByItemId] = useState<Record<number, Order[]>>({});
  const [loadingOrdersByItemId, setLoadingOrdersByItemId] = useState<Record<number, boolean>>({});
  const [orderLoadErrorsByItemId, setOrderLoadErrorsByItemId] = useState<Record<number, string>>({});

  useEffect(() => {
    if (fixedProjectId == null) return;
    setProjectFilter(String(fixedProjectId));
  }, [fixedProjectId]);

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("per_page", "500");
    const effectiveProjectId = fixedProjectId != null ? String(fixedProjectId) : projectFilter;
    if (statusFilter) params.set("status", statusFilter);
    if (effectiveProjectId) params.set("project_id", effectiveProjectId);
    return `/rfq-batches?${params.toString()}`;
  }, [fixedProjectId, projectFilter, statusFilter]);

  const {
    data: batchesResp,
    error: batchesError,
    isLoading: batchesLoading,
    mutate: mutateBatches,
  } = useSWR(active ? listPath : null, () => apiGetWithPagination<RfqBatchSummary[]>(listPath));
  const { data: projectsResp } = useSWR(active && showFilters ? "/rfq-project-options-editor" : null, () =>
    apiGetWithPagination<ProjectRow[]>("/projects?per_page=500"),
  );

  const batches = batchesResp?.data ?? [];
  const projects = projectsResp?.data ?? [];

  useEffect(() => {
    setActiveLinkedOrderLineId(null);
    setLoadedOrdersByItemId({});
    setLoadingOrdersByItemId({});
    setOrderLoadErrorsByItemId({});
    setLinePage(1);
  }, [selectedBatchId]);

  useEffect(() => {
    setLinePage(1);
  }, [highlightedItemId]);

  useEffect(() => {
    if (!active && !batchesResp) return;
    if (!selectedBatchId && batches.length) {
      setSelectedBatchId(String(batches[0].rfq_id));
      return;
    }
    if (selectedBatchId && !batches.some((batch) => String(batch.rfq_id) === selectedBatchId)) {
      setSelectedBatchId(batches.length ? String(batches[0].rfq_id) : "");
    }
  }, [active, batches, batchesResp, selectedBatchId]);

  const detailKey = selectedBatchId ? `/rfq-batches/${selectedBatchId}` : null;
  const {
    data: detailData,
    error: detailError,
    isLoading: detailLoading,
    mutate: mutateDetail,
  } = useSWR(active ? detailKey : null, () => apiGet<RfqBatchDetail>(detailKey ?? ""));

  useEffect(() => {
    if (!detailData) {
      if (!detailKey) {
        setLoadedBatchId(null);
        setBatchTitle("");
        setBatchStatus("OPEN");
        setBatchNote("");
        setLineDrafts({});
        setBatchBaseline({ title: "", status: "OPEN", note: "" });
        setLineDraftBaseline({});
        setPendingBatchRehydrate((c) => (c ? false : c));
        setPendingLineRehydrateIds((c) => (c.length ? [] : c));
      }
      return;
    }
    const serverLineDrafts = buildLineDraftMap(detailData.lines);
    const serverBatchBaseline = createRfqBatchBaseline(detailData);
    const serverBatchId = detailData.rfq_id ?? null;
    if (loadedBatchId !== serverBatchId) {
      setBatchTitle(serverBatchBaseline.title);
      setBatchStatus(serverBatchBaseline.status);
      setBatchNote(serverBatchBaseline.note);
      setLineDrafts(serverLineDrafts);
      setBatchBaseline(serverBatchBaseline);
      setLineDraftBaseline(serverLineDrafts);
      setPendingBatchRehydrate(false);
      setPendingLineRehydrateIds([]);
      setLoadedBatchId(serverBatchId);
      return;
    }
    if (!pendingBatchRehydrate && !pendingLineRehydrateIds.length) return;
    if (pendingBatchRehydrate) {
      setBatchTitle(serverBatchBaseline.title);
      setBatchStatus(serverBatchBaseline.status);
      setBatchNote(serverBatchBaseline.note);
      setBatchBaseline(serverBatchBaseline);
    }
    if (pendingLineRehydrateIds.length) {
      const rehydrated = mergeRehydratedLineDrafts(
        lineDrafts,
        lineDraftBaseline,
        serverLineDrafts,
        pendingLineRehydrateIds,
      );
      setLineDrafts(rehydrated.drafts);
      setLineDraftBaseline(rehydrated.baseline);
    }
    setPendingBatchRehydrate((c) => (c ? false : c));
    setPendingLineRehydrateIds((c) => (c.length ? [] : c));
    setLoadedBatchId(serverBatchId);
  }, [detailData, detailKey, loadedBatchId, pendingBatchRehydrate, pendingLineRehydrateIds]);

  function updateLineDraft(lineId: number, patch: Partial<RfqLineDraft>) {
    setLineDrafts((current) => ({
      ...current,
      [lineId]: {
        ...current[lineId],
        ...patch,
      },
    }));
  }

  const visibleLines = useMemo(() => {
    if (!detailData) return [];
    return orderVisibleRfqLines(detailData.lines, highlightedItemId);
  }, [detailData, highlightedItemId]);

  const totalLinePages = Math.max(1, Math.ceil(visibleLines.length / linePageSize));
  const currentLinePage = Math.min(linePage, totalLinePages);
  const pagedLines = useMemo(
    () => paginateRfqLines(visibleLines, currentLinePage, linePageSize),
    [currentLinePage, linePageSize, visibleLines],
  );
  const pageStartLine = visibleLines.length ? (currentLinePage - 1) * linePageSize + 1 : 0;
  const pageEndLine = visibleLines.length
    ? Math.min(visibleLines.length, pageStartLine + pagedLines.length - 1)
    : 0;

  useEffect(() => {
    if (linePage > totalLinePages) {
      setLinePage(totalLinePages);
    }
  }, [linePage, totalLinePages]);

  const isDirty = useMemo(() => {
    const batchChanged =
      batchTitle !== batchBaseline.title ||
      batchStatus !== batchBaseline.status ||
      batchNote !== batchBaseline.note;
    const lineChanged = Object.keys(lineDrafts).some((lineId) => {
      const numericLineId = Number(lineId);
      return !areRfqLineDraftsEqual(lineDrafts[numericLineId], lineDraftBaseline[numericLineId]);
    });
    return batchChanged || lineChanged;
  }, [batchBaseline.note, batchBaseline.status, batchBaseline.title, batchNote, batchStatus, batchTitle, lineDraftBaseline, lineDrafts]);

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  function parseLinkedOrderId(value: string): number | null {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }

  async function loadOrdersForItem(itemId: number, requiredOrderId: number | null, force = false) {
    if (!active) return;
    const cachedOrders = loadedOrdersByItemId[itemId] ?? [];
    const hasLoadedOrders = Object.prototype.hasOwnProperty.call(loadedOrdersByItemId, itemId);
    const hasRequiredOrder =
      requiredOrderId == null || cachedOrders.some((order) => order.order_id === requiredOrderId);
    if (!force && (loadingOrdersByItemId[itemId] || (hasLoadedOrders && hasRequiredOrder))) {
      return;
    }

    setLoadingOrdersByItemId((current) => ({ ...current, [itemId]: true }));
    setOrderLoadErrorsByItemId((current) => {
      if (!current[itemId]) return current;
      const next = { ...current };
      delete next[itemId];
      return next;
    });

    try {
      const orderMap = new Map<number, Order>();
      for (const order of force ? [] : cachedOrders) {
        orderMap.set(order.order_id, order);
      }

      const matchingOrders = await apiGetAllPages<Order>(`/orders?item_id=${itemId}&include_arrived=false&per_page=200`);
      for (const order of matchingOrders) {
        orderMap.set(order.order_id, order);
      }

      if (requiredOrderId != null && !orderMap.has(requiredOrderId)) {
        try {
          const requiredOrder = await apiGet<Order>(`/orders/${requiredOrderId}`);
          orderMap.set(requiredOrder.order_id, requiredOrder);
        } catch {
          // Keep the current linked-order selection visible via fallback option metadata.
        }
      }

      setLoadedOrdersByItemId((current) => ({
        ...current,
        [itemId]: Array.from(orderMap.values()).sort((left, right) => right.order_id - left.order_id),
      }));
    } catch (error) {
      setOrderLoadErrorsByItemId((current) => ({
        ...current,
        [itemId]: messageFromError("Linked order load failed", error),
      }));
    } finally {
      setLoadingOrdersByItemId((current) => {
        if (!current[itemId]) return current;
        const next = { ...current };
        delete next[itemId];
        return next;
      });
    }
  }

  async function saveBatch() {
    if (!selectedBatchId) return;
    setWorking(true);
    setMessage("");
    try {
      await apiSend(`/rfq-batches/${selectedBatchId}`, {
        method: "PUT",
        body: JSON.stringify({
          title: batchTitle.trim(),
          status: batchStatus,
          note: batchNote.trim() || null,
        }),
      });
      setPendingBatchRehydrate(true);
      setMessage(`Updated RFQ batch #${selectedBatchId}.`);
      await Promise.all([mutateDetail(), mutateBatches(), onSaved?.() ?? Promise.resolve()]);
    } catch (error) {
      setMessage(messageFromError("Batch update failed", error));
    } finally {
      setWorking(false);
    }
  }

  async function saveLine(line: RfqLine) {
    const draft = lineDrafts[line.line_id];
    if (!draft) return;
    const selectedLinkedOrderId = parseLinkedOrderId(draft.linked_order_id);
    setWorking(true);
    setMessage("");
    try {
      await apiSend(`/rfq-lines/${line.line_id}`, {
        method: "PUT",
        body: JSON.stringify({
          requested_quantity: Number(draft.requested_quantity),
          finalized_quantity: Number(draft.finalized_quantity),
          supplier_name: draft.supplier_name.trim() || null,
          lead_time_days: draft.lead_time_days.trim() ? Number(draft.lead_time_days) : null,
          expected_arrival: draft.expected_arrival.trim() || null,
          linked_order_id: draft.linked_order_id.trim() ? Number(draft.linked_order_id) : null,
          status: draft.status,
          note: draft.note.trim() || null,
        }),
      });
      setPendingLineRehydrateIds((current) =>
        current.includes(line.line_id) ? current : [...current, line.line_id],
      );
      setMessage(`Updated RFQ line #${line.line_id}.`);
      await Promise.all([
        mutateDetail(),
        mutateBatches(),
        loadOrdersForItem(line.item_id, selectedLinkedOrderId, true),
        onSaved?.() ?? Promise.resolve(),
      ]);
    } catch (error) {
      setMessage(messageFromError("Line update failed", error));
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="space-y-4">
      {title && <h2 className="font-display text-lg font-semibold">{title}</h2>}

      {showFilters && (
        <section className="panel p-4">
          <h3 className="mb-3 font-display text-lg font-semibold">Filter Batches</h3>
          <div className="grid gap-3 md:grid-cols-2">
            <select className="input" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">All status</option>
              <option value="OPEN">OPEN</option>
              <option value="CLOSED">CLOSED</option>
              <option value="CANCELLED">CANCELLED</option>
            </select>
            <select className="input" value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)}>
              <option value="">All projects</option>
              {projects.map((project) => (
                <option key={project.project_id} value={project.project_id}>
                  #{project.project_id} {project.name}
                </option>
              ))}
            </select>
          </div>
          {!!message && <p className="mt-3 text-sm text-slate-700">{message}</p>}
        </section>
      )}

      {!showFilters && !!message && (
        <p className="text-sm text-slate-700">{message}</p>
      )}

      <section className="grid gap-4 xl:grid-cols-[320px,minmax(0,1fr)]">
        <section className="panel p-4">
          <h3 className="mb-3 font-display text-lg font-semibold">Batch List</h3>
          {batchesLoading && <p className="text-sm text-slate-500">Loading RFQ batches...</p>}
          {batchesError && <p className="text-sm text-red-600">{String(batchesError)}</p>}
          <div className="space-y-3">
            {batches.map((batch) => {
              const active = String(batch.rfq_id) === selectedBatchId;
              return (
                <button
                  key={batch.rfq_id}
                  type="button"
                  className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                    active
                      ? "border-slate-800 bg-slate-800 text-white"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                  onClick={() => setSelectedBatchId(String(batch.rfq_id))}
                >
                  <p className="text-sm font-semibold">
                    #{batch.rfq_id} {batch.title}
                  </p>
                  <p className={`mt-1 text-xs ${active ? "text-slate-200" : "text-slate-500"}`}>
                    {batch.project_name} / target {batch.target_date ?? "-"} / {batch.status}
                  </p>
                  <div
                    className={`mt-3 grid grid-cols-3 gap-2 text-xs ${
                      active ? "text-slate-100" : "text-slate-600"
                    }`}
                  >
                    <div className="rounded-xl bg-black/5 px-2 py-2">
                      <p className="font-semibold">Lines</p>
                      <p>{batch.line_count}</p>
                    </div>
                    <div className="rounded-xl bg-black/5 px-2 py-2">
                      <p className="font-semibold">Quoted</p>
                      <p>{batch.quoted_line_count}</p>
                    </div>
                    <div className="rounded-xl bg-black/5 px-2 py-2">
                      <p className="font-semibold">Ordered</p>
                      <p>{batch.ordered_line_count}</p>
                    </div>
                  </div>
                </button>
              );
            })}
            {!batches.length && !batchesLoading && (
              <p className="text-sm text-slate-500">No RFQ batches.</p>
            )}
          </div>
        </section>

        <div className="space-y-4">
          {!selectedBatchId && (
            <section className="panel p-6">
              <p className="text-sm text-slate-500">Select an RFQ batch to review or update line details.</p>
            </section>
          )}

          {selectedBatchId && (
            <>
              <section className="panel p-4">
                {detailLoading && <p className="text-sm text-slate-500">Loading RFQ details...</p>}
                {detailError && <p className="text-sm text-red-600">{String(detailError)}</p>}
                {detailData && (
                  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr),auto]">
                    <div className="grid gap-3 md:grid-cols-3">
                      <input
                        className="input md:col-span-2"
                        value={batchTitle}
                        onChange={(event) => setBatchTitle(event.target.value)}
                        placeholder="Batch title"
                      />
                      <select
                        className="input"
                        value={batchStatus}
                        onChange={(event) => setBatchStatus(event.target.value as RfqBatchStatus)}
                      >
                        <option value="OPEN">OPEN</option>
                        <option value="CLOSED">CLOSED</option>
                        <option value="CANCELLED">CANCELLED</option>
                      </select>
                      <input
                        className="input md:col-span-3"
                        value={batchNote}
                        onChange={(event) => setBatchNote(event.target.value)}
                        placeholder="Batch note"
                      />
                    </div>
                    <div className="min-w-[220px] rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                      <p className="font-semibold">{detailData.project_name}</p>
                      <p>Target date: {detailData.target_date ?? "-"}</p>
                      <p>Total finalized qty: {detailData.finalized_quantity_total}</p>
                    </div>
                    <div className="lg:col-span-2">
                      <button className="button" type="button" disabled={working} onClick={saveBatch}>
                        Save Batch
                      </button>
                    </div>
                  </div>
                )}
              </section>

              <section className="panel p-4">
                {detailData && (
                  <>
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 text-sm">
                      <p className="text-slate-600">
                        Showing {pageStartLine || 0}-{pageEndLine || 0} of {visibleLines.length} RFQ lines.
                      </p>
                      <div className="flex flex-wrap items-center gap-2">
                        <label className="text-xs font-semibold uppercase tracking-wide text-slate-500" htmlFor="rfq-page-size">
                          Rows
                        </label>
                        <select
                          id="rfq-page-size"
                          className="input w-auto"
                          value={linePageSize}
                          onChange={(event) => {
                            setLinePageSize(Number(event.target.value) as (typeof linePageSizeOptions)[number]);
                            setLinePage(1);
                          }}
                        >
                          {linePageSizeOptions.map((option) => (
                            <option key={option} value={option}>
                              {option} / page
                            </option>
                          ))}
                        </select>
                        <button
                          className="button-subtle"
                          type="button"
                          disabled={currentLinePage <= 1}
                          onClick={() => setLinePage((current) => Math.max(1, current - 1))}
                        >
                          Previous
                        </button>
                        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                          Page {currentLinePage} / {totalLinePages}
                        </span>
                        <button
                          className="button-subtle"
                          type="button"
                          disabled={currentLinePage >= totalLinePages}
                          onClick={() => setLinePage((current) => Math.min(totalLinePages, current + 1))}
                        >
                          Next
                        </button>
                      </div>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="min-w-[1480px] text-sm">
                        <thead>
                          <tr className="border-b border-slate-200 text-left text-slate-500">
                            <th className="px-2 py-2">Item</th>
                            <th className="px-2 py-2">Requested</th>
                            <th className="px-2 py-2">Finalized</th>
                            <th className="px-2 py-2">Supplier</th>
                            <th className="px-2 py-2">Lead Days</th>
                            <th className="px-2 py-2">Expected Arrival</th>
                            <th className="px-2 py-2">Status</th>
                            <th className="px-2 py-2">Linked Order</th>
                            <th className="px-2 py-2">Note</th>
                            <th className="px-2 py-2">Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pagedLines.map((line) => {
                            const draft = lineDrafts[line.line_id];
                            const isHighlightedLine =
                              highlightedItemId != null && line.item_id === highlightedItemId;
                            const isLinkedOrderSelectActive = activeLinkedOrderLineId === line.line_id;
                            const matchingOrders = loadedOrdersByItemId[line.item_id] ?? [];
                            const orderLoadError = orderLoadErrorsByItemId[line.item_id] ?? null;
                            const orderOptions = buildLinkedOrderSelectOptions({
                              line,
                              draftLinkedOrderId: draft?.linked_order_id ?? "",
                              matchingOrders,
                              isActive: isLinkedOrderSelectActive,
                              isLoading: Boolean(loadingOrdersByItemId[line.item_id]),
                              loadError: orderLoadError,
                            });

                            return (
                              <tr
                                key={line.line_id}
                                className={`border-b border-slate-100 align-top ${
                                  isHighlightedLine ? "bg-amber-50/60" : ""
                                }`}
                              >
                                <td className="px-2 py-2">
                                  <p className="font-semibold">{line.item_number}</p>
                                  <p className="text-xs text-slate-500">{line.manufacturer_name}</p>
                                  <p className="text-xs text-slate-400">line #{line.line_id}</p>
                                  {isHighlightedLine && (
                                    <p className="mt-1 text-xs font-semibold text-amber-800">Focused item</p>
                                  )}
                                  {onOpenItem && (
                                    <button
                                      className="mt-2 button-subtle"
                                      type="button"
                                      onClick={() => onOpenItem(line.item_id, line.item_number)}
                                    >
                                      Open Item
                                    </button>
                                  )}
                                </td>
                                <td className="px-2 py-2">
                                  <input
                                    className="input"
                                    type="number"
                                    min={1}
                                    value={draft?.requested_quantity ?? ""}
                                    onChange={(event) =>
                                      updateLineDraft(line.line_id, { requested_quantity: event.target.value })
                                    }
                                  />
                                </td>
                                <td className="px-2 py-2">
                                  <input
                                    className="input"
                                    type="number"
                                    min={1}
                                    value={draft?.finalized_quantity ?? ""}
                                    onChange={(event) =>
                                      updateLineDraft(line.line_id, { finalized_quantity: event.target.value })
                                    }
                                  />
                                </td>
                                <td className="px-2 py-2">
                                  <input
                                    className="input"
                                    value={draft?.supplier_name ?? ""}
                                    onChange={(event) =>
                                      updateLineDraft(line.line_id, { supplier_name: event.target.value })
                                    }
                                    placeholder="Supplier name"
                                  />
                                </td>
                                <td className="px-2 py-2">
                                  <input
                                    className="input"
                                    type="number"
                                    min={0}
                                    value={draft?.lead_time_days ?? ""}
                                    onChange={(event) =>
                                      updateLineDraft(line.line_id, { lead_time_days: event.target.value })
                                    }
                                  />
                                </td>
                                <td className="px-2 py-2">
                                  <div className="space-y-2">
                                    <input
                                      className="input"
                                      type="date"
                                      value={draft?.expected_arrival ?? ""}
                                      onChange={(event) =>
                                        updateLineDraft(line.line_id, { expected_arrival: event.target.value })
                                      }
                                    />
                                    {line.linked_order_expected_arrival && (
                                      <p className="text-xs text-slate-500">
                                        Linked order ETA: {line.linked_order_expected_arrival}
                                      </p>
                                    )}
                                  </div>
                                </td>
                                <td className="px-2 py-2">
                                  <select
                                    className="input"
                                    value={draft?.status ?? line.status}
                                    onChange={(event) =>
                                      updateLineDraft(line.line_id, {
                                        status: event.target.value as RfqLine["status"],
                                      })
                                    }
                                  >
                                    <option value="DRAFT">DRAFT</option>
                                    <option value="SENT">SENT</option>
                                    <option value="QUOTED">QUOTED</option>
                                    <option value="ORDERED">ORDERED</option>
                                    <option value="CANCELLED">CANCELLED</option>
                                  </select>
                                </td>
                                <td className="px-2 py-2">
                                  <select
                                    className="input"
                                    title="Focus to load matching open orders for this item."
                                    value={draft?.linked_order_id ?? ""}
                                    onBlur={() =>
                                      setActiveLinkedOrderLineId((current) =>
                                        current === line.line_id ? null : current,
                                      )
                                    }
                                    onChange={(event) =>
                                      updateLineDraft(line.line_id, { linked_order_id: event.target.value })
                                    }
                                    onFocus={() => {
                                      setActiveLinkedOrderLineId(line.line_id);
                                      void loadOrdersForItem(
                                        line.item_id,
                                        parseLinkedOrderId(draft?.linked_order_id ?? ""),
                                      );
                                    }}
                                  >
                                    {orderOptions.map((option) => (
                                      <option key={option.value} disabled={option.disabled} value={option.value}>
                                        {option.label}
                                      </option>
                                    ))}
                                  </select>
                                  {isLinkedOrderSelectActive && orderLoadError && (
                                    <p className="mt-2 text-xs text-red-600">{orderLoadError}</p>
                                  )}
                                  {(line.linked_quotation_number || line.linked_order_supplier_name) && (
                                    <p className="mt-2 text-xs text-slate-500">
                                      {line.linked_order_supplier_name ?? "-"} / {line.linked_quotation_number ?? "-"}
                                    </p>
                                  )}
                                </td>
                                <td className="px-2 py-2">
                                  <textarea
                                    className="input min-h-[88px]"
                                    value={draft?.note ?? ""}
                                    onChange={(event) => updateLineDraft(line.line_id, { note: event.target.value })}
                                    placeholder="Line note"
                                  />
                                </td>
                                <td className="px-2 py-2">
                                  <button
                                    className="button-subtle"
                                    type="button"
                                    disabled={working || !draft}
                                    onClick={() => void saveLine(line)}
                                  >
                                    Save Line
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                          {!pagedLines.length && (
                            <tr>
                              <td className="px-2 py-5 text-slate-500" colSpan={10}>
                                No matching RFQ lines in this batch.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </section>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
