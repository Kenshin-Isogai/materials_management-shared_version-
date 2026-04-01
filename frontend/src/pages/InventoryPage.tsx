import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { CatalogPicker } from "../components/CatalogPicker";
import { apiDownload, apiGetWithPagination, apiSend, apiSendForm } from "../lib/api";
import { getNextMovementEntryLocations } from "../lib/movementEntry";
import { formatActionError, resolvePreviewSelection } from "../lib/previewState";
import type { CatalogSearchResult, InventoryRow, Item } from "../lib/types";

type MoveRow = {
  item_id: string;
  quantity: string;
  from_location: string;
  to_location: string;
  note: string;
};

type InventoryImportPreviewRow = {
  row: number;
  operation_type: string;
  item_id: string;
  quantity: string;
  from_location: string | null;
  to_location: string | null;
  location: string | null;
  note: string | null;
  status: "exact" | "high_confidence" | "needs_review" | "unresolved";
  message: string;
  blocking: boolean;
  requires_user_selection: boolean;
  allowed_entity_types: Array<"item">;
  suggested_match: CatalogSearchResult | null;
};

type InventoryImportPreview = {
  source_name: string;
  summary: {
    total_rows: number;
    exact: number;
    high_confidence: number;
    needs_review: number;
    unresolved: number;
  };
  blocking_errors: string[];
  can_auto_accept: boolean;
  rows: InventoryImportPreviewRow[];
};

const blankMoveRow = (
  locations: Partial<Pick<MoveRow, "from_location" | "to_location">> = {},
): MoveRow => ({
  item_id: "",
  quantity: "",
  from_location: locations.from_location ?? "STOCK",
  to_location: locations.to_location ?? "",
  note: ""
});

const initialMoveRows = (count = 4): MoveRow[] => Array.from({ length: count }, () => blankMoveRow());

export function InventoryPage() {
  const [bulkRows, setBulkRows] = useState<MoveRow[]>(() => initialMoveRows());
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [movementCsvFile, setMovementCsvFile] = useState<File | null>(null);
  const [movementBatchId, setMovementBatchId] = useState("");
  const [movementMessage, setMovementMessage] = useState("");
  const [movementPreview, setMovementPreview] = useState<InventoryImportPreview | null>(null);
  const [movementPreviewSelections, setMovementPreviewSelections] = useState<
    Record<number, CatalogSearchResult | null>
  >({});
  const { data, error, isLoading, mutate } = useSWR("/inventory", () =>
    apiGetWithPagination<InventoryRow[]>("/inventory?per_page=200")
  );
  const { data: itemsResp } = useSWR("/items-options", () =>
    apiGetWithPagination<Item[]>("/items?per_page=1000")
  );
  const items = useMemo(() => itemsResp?.data ?? [], [itemsResp]);
  const itemCatalogById = useMemo(
    () =>
      new Map(
        items.map((item) => [
          item.item_id,
          {
            entity_type: "item" as const,
            entity_id: item.item_id,
            value_text: item.item_number,
            display_label: `${item.item_number} (${item.manufacturer_name}) #${item.item_id}`,
            summary: [item.category, `#${item.item_id}`].filter(Boolean).join(" | "),
            match_source: "item_number",
          },
        ])
      ),
    [items]
  );

  function resetMovementPreview() {
    setMovementPreview(null);
    setMovementPreviewSelections({});
  }

  function applyMovementPreview(preview: InventoryImportPreview) {
    const nextSelections: Record<number, CatalogSearchResult | null> = {};
    for (const row of preview.rows) {
      nextSelections[row.row] = row.suggested_match;
    }
    setMovementPreview(preview);
    setMovementPreviewSelections(nextSelections);
  }

  function selectedMovementPreviewMatch(row: InventoryImportPreviewRow): CatalogSearchResult | null {
    return resolvePreviewSelection(movementPreviewSelections, row.row, row.suggested_match ?? null);
  }

  function previewStatusTone(status: InventoryImportPreviewRow["status"]): string {
    switch (status) {
      case "exact":
        return "bg-emerald-50 text-emerald-700";
      case "high_confidence":
        return "bg-sky-50 text-sky-700";
      case "needs_review":
        return "bg-amber-50 text-amber-700";
      case "unresolved":
        return "bg-red-50 text-red-700";
      default:
        return "bg-slate-100 text-slate-700";
    }
  }



  async function previewMovementCsv(event: FormEvent) {
    event.preventDefault();
    if (!movementCsvFile) return;
    const formData = new FormData();
    formData.append("file", movementCsvFile);
    if (movementBatchId.trim()) formData.append("batch_id", movementBatchId.trim());
    setIsSubmitting(true);
    setMovementMessage("");
    resetMovementPreview();
    try {
      const result = await apiSendForm<InventoryImportPreview>("/inventory/import-preview", formData);
      applyMovementPreview(result);
      setMovementMessage(
        result.can_auto_accept
          ? `Preview ready: ${result.summary.total_rows} row(s) are ready to import.`
          : `Preview ready: review=${result.summary.needs_review}, unresolved=${result.summary.unresolved}.`
      );
    } catch (error) {
      setMovementMessage(formatActionError("Preview failed", error));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function confirmMovementPreview() {
    if (!movementCsvFile || !movementPreview) return;
    const missingSelection = movementPreview.rows.find(
      (row) => row.requires_user_selection && !selectedMovementPreviewMatch(row)
    );
    if (missingSelection) {
      setMovementMessage(`Row ${missingSelection.row}: select an item before importing.`);
      return;
    }
    const nonFixableBlocking = movementPreview.rows.find(
      (row) => row.blocking && !row.requires_user_selection
    );
    if (nonFixableBlocking) {
      setMovementMessage(`Row ${nonFixableBlocking.row}: ${nonFixableBlocking.message}`);
      return;
    }

    const rowOverrides: Record<number, { item_id: number }> = {};
    for (const row of movementPreview.rows) {
      const selection = selectedMovementPreviewMatch(row);
      if (!selection) continue;
      if (row.requires_user_selection || selection.entity_id !== row.suggested_match?.entity_id) {
        rowOverrides[row.row] = { item_id: selection.entity_id };
      }
    }

    const formData = new FormData();
    formData.append("file", movementCsvFile);
    if (movementBatchId.trim()) formData.append("batch_id", movementBatchId.trim());
    if (Object.keys(rowOverrides).length > 0) {
      formData.append("row_overrides", JSON.stringify(rowOverrides));
    }

    setIsSubmitting(true);
    setMovementMessage("");
    try {
      const result = await apiSendForm<{ batch_id: string; operations: Array<Record<string, unknown>> }>(
        "/inventory/import-csv",
        formData
      );
      setMovementMessage(
        `Imported ${result.operations.length} movement row(s). Batch ID: ${result.batch_id}.`
      );
      setMovementCsvFile(null);
      setMovementBatchId("");
      resetMovementPreview();
      await mutate();
    } catch (error) {
      setMovementMessage(formatActionError("Import failed", error));
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

  function addBulkRow() {
    setBulkRows((prev) => [...prev, blankMoveRow(getNextMovementEntryLocations(prev))]);
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
      setBulkRows(initialMoveRows());
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
        <div className="flex flex-wrap gap-2">
          <button
            className="button-subtle"
            type="button"
            onClick={() =>
              void apiDownload("/inventory/import-template", "inventory_import_template.csv").catch(
                (error) => {
                  window.alert(error instanceof Error ? error.message : String(error));
                }
              )
            }
          >
            Download Template CSV
          </button>
          <button
            className="button-subtle"
            type="button"
            onClick={() =>
              void apiDownload("/inventory/import-reference", "inventory_import_reference.csv").catch(
                (error) => {
                  window.alert(error instanceof Error ? error.message : String(error));
                }
              )
            }
          >
            Download Reference CSV
          </button>
        </div>
        <form className="grid gap-2" onSubmit={previewMovementCsv}>
          <input
            className="input"
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              setMovementCsvFile(e.target.files?.[0] ?? null);
              resetMovementPreview();
            }}
            required
          />
          <input
            className="input"
            placeholder="Batch ID (optional)"
            value={movementBatchId}
            onChange={(e) => {
              setMovementBatchId(e.target.value);
              resetMovementPreview();
            }}
          />
          <button className="button" disabled={isSubmitting || !movementCsvFile} type="submit">
            Preview Import
          </button>
        </form>
        {movementMessage && <p className="text-sm text-signal">{movementMessage}</p>}
        {movementPreview && (
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-emerald-50 px-3 py-1 font-semibold text-emerald-700">
                Exact {movementPreview.summary.exact}
              </span>
              <span className="rounded-full bg-amber-50 px-3 py-1 font-semibold text-amber-700">
                Review {movementPreview.summary.needs_review}
              </span>
              <span className="rounded-full bg-red-50 px-3 py-1 font-semibold text-red-700">
                Unresolved {movementPreview.summary.unresolved}
              </span>
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-[980px] text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="px-2 py-2">Row</th>
                    <th className="px-2 py-2">Operation</th>
                    <th className="px-2 py-2">Item</th>
                    <th className="px-2 py-2">Quantity</th>
                    <th className="px-2 py-2">Status</th>
                    <th className="px-2 py-2">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {movementPreview.rows.map((row) => (
                    <tr key={row.row} className="border-b border-slate-100 align-top">
                      <td className="px-2 py-3 font-semibold">#{row.row}</td>
                      <td className="px-2 py-3">
                        <div className="space-y-1">
                          <p className="font-semibold">{row.operation_type}</p>
                          <p className="text-xs text-slate-500">
                            {row.from_location ? `from ${row.from_location}` : ""}
                            {row.to_location ? ` to ${row.to_location}` : ""}
                            {row.location ? ` at ${row.location}` : ""}
                          </p>
                          {row.note && <p className="text-xs text-slate-500">{row.note}</p>}
                        </div>
                      </td>
                      <td className="px-2 py-3">
                        {row.suggested_match ? (
                          <div className="space-y-1">
                            <p className="font-semibold text-slate-900">
                              {row.suggested_match.display_label}
                            </p>
                            {row.suggested_match.summary && (
                              <p className="text-xs text-slate-500">{row.suggested_match.summary}</p>
                            )}
                          </div>
                        ) : (
                          <p className="text-sm text-slate-500">{row.item_id || "Unresolved item"}</p>
                        )}
                      </td>
                      <td className="px-2 py-3">{row.quantity}</td>
                      <td className="px-2 py-3">
                        <span
                          className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${previewStatusTone(row.status)}`}
                        >
                          {row.status}
                        </span>
                      </td>
                      <td className="px-2 py-3">
                        <div className="space-y-2">
                          <p className="text-xs text-slate-600">{row.message}</p>
                          {row.allowed_entity_types.length > 0 && (
                            <CatalogPicker
                              allowedTypes={row.allowed_entity_types}
                              onChange={(value) =>
                                setMovementPreviewSelections((prev) => ({
                                  ...prev,
                                  [row.row]: value,
                                }))
                              }
                              placeholder="Select item"
                              recentKey="inventory-import-preview-item"
                              value={
                                selectedMovementPreviewMatch(row) ??
                                (row.item_id ? itemCatalogById.get(Number(row.item_id)) ?? null : null)
                              }
                            />
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button className="button" disabled={isSubmitting} onClick={() => void confirmMovementPreview()} type="button">
                Confirm Import
              </button>
              <button className="button-subtle" disabled={isSubmitting} onClick={resetMovementPreview} type="button">
                Clear Preview
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="panel space-y-3 p-4">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-lg font-semibold">Movement Entry</h2>
          <button
            className="button-subtle"
            type="button"
            onClick={addBulkRow}
          >
            Add Row
          </button>
        </div>
        <p className="text-xs text-slate-500">
          Single-item and multi-item movements are both handled here.
        </p>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
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
                    <div className="min-w-[18rem]">
                      <CatalogPicker
                        allowedTypes={["item"]}
                        onChange={(value) =>
                          updateBulkRow(idx, { item_id: value ? String(value.entity_id) : "" })
                        }
                        placeholder="Search items"
                        recentKey="movements-entry-item"
                        value={row.item_id ? itemCatalogById.get(Number(row.item_id)) ?? null : null}
                      />
                    </div>
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
                    <button className="button-subtle" type="button" onClick={() => removeBulkRow(idx)}>
                      Del
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button className="button" disabled={isSubmitting} onClick={submitBulk} type="button">
          Submit Moves
        </button>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Current Inventory</h2>
        {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {error && <ApiErrorNotice error={error} area="inventory data" />}
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
