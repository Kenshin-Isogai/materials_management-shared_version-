import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { apiGet, apiGetAllPages, apiGetWithPagination, apiSend } from "../lib/api";
import { areRfqLineDraftsEqual, type RfqLineDraft } from "../lib/editorDrafts";
import {
  buildLineDraftMap,
  createRfqBatchBaseline,
  mergeRehydratedLineDrafts,
  orderVisibleRfqLines,
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
  const [statusFilter, setStatusFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [selectedBatchId, setSelectedBatchId] = useState("");
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

  const orderOptionItemIds = useMemo(() => {
    const itemIds = new Set<number>();
    for (const line of detailData?.lines ?? []) {
      itemIds.add(line.item_id);
    }
    return Array.from(itemIds).sort((left, right) => left - right);
  }, [detailData?.lines]);

  const linkedOrderIds = useMemo(() => {
    const orderIds = new Set<number>();
    for (const line of detailData?.lines ?? []) {
      if (line.linked_order_id != null) {
        orderIds.add(line.linked_order_id);
      }
    }
    return Array.from(orderIds).sort((left, right) => left - right);
  }, [detailData?.lines]);

  const orderOptionsKey = useMemo(() => {
    if (!active || !detailData) return null;
    return `rfq-order-options:${orderOptionItemIds.join(",")}:${linkedOrderIds.join(",")}`;
  }, [active, detailData, linkedOrderIds, orderOptionItemIds]);

  const { data: orderOptions = [], mutate: mutateOrders } = useSWR(orderOptionsKey, async () => {
    const orderMap = new Map<number, Order>();
    const orderGroups = await Promise.all(
      orderOptionItemIds.map((itemId) =>
        apiGetAllPages<Order>(`/orders?item_id=${itemId}&include_arrived=false&per_page=200`),
      ),
    );
    for (const group of orderGroups) {
      for (const order of group) {
        orderMap.set(order.order_id, order);
      }
    }
    const missingLinkedIds = linkedOrderIds.filter((orderId) => !orderMap.has(orderId));
    if (missingLinkedIds.length) {
      const linkedOrders = await Promise.all(
        missingLinkedIds.map(async (orderId) => {
          try {
            return await apiGet<Order>(`/orders/${orderId}`);
          } catch {
            return null;
          }
        }),
      );
      for (const order of linkedOrders) {
        if (order) {
          orderMap.set(order.order_id, order);
        }
      }
    }
    return Array.from(orderMap.values()).sort((left, right) => right.order_id - left.order_id);
  });

  const ordersByItemId = useMemo(() => {
    const index = new Map<number, Order[]>();
    for (const order of orderOptions) {
      const current = index.get(order.item_id);
      if (current) {
        current.push(order);
      } else {
        index.set(order.item_id, [order]);
      }
    }
    return index;
  }, [orderOptions]);

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
        setPendingBatchRehydrate(false);
        setPendingLineRehydrateIds([]);
      }
      return;
    }
    const serverLineDrafts = buildLineDraftMap(detailData.lines);
    const serverBatchBaseline = createRfqBatchBaseline(detailData);
    if (loadedBatchId !== detailData.rfq_id) {
      setBatchTitle(serverBatchBaseline.title);
      setBatchStatus(serverBatchBaseline.status);
      setBatchNote(serverBatchBaseline.note);
      setLineDrafts(serverLineDrafts);
      setBatchBaseline(serverBatchBaseline);
      setLineDraftBaseline(serverLineDrafts);
      setPendingBatchRehydrate(false);
      setPendingLineRehydrateIds([]);
      setLoadedBatchId(detailData.rfq_id);
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
    setPendingBatchRehydrate(false);
    setPendingLineRehydrateIds([]);
    setLoadedBatchId(detailData.rfq_id);
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
        mutateOrders(),
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
                        {visibleLines.map((line) => {
                          const draft = lineDrafts[line.line_id];
                          const isHighlightedLine =
                            highlightedItemId != null && line.item_id === highlightedItemId;
                          const matchingOrders = ordersByItemId.get(line.item_id) ?? [];

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
                                  value={draft?.linked_order_id ?? ""}
                                  onChange={(event) =>
                                    updateLineDraft(line.line_id, { linked_order_id: event.target.value })
                                  }
                                >
                                  <option value="">No linked order</option>
                                  {matchingOrders.map((order) => (
                                    <option key={order.order_id} value={order.order_id}>
                                      #{order.order_id} / {order.supplier_name} / qty {order.order_amount} / ETA{" "}
                                      {order.expected_arrival ?? "-"}
                                      {order.project_name ? ` / ${order.project_name}` : ""}
                                    </option>
                                  ))}
                                </select>
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
                        {!visibleLines.length && (
                          <tr>
                            <td className="px-2 py-5 text-slate-500" colSpan={10}>
                              No matching RFQ lines in this batch.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
