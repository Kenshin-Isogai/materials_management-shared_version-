import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";
import { apiGetWithPagination, apiSend, apiSendForm } from "../lib/api";
import type { InventoryRow, Item } from "../lib/types";

type MoveForm = {
  item_id: string;
  quantity: string;
  from_location: string;
  to_location: string;
  note: string;
};

type MoveRow = MoveForm;

const blankMoveRow = (): MoveRow => ({
  item_id: "",
  quantity: "",
  from_location: "STOCK",
  to_location: "",
  note: ""
});

export function InventoryPage() {
  const [form, setForm] = useState<MoveForm>({
    item_id: "",
    quantity: "",
    from_location: "STOCK",
    to_location: "",
    note: ""
  });
  const [bulkRows, setBulkRows] = useState<MoveRow[]>([blankMoveRow(), blankMoveRow()]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [movementCsvFile, setMovementCsvFile] = useState<File | null>(null);
  const [movementBatchId, setMovementBatchId] = useState("");
  const { data, error, isLoading, mutate } = useSWR("/inventory", () =>
    apiGetWithPagination<InventoryRow[]>("/inventory?per_page=200")
  );
  const { data: itemsResp } = useSWR("/items-options", () =>
    apiGetWithPagination<Item[]>("/items?per_page=1000")
  );
  const items = useMemo(() => itemsResp?.data ?? [], [itemsResp]);

  function itemLabel(item: Item) {
    return `${item.item_number} (${item.manufacturer_name}) #${item.item_id}`;
  }



  async function submitMovementCsv(event: FormEvent) {
    event.preventDefault();
    if (!movementCsvFile) return;
    const formData = new FormData();
    formData.append("file", movementCsvFile);
    if (movementBatchId.trim()) formData.append("batch_id", movementBatchId.trim());
    setIsSubmitting(true);
    try {
      await apiSendForm("/inventory/import-csv", formData);
      setMovementCsvFile(null);
      setMovementBatchId("");
      await mutate();
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitMove(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    try {
      await apiSend("/inventory/move", {
        method: "POST",
        body: JSON.stringify({
          item_id: Number(form.item_id),
          quantity: Number(form.quantity),
          from_location: form.from_location,
          to_location: form.to_location,
          note: form.note || undefined
        })
      });
      setForm((prev) => ({ ...prev, quantity: "", note: "", to_location: "" }));
      await mutate();
    } finally {
      setIsSubmitting(false);
    }
  }

  function updateBulkRow(index: number, patch: Partial<MoveRow>) {
    setBulkRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeBulkRow(index: number) {
    setBulkRows((prev) => prev.filter((_, i) => i !== index));
  }

  async function submitBulk() {
    const operations = bulkRows
      .filter(
        (row) =>
          row.item_id &&
          row.quantity &&
          row.from_location.trim() &&
          row.to_location.trim()
      )
      .map((row) => ({
        operation_type: "MOVE",
        item_id: Number(row.item_id),
        quantity: Number(row.quantity),
        from_location: row.from_location.trim(),
        to_location: row.to_location.trim(),
        note: row.note.trim() || undefined
      }));
    if (!operations.length) return;
    setIsSubmitting(true);
    try {
      await apiSend("/inventory/batch", {
        method: "POST",
        body: JSON.stringify({ operations })
      });
      setBulkRows([blankMoveRow(), blankMoveRow()]);
      await mutate();
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Movements</h1>
        <p className="mt-1 text-sm text-slate-600">
          Transfer, consume, adjust inventory with single and bulk operations.
        </p>
      </section>



      <section className="panel grid gap-3 p-4">
        <h2 className="font-display text-lg font-semibold">CSV Import (Movements)</h2>
        <p className="text-xs text-slate-500">
          Columns: operation_type,item_id,quantity,from_location,to_location,location,note
        </p>
        <form className="grid gap-2" onSubmit={submitMovementCsv}>
          <input
            className="input"
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setMovementCsvFile(e.target.files?.[0] ?? null)}
            required
          />
          <input
            className="input"
            placeholder="Batch ID (optional)"
            value={movementBatchId}
            onChange={(e) => setMovementBatchId(e.target.value)}
          />
          <button className="button" disabled={isSubmitting || !movementCsvFile} type="submit">
            Import CSV
          </button>
        </form>
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <form className="panel grid gap-3 p-4" onSubmit={submitMove}>
          <h2 className="font-display text-lg font-semibold">Single Move</h2>
          <select
            className="input"
            value={form.item_id}
            onChange={(e) => setForm((p) => ({ ...p, item_id: e.target.value }))}
            required
          >
            <option value="">Select item</option>
            {items.map((item) => (
              <option key={item.item_id} value={item.item_id}>
                {itemLabel(item)}
              </option>
            ))}
          </select>
          <input
            className="input"
            placeholder="Quantity"
            type="number"
            min={1}
            value={form.quantity}
            onChange={(e) => setForm((p) => ({ ...p, quantity: e.target.value }))}
            required
          />
          <input
            className="input"
            placeholder="From location"
            value={form.from_location}
            onChange={(e) => setForm((p) => ({ ...p, from_location: e.target.value }))}
            required
          />
          <input
            className="input"
            placeholder="To location"
            value={form.to_location}
            onChange={(e) => setForm((p) => ({ ...p, to_location: e.target.value }))}
            required
          />
          <input
            className="input"
            placeholder="Note (optional)"
            value={form.note}
            onChange={(e) => setForm((p) => ({ ...p, note: e.target.value }))}
          />
          <button className="button" disabled={isSubmitting} type="submit">
            Move
          </button>
        </form>

        <div className="panel space-y-3 p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-lg font-semibold">Bulk Move Entry</h2>
            <button
              className="button-subtle"
              onClick={() => setBulkRows((prev) => [...prev, blankMoveRow()])}
            >
              Add Row
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-[900px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">Item</th>
                  <th className="px-2 py-2">Qty</th>
                  <th className="px-2 py-2">From</th>
                  <th className="px-2 py-2">To</th>
                  <th className="px-2 py-2">Note</th>
                  <th className="px-2 py-2">-</th>
                </tr>
              </thead>
              <tbody>
                {bulkRows.map((row, idx) => (
                  <tr key={idx} className="border-b border-slate-100">
                    <td className="px-2 py-2">
                      <select
                        className="input"
                        value={row.item_id}
                        onChange={(e) => updateBulkRow(idx, { item_id: e.target.value })}
                      >
                        <option value="">Select item</option>
                        {items.map((item) => (
                          <option key={item.item_id} value={item.item_id}>
                            {itemLabel(item)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        type="number"
                        min={1}
                        value={row.quantity}
                        onChange={(e) => updateBulkRow(idx, { quantity: e.target.value })}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.from_location}
                        onChange={(e) => updateBulkRow(idx, { from_location: e.target.value })}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.to_location}
                        onChange={(e) => updateBulkRow(idx, { to_location: e.target.value })}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.note}
                        onChange={(e) => updateBulkRow(idx, { note: e.target.value })}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <button className="button-subtle" onClick={() => removeBulkRow(idx)}>
                        Del
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="button" disabled={isSubmitting} onClick={submitBulk}>
            Submit Bulk Moves
          </button>
        </div>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Current Inventory</h2>
        {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {error && <p className="text-sm text-red-600">{String(error)}</p>}
        {data?.data && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">Item</th>
                  <th className="px-2 py-2">Location</th>
                  <th className="px-2 py-2">Qty</th>
                  <th className="px-2 py-2">Category</th>
                  <th className="px-2 py-2">Manufacturer</th>
                </tr>
              </thead>
              <tbody>
                {data.data.map((row) => (
                  <tr key={row.ledger_id} className="border-b border-slate-100">
                    <td className="px-2 py-2 font-semibold">{row.item_number}</td>
                    <td className="px-2 py-2">{row.location}</td>
                    <td className="px-2 py-2">{row.quantity}</td>
                    <td className="px-2 py-2">{row.category ?? "-"}</td>
                    <td className="px-2 py-2">{row.manufacturer_name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
