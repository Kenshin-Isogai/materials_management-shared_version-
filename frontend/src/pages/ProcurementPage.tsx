import { useMemo, useState } from "react";
import useSWR from "swr";
import { apiDownload, apiGet, apiGetWithPagination, apiSend } from "../lib/api";
import type { ProcurementBatchDetail, ProcurementBatchSummary } from "../lib/types";

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
                <div className="space-y-2">
                  {batchDetail.lines.map((line) => (
                    <div key={line.line_id} className="rounded-xl border border-slate-200 px-3 py-2 text-sm">
                      <p className="font-semibold">{line.item_number} x {line.finalized_quantity}</p>
                      <p className="text-xs text-slate-500">
                        {line.source_type}
                        {line.source_project_name ? ` | ${line.source_project_name}` : ""}
                        {line.supplier_name ? ` | ${line.supplier_name}` : ""}
                        {line.expected_arrival ? ` | ETA ${line.expected_arrival}` : ""}
                      </p>
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
