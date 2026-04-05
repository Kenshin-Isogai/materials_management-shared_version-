import { useMemo, useState } from "react";
import useSWR from "swr";
import { apiDownload, apiGet, apiGetWithPagination, apiSend } from "@/lib/api";
import { buildLinkedOrderSelectOptions } from "@/lib/rfqEditorState";
import type {
  ProcurementBatchDetail,
  ProcurementBatchSummary,
  ProcurementLine,
  ProcurementLineStatus,
  PurchaseOrderLine,
} from "@/lib/types";

type ShortageInboxRow = {
  item_id: number;
  item_number: string;
  manufacturer_name: string | null;
  requested_quantity: number;
  source_type: "PROJECT" | "BOM" | "ADHOC";
  source_project_id: number | null;
  source_project_name: string | null;
  expected_arrival: string | null;
  note: string | null;
};

type ShortageInbox = {
  generated_at: string;
  rows: ShortageInboxRow[];
};

export function ProcurementPage() {
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null);
  const [batchTitle, setBatchTitle] = useState("");
  const [message, setMessage] = useState("");
  const [working, setWorking] = useState(false);
  const [editingLineId, setEditingLineId] = useState<number | null>(null);
  const [lineDraft, setLineDraft] = useState<{
    status: ProcurementLineStatus;
    finalized_quantity: string;
    supplier_name: string;
    expected_arrival: string;
    linked_purchase_order_line_id: string;
    note: string;
  } | null>(null);

  const { data: inboxResp, mutate: mutateInbox } = useSWR("/shortage-inbox", () =>
    apiGet<ShortageInbox>("/shortage-inbox"),
  );
  const { data: batchesResp, mutate: mutateBatches } = useSWR("/procurement-batches", () =>
    apiGetWithPagination<ProcurementBatchSummary[]>("/procurement-batches?per_page=200"),
  );
  const detailKey = selectedBatchId ? `/procurement-batches/${selectedBatchId}` : null;
  const { data: batchDetail, mutate: mutateDetail } = useSWR(detailKey, () =>
    apiGet<ProcurementBatchDetail>(detailKey ?? ""),
  );

  const inboxRows = inboxResp?.rows ?? [];
  const batches = batchesResp?.data ?? [];

  const selectedBatch = useMemo(
    () => batches.find((batch) => batch.batch_id === selectedBatchId) ?? null,
    [batches, selectedBatchId],
  );
  const editingLine = useMemo(
    () => batchDetail?.lines.find((line) => line.line_id === editingLineId) ?? null,
    [batchDetail?.lines, editingLineId],
  );
  const matchingOrdersPath = useMemo(() => {
    if (!editingLine) return null;
    return `/purchase-order-lines?item_id=${editingLine.item_id}&include_arrived=false&per_page=200`;
  }, [editingLine]);
  const {
    data: matchingOrdersResp,
    error: matchingOrdersError,
    isLoading: matchingOrdersLoading,
  } = useSWR(matchingOrdersPath, () =>
    apiGetWithPagination<PurchaseOrderLine[]>(matchingOrdersPath ?? ""),
  );
  const matchingOrders = matchingOrdersResp?.data ?? [];

  function beginEditLine(line: ProcurementLine) {
    setEditingLineId(line.line_id);
    setLineDraft({
      status: line.status,
      finalized_quantity: String(line.finalized_quantity),
      supplier_name: line.supplier_name ?? "",
      expected_arrival: line.expected_arrival ?? "",
      linked_purchase_order_line_id:
        line.linked_purchase_order_line_id == null ? "" : String(line.linked_purchase_order_line_id),
      note: line.note ?? "",
    });
    setMessage("");
  }

  function cancelEditLine() {
    setEditingLineId(null);
    setLineDraft(null);
  }

  async function saveLine(line: ProcurementLine) {
    if (!lineDraft) return;
    setWorking(true);
    setMessage("");
    const prevStatus = line.status;
    const nextStatus = lineDraft.status;
    try {
      await apiSend(`/procurement-lines/${line.line_id}`, {
        method: "PUT",
        body: JSON.stringify({
          status: lineDraft.status,
          finalized_quantity: Number(lineDraft.finalized_quantity),
          supplier_name: lineDraft.supplier_name.trim() || null,
          expected_arrival: lineDraft.expected_arrival.trim() || null,
          linked_purchase_order_line_id:
            lineDraft.status === "ORDERED" && lineDraft.linked_purchase_order_line_id.trim()
              ? Number(lineDraft.linked_purchase_order_line_id)
              : null,
          note: lineDraft.note.trim() || null,
        }),
      });
      let feedback = `Updated procurement line #${line.line_id}.`;
      if (prevStatus !== nextStatus) {
        if (nextStatus === "QUOTED") {
          feedback += " This line now counts as quoted supply in the Planning Board.";
        } else if (nextStatus === "ORDERED") {
          feedback += " This line is now linked to a purchase order and will appear in Arrival tracking.";
        }
      }
      setMessage(feedback);
      cancelEditLine();
      await Promise.all([mutateDetail(), mutateBatches(), mutateInbox()]);
    } catch (error) {
      setMessage(`Line update failed: ${String(error ?? "")}`);
    } finally {
      setWorking(false);
    }
  }

  async function createFromInbox() {
    if (!inboxRows.length) return;
    setWorking(true);
    setMessage("");
    try {
      const payload = await apiSend<ProcurementBatchDetail>("/shortage-inbox/to-procurement", {
        method: "POST",
        body: JSON.stringify({
          create_batch_title: batchTitle.trim() || "Procurement Batch",
          lines: inboxRows.map((row) => ({
            item_id: row.item_id,
            requested_quantity: row.requested_quantity,
            source_type: row.source_type,
            source_project_id: row.source_project_id,
            expected_arrival: row.expected_arrival,
            note: row.note,
          })),
        }),
      });
      setSelectedBatchId(payload.batch_id);
      setMessage(`Created procurement batch #${payload.batch_id}.`);
      await Promise.all([mutateBatches(), mutateInbox(), mutateDetail()]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  }

  async function exportBatch() {
    if (!selectedBatchId) return;
    try {
      await apiDownload(
        `/procurement-batches/${selectedBatchId}/export.csv`,
        `procurement_batch_${selectedBatchId}.csv`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Procurement</h1>
        <p className="mt-1 text-sm text-slate-600">
          Unified home for shortage follow-up, cross-project batch creation, and exportable supplier CSVs.
        </p>
      </section>

      <section className="panel p-4">
        <div className="flex flex-wrap items-center gap-3">
          <input
            className="input max-w-sm"
            value={batchTitle}
            onChange={(event) => setBatchTitle(event.target.value)}
            placeholder="New batch title"
          />
          <button className="button" type="button" disabled={working || !inboxRows.length} onClick={() => void createFromInbox()}>
            Create Batch From Inbox
          </button>
          {selectedBatchId && (
            <button className="button-subtle" type="button" onClick={() => void exportBatch()}>
              Export Selected Batch CSV
            </button>
          )}
        </div>
        {!!message && <p className="mt-3 text-sm text-slate-700">{message}</p>}
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr),420px]">
        <div className="panel p-4">
          <h2 className="mb-3 font-display text-lg font-semibold">Shortage Inbox</h2>
          <div className="overflow-x-auto">
            <table className="min-w-[900px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">Item</th>
                  <th className="px-2 py-2">Qty</th>
                  <th className="px-2 py-2">Source</th>
                  <th className="px-2 py-2">Project</th>
                  <th className="px-2 py-2">Needed By</th>
                </tr>
              </thead>
              <tbody>
                {inboxRows.map((row) => (
                  <tr key={`${row.source_type}-${row.source_project_id ?? "na"}-${row.item_id}`} className="border-b border-slate-100">
                    <td className="px-2 py-2">
                      {row.item_number}
                      {row.manufacturer_name ? ` (${row.manufacturer_name})` : ""}
                    </td>
                    <td className="px-2 py-2 font-semibold text-amber-700">{row.requested_quantity}</td>
                    <td className="px-2 py-2">{row.source_type}</td>
                    <td className="px-2 py-2">{row.source_project_name ?? "-"}</td>
                    <td className="px-2 py-2">{row.expected_arrival ?? "-"}</td>
                  </tr>
                ))}
                {!inboxRows.length && (
                  <tr>
                    <td className="px-2 py-4 text-slate-500" colSpan={5}>
                      No current shortage rows.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-4">
          <section className="panel p-4">
            <h2 className="mb-3 font-display text-lg font-semibold">Batch List</h2>
            <div className="space-y-2">
              {batches.map((batch) => (
                <button
                  key={batch.batch_id}
                  type="button"
                  className={`w-full rounded-xl border px-3 py-3 text-left ${batch.batch_id === selectedBatchId ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-white"}`}
                  onClick={() => setSelectedBatchId(batch.batch_id)}
                >
                  <p className="font-semibold">#{batch.batch_id} {batch.title}</p>
                  <p className={`text-xs ${batch.batch_id === selectedBatchId ? "text-slate-200" : "text-slate-500"}`}>
                    {batch.status} | {batch.line_count} lines
                  </p>
                </button>
              ))}
              {!batches.length && <p className="text-sm text-slate-500">No procurement batches yet.</p>}
            </div>
          </section>

          <section className="panel p-4">
            <h2 className="mb-3 font-display text-lg font-semibold">Selected Batch</h2>
            {!selectedBatch && <p className="text-sm text-slate-500">Select a batch to inspect it.</p>}
            {selectedBatch && batchDetail && (
              <div className="space-y-3">
                <p className="text-sm text-slate-600">
                  {batchDetail.status} | {batchDetail.finalized_quantity_total} total finalized quantity
                </p>
                <div className="space-y-3">
                  {batchDetail.lines.map((line) => (
                    <div key={line.line_id} className="rounded-xl border border-slate-200 px-3 py-3 text-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-semibold">
                            #{line.line_id} {line.item_number} x {line.finalized_quantity}
                          </p>
                          <p className="text-xs text-slate-500">
                            {line.source_type}
                            {line.source_project_name ? ` | ${line.source_project_name}` : ""}
                            {line.linked_purchase_order_line_supplier_name
                              ? ` | ${line.linked_purchase_order_line_supplier_name}`
                              : ""}
                          </p>
                        </div>
                        {editingLineId === line.line_id ? (
                          <div className="flex gap-2">
                            <button className="button-subtle" type="button" disabled={working} onClick={() => void saveLine(line)}>
                              Save
                            </button>
                            <button className="button-subtle" type="button" disabled={working} onClick={cancelEditLine}>
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button className="button-subtle" type="button" disabled={working} onClick={() => beginEditLine(line)}>
                            Edit
                          </button>
                        )}
                      </div>
                      {editingLineId === line.line_id && lineDraft ? (
                        <div className="mt-3 space-y-2">
                          <select
                            className="input"
                            value={lineDraft.status}
                            onChange={(event) =>
                              setLineDraft((current) =>
                                current
                                  ? {
                                      ...current,
                                      status: event.target.value as ProcurementLineStatus,
                                    }
                                  : current,
                              )
                            }
                          >
                            <option value="DRAFT">DRAFT</option>
                            <option value="SENT">SENT</option>
                            <option value="QUOTED">QUOTED</option>
                            <option value="ORDERED">ORDERED</option>
                            <option value="CANCELLED">CANCELLED</option>
                          </select>
                          <input
                            className="input"
                            type="number"
                            min={1}
                            value={lineDraft.finalized_quantity}
                            onChange={(event) =>
                              setLineDraft((current) =>
                                current ? { ...current, finalized_quantity: event.target.value } : current,
                              )
                            }
                            placeholder="Finalized quantity"
                          />
                          <input
                            className="input"
                            value={lineDraft.supplier_name}
                            onChange={(event) =>
                              setLineDraft((current) =>
                                current ? { ...current, supplier_name: event.target.value } : current,
                              )
                            }
                            placeholder="Supplier name"
                          />
                          <input
                            className="input"
                            type="date"
                            value={lineDraft.expected_arrival}
                            onChange={(event) =>
                              setLineDraft((current) =>
                                current ? { ...current, expected_arrival: event.target.value } : current,
                              )
                            }
                          />
                          <select
                            className="input"
                            value={lineDraft.linked_purchase_order_line_id}
                            onChange={(event) =>
                              setLineDraft((current) =>
                                current ? { ...current, linked_purchase_order_line_id: event.target.value } : current,
                              )
                            }
                          >
                            {buildLinkedOrderSelectOptions({
                              line,
                              draftLinkedOrderId: lineDraft.linked_purchase_order_line_id,
                              matchingOrders,
                              isActive: true,
                              isLoading: matchingOrdersLoading,
                              loadError: matchingOrdersError ? String(matchingOrdersError) : null,
                            }).map((option) => (
                              <option key={option.value} value={option.value} disabled={option.disabled}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                          <textarea
                            className="input min-h-[88px]"
                            value={lineDraft.note}
                            onChange={(event) =>
                              setLineDraft((current) => (current ? { ...current, note: event.target.value } : current))
                            }
                            placeholder="Note"
                          />
                        </div>
                      ) : (
                        <div className="mt-2 space-y-1 text-xs text-slate-500">
                          <p>Status: {line.status}</p>
                          <p>Supplier: {line.supplier_name ?? "-"}</p>
                          <p>ETA: {line.expected_arrival ?? "-"}</p>
                          <p>
                            Linked purchase order line:{" "}
                            {line.linked_purchase_order_line_id ? `#${line.linked_purchase_order_line_id}` : "-"}
                          </p>
                          <p>Note: {line.note ?? "-"}</p>
                        </div>
                      )}
                    </div>
                  ))}
                  {!batchDetail.lines.length && <p className="text-sm text-slate-500">No lines in this batch.</p>}
                </div>
              </div>
            )}
          </section>
        </div>
      </section>
    </div>
  );
}
