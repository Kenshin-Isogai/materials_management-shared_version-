import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { apiGetWithPagination, apiSend } from "../lib/api";
import type { Order } from "../lib/types";

type ProjectOption = {
  project_id: number;
  name: string;
  status: string;
  planned_start: string | null;
};

type RfqBatchSummary = {
  rfq_id: number;
  project_id: number;
  project_name: string;
  title: string;
  target_date: string | null;
  status: "OPEN" | "CLOSED" | "CANCELLED";
  note: string | null;
  line_count: number;
  finalized_quantity_total: number;
  quoted_line_count: number;
  ordered_line_count: number;
};

type RfqLine = {
  line_id: number;
  item_id: number;
  item_number: string;
  manufacturer_name: string;
  requested_quantity: number;
  finalized_quantity: number;
  supplier_name: string | null;
  lead_time_days: number | null;
  expected_arrival: string | null;
  linked_order_id: number | null;
  status: "DRAFT" | "SENT" | "QUOTED" | "ORDERED" | "CANCELLED";
  note: string | null;
  linked_order_project_id: number | null;
  linked_order_expected_arrival: string | null;
  linked_quotation_number: string | null;
  linked_order_supplier_name: string | null;
};

type RfqBatchDetail = RfqBatchSummary & {
  lines: RfqLine[];
};

type LineDraft = {
  requested_quantity: string;
  finalized_quantity: string;
  supplier_name: string;
  lead_time_days: string;
  expected_arrival: string;
  linked_order_id: string;
  status: RfqLine["status"];
  note: string;
};

export function RfqPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [batchTitle, setBatchTitle] = useState("");
  const [batchStatus, setBatchStatus] = useState<RfqBatchSummary["status"]>("OPEN");
  const [batchNote, setBatchNote] = useState("");
  const [lineDrafts, setLineDrafts] = useState<Record<number, LineDraft>>({});
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("per_page", "500");
    if (statusFilter) params.set("status", statusFilter);
    if (projectFilter) params.set("project_id", projectFilter);
    return `/rfq-batches?${params.toString()}`;
  }, [projectFilter, statusFilter]);

  const { data: batchesResp, error: batchesError, isLoading: batchesLoading, mutate: mutateBatches } = useSWR(
    listPath,
    () => apiGetWithPagination<RfqBatchSummary[]>(listPath)
  );
  const { data: projectsResp } = useSWR("/rfq-project-options", () =>
    apiGetWithPagination<ProjectOption[]>("/projects?per_page=500")
  );
  const { data: ordersResp, mutate: mutateOrders } = useSWR("/rfq-open-orders", () =>
    apiGetWithPagination<Order[]>("/orders?include_arrived=false&per_page=500")
  );

  const batches = batchesResp?.data ?? [];
  const projects = projectsResp?.data ?? [];
  const openOrders = ordersResp?.data ?? [];

  useEffect(() => {
    if (!selectedBatchId && batches.length) {
      setSelectedBatchId(String(batches[0].rfq_id));
    }
    if (selectedBatchId && !batches.some((batch) => String(batch.rfq_id) === selectedBatchId)) {
      setSelectedBatchId(batches.length ? String(batches[0].rfq_id) : "");
    }
  }, [batches, selectedBatchId]);

  const detailKey = selectedBatchId ? `/rfq-batches/${selectedBatchId}` : null;
  const {
    data: detailData,
    error: detailError,
    isLoading: detailLoading,
    mutate: mutateDetail,
  } = useSWR(detailKey, () => apiSend<RfqBatchDetail>(detailKey ?? "", { method: "GET" }));

  useEffect(() => {
    if (!detailData) return;
    setBatchTitle(detailData.title);
    setBatchStatus(detailData.status);
    setBatchNote(detailData.note ?? "");
    setLineDrafts(
      Object.fromEntries(
        detailData.lines.map((line) => [
          line.line_id,
          {
            requested_quantity: String(line.requested_quantity),
            finalized_quantity: String(line.finalized_quantity),
            supplier_name: line.supplier_name ?? "",
            lead_time_days: line.lead_time_days == null ? "" : String(line.lead_time_days),
            expected_arrival: line.expected_arrival ?? "",
            linked_order_id: line.linked_order_id == null ? "" : String(line.linked_order_id),
            status: line.status,
            note: line.note ?? "",
          }
        ])
      )
    );
  }, [detailData]);

  function updateLineDraft(lineId: number, patch: Partial<LineDraft>) {
    setLineDrafts((current) => ({
      ...current,
      [lineId]: {
        ...current[lineId],
        ...patch,
      }
    }));
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
          note: batchNote.trim() || null
        })
      });
      setMessage(`Updated RFQ batch #${selectedBatchId}.`);
      await Promise.all([mutateDetail(), mutateBatches()]);
    } catch (error) {
      setMessage(`Batch update failed: ${String(error ?? "")}`);
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
          note: draft.note.trim() || null
        })
      });
      setMessage(`Updated RFQ line #${line.line_id}.`);
      await Promise.all([mutateDetail(), mutateBatches(), mutateOrders()]);
    } catch (error) {
      setMessage(`Line update failed: ${String(error ?? "")}`);
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">RFQ Workspace</h1>
        <p className="mt-1 text-sm text-slate-600">
          Convert planning gaps into supplier conversations, finalize quantities and lead times, then link real orders back to the project.
        </p>
        <p className="mt-1 text-xs text-slate-500">
          A line marked <span className="font-semibold">QUOTED</span> counts as dedicated planned supply. Once an actual order exists, link it and the order becomes the dedicated source used by planning.
        </p>
      </section>

      <section className="grid gap-6 xl:grid-cols-[360px,minmax(0,1fr)]">
        <aside className="space-y-4">
          <section className="panel p-4">
            <h2 className="mb-3 font-display text-lg font-semibold">Filter Batches</h2>
            <div className="grid gap-3">
              <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="">All status</option>
                <option value="OPEN">OPEN</option>
                <option value="CLOSED">CLOSED</option>
                <option value="CANCELLED">CANCELLED</option>
              </select>
              <select className="input" value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
                <option value="">All projects</option>
                {projects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    #{project.project_id} {project.name}
                  </option>
                ))}
              </select>
              {!!message && <p className="text-sm text-slate-700">{message}</p>}
            </div>
          </section>

          <section className="panel p-4">
            <h2 className="mb-3 font-display text-lg font-semibold">Batch List</h2>
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
                    <p className="text-sm font-semibold">#{batch.rfq_id} {batch.title}</p>
                    <p className={`mt-1 text-xs ${active ? "text-slate-200" : "text-slate-500"}`}>
                      {batch.project_name} / target {batch.target_date ?? "-"} / {batch.status}
                    </p>
                    <div className={`mt-3 grid grid-cols-3 gap-2 text-xs ${active ? "text-slate-100" : "text-slate-600"}`}>
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
        </aside>

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
                        onChange={(e) => setBatchTitle(e.target.value)}
                        placeholder="Batch title"
                      />
                      <select
                        className="input"
                        value={batchStatus}
                        onChange={(e) => setBatchStatus(e.target.value as RfqBatchSummary["status"])}
                      >
                        <option value="OPEN">OPEN</option>
                        <option value="CLOSED">CLOSED</option>
                        <option value="CANCELLED">CANCELLED</option>
                      </select>
                      <input
                        className="input md:col-span-3"
                        value={batchNote}
                        onChange={(e) => setBatchNote(e.target.value)}
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
                        {detailData.lines.map((line) => {
                          const draft = lineDrafts[line.line_id];
                          const matchingOrders = openOrders.filter(
                            (order) => order.item_id === line.item_id || order.order_id === line.linked_order_id
                          );
                          return (
                            <tr key={line.line_id} className="border-b border-slate-100 align-top">
                              <td className="px-2 py-2">
                                <p className="font-semibold">{line.item_number}</p>
                                <p className="text-xs text-slate-500">{line.manufacturer_name}</p>
                                <p className="text-xs text-slate-400">line #{line.line_id}</p>
                              </td>
                              <td className="px-2 py-2">
                                <input
                                  className="input"
                                  type="number"
                                  min={1}
                                  value={draft?.requested_quantity ?? ""}
                                  onChange={(e) => updateLineDraft(line.line_id, { requested_quantity: e.target.value })}
                                />
                              </td>
                              <td className="px-2 py-2">
                                <input
                                  className="input"
                                  type="number"
                                  min={1}
                                  value={draft?.finalized_quantity ?? ""}
                                  onChange={(e) => updateLineDraft(line.line_id, { finalized_quantity: e.target.value })}
                                />
                              </td>
                              <td className="px-2 py-2">
                                <input
                                  className="input"
                                  value={draft?.supplier_name ?? ""}
                                  onChange={(e) => updateLineDraft(line.line_id, { supplier_name: e.target.value })}
                                  placeholder="Supplier name"
                                />
                              </td>
                              <td className="px-2 py-2">
                                <input
                                  className="input"
                                  type="number"
                                  min={0}
                                  value={draft?.lead_time_days ?? ""}
                                  onChange={(e) => updateLineDraft(line.line_id, { lead_time_days: e.target.value })}
                                />
                              </td>
                              <td className="px-2 py-2">
                                <div className="space-y-2">
                                  <input
                                    className="input"
                                    type="date"
                                    value={draft?.expected_arrival ?? ""}
                                    onChange={(e) => updateLineDraft(line.line_id, { expected_arrival: e.target.value })}
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
                                  onChange={(e) => updateLineDraft(line.line_id, { status: e.target.value as RfqLine["status"] })}
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
                                  onChange={(e) => updateLineDraft(line.line_id, { linked_order_id: e.target.value })}
                                >
                                  <option value="">No linked order</option>
                                  {matchingOrders.map((order) => (
                                    <option key={order.order_id} value={order.order_id}>
                                      #{order.order_id} / {order.supplier_name} / qty {order.order_amount} / ETA {order.expected_arrival ?? "-"}{order.project_name ? ` / ${order.project_name}` : ""}
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
                                  onChange={(e) => updateLineDraft(line.line_id, { note: e.target.value })}
                                  placeholder="Line note"
                                />
                              </td>
                              <td className="px-2 py-2">
                                <button className="button-subtle" type="button" disabled={working || !draft} onClick={() => saveLine(line)}>
                                  Save Line
                                </button>
                              </td>
                            </tr>
                          );
                        })}
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
