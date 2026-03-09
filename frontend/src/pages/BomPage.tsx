import { useState } from "react";
import { CatalogPicker } from "../components/CatalogPicker";
import { apiSend } from "../lib/api";
import { formatActionError } from "../lib/previewState";
import type { CatalogSearchResult } from "../lib/types";

type BomRow = {
  supplier: string;
  item_number: string;
  required_quantity: number;
};

type BomResult = {
  rows: Array<Record<string, unknown>>;
  target_date?: string | null;
};

type BomPreviewStatus = "exact" | "high_confidence" | "needs_review" | "unresolved";

type BomPreviewMatch = CatalogSearchResult & {
  confidence_score?: number | null;
  match_reason?: string | null;
  canonical_item_number?: string | null;
  manufacturer_name?: string | null;
  units_per_order?: number | null;
};

type BomPreviewRow = {
  row: number;
  supplier: string;
  item_number: string;
  required_quantity: number;
  supplier_status: BomPreviewStatus;
  item_status: BomPreviewStatus;
  status: BomPreviewStatus;
  message: string;
  requires_supplier_selection: boolean;
  requires_item_selection: boolean;
  suggested_supplier: BomPreviewMatch | null;
  supplier_candidates: BomPreviewMatch[];
  suggested_match: BomPreviewMatch | null;
  candidates: BomPreviewMatch[];
  canonical_item_number: string | null;
  units_per_order: number | null;
  canonical_required_quantity: number | null;
  available_stock: number | null;
  shortage: number | null;
};

type BomPreview = {
  target_date: string | null;
  summary: {
    total_rows: number;
    exact: number;
    high_confidence: number;
    needs_review: number;
    unresolved: number;
  };
  can_auto_accept: boolean;
  rows: BomPreviewRow[];
};

const blankRow = (): BomRow => ({
  supplier: "",
  item_number: "",
  required_quantity: 0,
});

function previewStatusTone(status: BomPreviewStatus): string {
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

function statusLabel(status: BomPreviewStatus): string {
  return status.replace("_", " ");
}

export function BomPage() {
  const [rows, setRows] = useState<BomRow[]>([
    { supplier: "Thorlabs", item_number: "LENS-001", required_quantity: 3 },
  ]);
  const [result, setResult] = useState<BomResult | null>(null);
  const [preview, setPreview] = useState<BomPreview | null>(null);
  const [previewSupplierSelections, setPreviewSupplierSelections] = useState<
    Record<number, CatalogSearchResult>
  >({});
  const [previewItemSelections, setPreviewItemSelections] = useState<
    Record<number, CatalogSearchResult>
  >({});
  const [loading, setLoading] = useState(false);
  const [targetDate, setTargetDate] = useState("");
  const [message, setMessage] = useState("");

  function resetPreview() {
    setPreview(null);
    setPreviewSupplierSelections({});
    setPreviewItemSelections({});
  }

  function invalidateWorkingState() {
    resetPreview();
    setResult(null);
    setMessage("");
  }

  function updateRow(index: number, patch: Partial<BomRow>) {
    invalidateWorkingState();
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addRow() {
    invalidateWorkingState();
    setRows((prev) => [...prev, blankRow()]);
  }

  function removeRow(index: number) {
    invalidateWorkingState();
    setRows((prev) => prev.filter((_, i) => i !== index));
  }

  function normalizedRows(): BomRow[] {
    return rows
      .filter(
        (row) =>
          row.supplier.trim() ||
          row.item_number.trim() ||
          Number(row.required_quantity || 0) > 0
      )
      .map((row) => ({
        supplier: row.supplier.trim(),
        item_number: row.item_number.trim(),
        required_quantity: Number(row.required_quantity || 0),
      }));
  }

  function explicitPreviewSupplier(row: BomPreviewRow): CatalogSearchResult | null {
    return previewSupplierSelections[row.row] ?? null;
  }

  function explicitPreviewItem(row: BomPreviewRow): CatalogSearchResult | null {
    return previewItemSelections[row.row] ?? null;
  }

  function displayPreviewSupplier(row: BomPreviewRow): BomPreviewMatch | CatalogSearchResult | null {
    return (
      explicitPreviewSupplier(row) ??
      (row.suggested_supplier && !row.requires_supplier_selection ? row.suggested_supplier : null)
    );
  }

  function displayPreviewItem(row: BomPreviewRow): BomPreviewMatch | CatalogSearchResult | null {
    return (
      explicitPreviewItem(row) ??
      (row.suggested_match && !row.requires_item_selection ? row.suggested_match : null)
    );
  }

  function setPreviewSupplierSelection(rowNumber: number, value: CatalogSearchResult | null) {
    setPreviewSupplierSelections((prev) => {
      const next = { ...prev };
      if (value) {
        next[rowNumber] = value;
      } else {
        delete next[rowNumber];
      }
      return next;
    });
  }

  function setPreviewItemSelection(rowNumber: number, value: CatalogSearchResult | null) {
    setPreviewItemSelections((prev) => {
      const next = { ...prev };
      if (value) {
        next[rowNumber] = value;
      } else {
        delete next[rowNumber];
      }
      return next;
    });
  }

  function supplierTextForRow(row: BomPreviewRow): string {
    const explicit = explicitPreviewSupplier(row);
    if (explicit) return explicit.value_text.trim();
    if (row.supplier_status === "high_confidence") {
      return row.suggested_supplier?.value_text?.trim() || row.supplier.trim();
    }
    return row.supplier.trim();
  }

  function itemTextForRow(row: BomPreviewRow): string {
    const explicit = explicitPreviewItem(row);
    if (explicit) return explicit.value_text.trim();
    if (row.item_status === "high_confidence") {
      return row.suggested_match?.value_text?.trim() || row.item_number.trim();
    }
    return row.item_number.trim();
  }

  function buildRowsFromPreview(options?: { requireResolved?: boolean }): BomRow[] | null {
    if (!preview) return normalizedRows();
    const requireResolved = options?.requireResolved ?? false;
    const unresolvedRows: number[] = [];
    const nextRows = preview.rows.map((row) => {
      const supplier = supplierTextForRow(row);
      const item_number = itemTextForRow(row);
      const supplierReady =
        !!explicitPreviewSupplier(row) || row.supplier_status === "exact" || row.supplier_status === "high_confidence";
      const itemReady =
        !!explicitPreviewItem(row) || row.item_status === "exact" || row.item_status === "high_confidence";
      if (requireResolved && (!supplierReady || !itemReady || !supplier || !item_number)) {
        unresolvedRows.push(row.row);
      }
      return {
        supplier,
        item_number,
        required_quantity: row.required_quantity,
      };
    });
    if (requireResolved && unresolvedRows.length > 0) {
      setMessage(
        `Resolve preview rows before continuing: ${unresolvedRows.map((row) => `#${row}`).join(", ")}`
      );
      return null;
    }
    return nextRows;
  }

  function applyCorrectionsToGrid() {
    const correctedRows = buildRowsFromPreview();
    if (!correctedRows) return;
    const currentRows = normalizedRows();
    const changedCount = correctedRows.filter((row, index) => {
      const current = currentRows[index];
      return (
        !current ||
        current.supplier !== row.supplier ||
        current.item_number !== row.item_number ||
        current.required_quantity !== row.required_quantity
      );
    }).length;
    setRows(correctedRows.length > 0 ? correctedRows : [blankRow()]);
    resetPreview();
    setMessage(`Applied corrections to ${changedCount} BOM row(s).`);
  }

  async function previewReconciliation() {
    const payloadRows = normalizedRows();
    if (!payloadRows.length) return;
    setLoading(true);
    setMessage("");
    setResult(null);
    resetPreview();
    try {
      const data = await apiSend<BomPreview>("/bom/preview", {
        method: "POST",
        body: JSON.stringify({
          rows: payloadRows,
          target_date: targetDate.trim() || null,
        }),
      });
      setPreview(data);
      setMessage(
        data.can_auto_accept
          ? `Preview ready: ${data.summary.total_rows} row(s) can be analyzed directly.`
          : `Preview ready: review=${data.summary.needs_review}, unresolved=${data.summary.unresolved}.`
      );
    } catch (error) {
      setMessage(formatActionError("Preview failed", error));
    } finally {
      setLoading(false);
    }
  }

  async function analyzePreviewRows() {
    const payloadRows = buildRowsFromPreview({ requireResolved: true });
    if (!payloadRows?.length) return;
    setLoading(true);
    setMessage("");
    try {
      const data = await apiSend<BomResult>("/bom/analyze", {
        method: "POST",
        body: JSON.stringify({
          rows: payloadRows,
          target_date: targetDate.trim() || null,
        }),
      });
      setResult(data);
      setMessage("Analysis updated from the preview selection set.");
    } catch (error) {
      setMessage(formatActionError("Analysis failed", error));
    } finally {
      setLoading(false);
    }
  }

  async function reservePreviewRows() {
    const payloadRows = buildRowsFromPreview({ requireResolved: true });
    if (!payloadRows?.length) return;
    setLoading(true);
    setMessage("");
    try {
      const data = await apiSend<{
        analysis: Array<Record<string, unknown>>;
        created_reservations: Array<Record<string, unknown>>;
      }>("/bom/reserve", {
        method: "POST",
        body: JSON.stringify({
          rows: payloadRows,
          purpose: "BOM reserve",
        }),
      });
      setRows(payloadRows);
      setResult({ rows: data.analysis, target_date: targetDate.trim() || null });
      resetPreview();
      setMessage(`Created ${data.created_reservations.length} reservation(s).`);
    } catch (error) {
      setMessage(formatActionError("Reserve failed", error));
    } finally {
      setLoading(false);
    }
  }

  async function saveShortagesFromPreview() {
    const payloadRows = buildRowsFromPreview({ requireResolved: true });
    if (!payloadRows?.length) return;
    setLoading(true);
    setMessage("");
    try {
      const data = await apiSend<{
        target_date: string | null;
        analysis: Array<Record<string, unknown>>;
        created_count: number;
      }>("/purchase-candidates/from-bom", {
        method: "POST",
        body: JSON.stringify({
          rows: payloadRows,
          target_date: targetDate.trim() || null,
        }),
      });
      setRows(payloadRows);
      setResult({ rows: data.analysis, target_date: data.target_date });
      resetPreview();
      setMessage(`Saved ${data.created_count} purchase candidate(s).`);
    } catch (error) {
      setMessage(formatActionError("Save failed", error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">BOM</h1>
        <p className="mt-1 text-sm text-slate-600">
          Preview spreadsheet rows, reconcile supplier and item matches, then analyze or reserve against the corrected set.
        </p>
      </section>

      <section className="panel p-4">
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-600">Spreadsheet-like BOM entry</p>
          <button className="button-subtle" onClick={addRow} type="button">
            Add Row
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Enter supplier and ordered item text as received, then use preview reconciliation before analysis or shortage follow-up.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-[700px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="px-2 py-2">Supplier</th>
                <th className="px-2 py-2">Item Number</th>
                <th className="px-2 py-2">Required Qty</th>
                <th className="px-2 py-2">-</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => (
                <tr key={idx} className="border-b border-slate-100">
                  <td className="px-2 py-2">
                    <CatalogPicker
                      allowedTypes={["supplier"]}
                      onChange={(value) => updateRow(idx, { supplier: value?.value_text ?? "" })}
                      onQueryChange={(value) => updateRow(idx, { supplier: value })}
                      placeholder="Type or search supplier"
                      recentKey="bom-supplier"
                      seedQuery={row.supplier}
                      value={null}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <CatalogPicker
                      allowedTypes={["item"]}
                      onChange={(value) => updateRow(idx, { item_number: value?.value_text ?? "" })}
                      onQueryChange={(value) => updateRow(idx, { item_number: value })}
                      placeholder="Type raw SKU or search item"
                      recentKey="bom-item"
                      seedQuery={row.item_number}
                      value={null}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      min={0}
                      onChange={(e) => updateRow(idx, { required_quantity: Number(e.target.value) })}
                      type="number"
                      value={row.required_quantity}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <button className="button-subtle" onClick={() => removeRow(idx)} type="button">
                      Del
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            className="input"
            onChange={(e) => {
              invalidateWorkingState();
              setTargetDate(e.target.value);
            }}
            title="BOM analysis target date"
            type="date"
            value={targetDate}
          />
          <button className="button" disabled={loading} onClick={previewReconciliation} type="button">
            Preview Reconciliation
          </button>
        </div>
        {!!message && <p className="mt-2 text-sm text-slate-700">{message}</p>}
      </section>

      {preview && (
        <section className="panel p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-display text-lg font-semibold">Preview</h2>
              <p className="mt-1 text-xs text-slate-500">
                High-confidence rows auto-use their suggestion if you do not override them. Review and unresolved rows need an explicit selection.
              </p>
            </div>
            <div className="text-xs text-slate-500">
              Analysis date: <strong>{preview.target_date ?? "current availability"}</strong>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full bg-emerald-50 px-3 py-1 font-semibold text-emerald-700">
              Exact {preview.summary.exact}
            </span>
            <span className="rounded-full bg-sky-50 px-3 py-1 font-semibold text-sky-700">
              High Confidence {preview.summary.high_confidence}
            </span>
            <span className="rounded-full bg-amber-50 px-3 py-1 font-semibold text-amber-700">
              Review {preview.summary.needs_review}
            </span>
            <span className="rounded-full bg-red-50 px-3 py-1 font-semibold text-red-700">
              Unresolved {preview.summary.unresolved}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="button" disabled={loading} onClick={analyzePreviewRows} type="button">
              Analyze
            </button>
            <button className="button-subtle" disabled={loading} onClick={reservePreviewRows} type="button">
              Reserve Available
            </button>
            <button className="button-subtle" disabled={loading} onClick={saveShortagesFromPreview} type="button">
              Save Shortages
            </button>
            <button className="button-subtle" disabled={loading} onClick={applyCorrectionsToGrid} type="button">
              Apply Corrections To Grid
            </button>
            <button className="button-subtle" disabled={loading} onClick={resetPreview} type="button">
              Clear Preview
            </button>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-[1400px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">Row</th>
                  <th className="px-2 py-2">Supplier</th>
                  <th className="px-2 py-2">Ordered Item</th>
                  <th className="px-2 py-2">Projection</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Reconcile</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => (
                  <tr key={row.row} className="border-b border-slate-100 align-top">
                    <td className="px-2 py-3 font-semibold">#{row.row}</td>
                    <td className="px-2 py-3">
                      <div className="space-y-1">
                        <p className="font-semibold text-slate-900">{row.supplier || "(blank)"}</p>
                        <p className="text-xs text-slate-500">
                          Supplier status: <span className="font-semibold">{statusLabel(row.supplier_status)}</span>
                        </p>
                        {displayPreviewSupplier(row) && displayPreviewSupplier(row)?.display_label !== row.supplier && (
                          <p className="text-xs text-slate-500">
                            Suggested: {displayPreviewSupplier(row)?.display_label}
                          </p>
                        )}
                      </div>
                    </td>
                    <td className="px-2 py-3">
                      <div className="space-y-1">
                        <p className="font-semibold text-slate-900">{row.item_number || "(blank)"}</p>
                        <p className="text-xs text-slate-500">
                          Item status: <span className="font-semibold">{statusLabel(row.item_status)}</span>
                        </p>
                        {displayPreviewItem(row) && (
                          <p className="text-xs text-slate-500">
                            Resolved: {displayPreviewItem(row)?.display_label}
                          </p>
                        )}
                      </div>
                    </td>
                    <td className="px-2 py-3">
                      {row.canonical_item_number ? (
                        <div className="space-y-1 text-xs text-slate-600">
                          <p>
                            Canonical: <span className="font-semibold text-slate-900">{row.canonical_item_number}</span>
                          </p>
                          <p>
                            Units/Order: <span className="font-semibold text-slate-900">{row.units_per_order ?? "-"}</span>
                          </p>
                          <p>
                            Requested: <span className="font-semibold text-slate-900">{row.required_quantity}</span>
                          </p>
                          <p>
                            Canonical Qty: <span className="font-semibold text-slate-900">{row.canonical_required_quantity ?? "-"}</span>
                          </p>
                          <p>
                            Available: <span className="font-semibold text-slate-900">{row.available_stock ?? "-"}</span>
                          </p>
                          <p>
                            Shortage: <span className="font-semibold text-slate-900">{row.shortage ?? "-"}</span>
                          </p>
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500">No projected stock yet.</p>
                      )}
                    </td>
                    <td className="px-2 py-3">
                      <div className="space-y-2">
                        <span
                          className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${previewStatusTone(row.status)}`}
                        >
                          {statusLabel(row.status)}
                        </span>
                        <p className="text-xs text-slate-600">{row.message}</p>
                      </div>
                    </td>
                    <td className="px-2 py-3">
                      <div className="space-y-3">
                        <div>
                          <p className="mb-1 text-xs font-semibold text-slate-600">Supplier override</p>
                          <CatalogPicker
                            allowedTypes={["supplier"]}
                            onChange={(value) => setPreviewSupplierSelection(row.row, value)}
                            placeholder="Search supplier"
                            recentKey="bom-preview-supplier"
                            seedQuery={row.supplier}
                            value={explicitPreviewSupplier(row)}
                          />
                          {row.supplier_candidates.length > 0 && (
                            <p className="mt-1 text-[11px] text-slate-500">
                              Top matches:{" "}
                              {row.supplier_candidates.slice(0, 2).map((candidate) => candidate.display_label).join(", ")}
                            </p>
                          )}
                        </div>
                        <div>
                          <p className="mb-1 text-xs font-semibold text-slate-600">Item override</p>
                          <CatalogPicker
                            allowedTypes={["item"]}
                            onChange={(value) => setPreviewItemSelection(row.row, value)}
                            placeholder="Search item"
                            recentKey="bom-preview-item"
                            seedQuery={row.item_number}
                            value={explicitPreviewItem(row)}
                          />
                          {row.candidates.length > 0 && (
                            <p className="mt-1 text-[11px] text-slate-500">
                              Top matches: {row.candidates.slice(0, 2).map((candidate) => candidate.display_label).join(", ")}
                            </p>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Result</h2>
        {!result && <p className="text-sm text-slate-500">No analysis yet.</p>}
        {result && (
          <div className="space-y-2 overflow-x-auto">
            <p className="text-xs text-slate-500">
              Analysis date: <strong>{result.target_date ?? "current availability"}</strong>
            </p>
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">Supplier</th>
                  <th className="px-2 py-2">Ordered Item</th>
                  <th className="px-2 py-2">Canonical Item</th>
                  <th className="px-2 py-2">Required</th>
                  <th className="px-2 py-2">Available</th>
                  <th className="px-2 py-2">Shortage</th>
                  <th className="px-2 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, idx) => (
                  <tr key={idx} className="border-b border-slate-100">
                    <td className="px-2 py-2">{String(row.supplier ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.ordered_item_number ?? row.item_number ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.canonical_item_number ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.required_quantity ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.available_stock ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.shortage ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.status ?? "-")}</td>
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
