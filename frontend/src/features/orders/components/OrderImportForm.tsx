import { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { MissingItemResolverRow, CatalogSearchResult } from "@/lib/types";
import { CatalogPicker } from "@/components/CatalogPicker";
import { ImportPreviewSummary } from "@/components/ImportPreviewSummary";
import type {
  GeneratedArtifact,
  OrderImportPreview,
  OrderImportPreviewRow,
  LockedPurchaseOrderPreview,
} from "@/features/orders/types";
import {
  downloadMissingRowsCsv,
  orderPreviewRowKey,
  purchaseOrderPreviewKey,
  previewStatusLabel,
  previewStatusTone,
  formatTimestamp,
} from "@/features/orders/utils";

export type OrderImportFormProps = {
  files: File[];
  setFiles: (files: File[]) => void;
  defaultDate: string;
  setDefaultDate: (date: string) => void;
  loading: boolean;
  message: string;
  latestGeneratedArtifact: GeneratedArtifact | null;
  missingRows: MissingItemResolverRow[];
  generatedArtifacts: GeneratedArtifact[];
  onPreviewImport: (event: FormEvent) => void;
  onResetImportPreview: () => void;
  onDownloadImportCsv: (path: string, fallbackFilename: string) => void;
  onDownloadGeneratedArtifact: (artifact: GeneratedArtifact) => void;
  // Import preview props
  importPreview: OrderImportPreview | null;
  previewSelections: Record<string, CatalogSearchResult | null>;
  previewUnits: Record<string, string>;
  previewAliasSaves: Record<string, boolean>;
  previewUnlocks: Record<string, boolean>;
  setPreviewSelections: React.Dispatch<React.SetStateAction<Record<string, CatalogSearchResult | null>>>;
  setPreviewUnits: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  setPreviewAliasSaves: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  setPreviewUnlocks: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  selectedPreviewMatch: (row: OrderImportPreviewRow) => CatalogSearchResult | null;
  previewUnitsValue: (row: OrderImportPreviewRow) => string;
  canOfferAliasSave: (row: OrderImportPreviewRow, selected: CatalogSearchResult | null) => boolean;
  unresolvedPreviewRows: () => MissingItemResolverRow[];
  onConfirmImportPreview: () => void;
};

export function OrderImportForm({
  files,
  setFiles,
  defaultDate,
  setDefaultDate,
  loading,
  message,
  latestGeneratedArtifact,
  missingRows,
  generatedArtifacts,
  onPreviewImport,
  onResetImportPreview,
  onDownloadImportCsv,
  onDownloadGeneratedArtifact,
  importPreview,
  previewSelections,
  previewUnits,
  previewAliasSaves,
  previewUnlocks,
  setPreviewSelections,
  setPreviewUnits,
  setPreviewAliasSaves,
  setPreviewUnlocks,
  selectedPreviewMatch,
  previewUnitsValue,
  canOfferAliasSave,
  unresolvedPreviewRows,
  onConfirmImportPreview,
}: OrderImportFormProps) {
  const navigate = useNavigate();

  return (
    <>
      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Import Purchase Order Lines CSV</h2>
        <div className="mb-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
          <p className="font-semibold text-slate-900">CSV Format</p>
          <p className="mt-1">
            Required columns: <code>supplier</code>, <code>item_number</code>, <code>quantity</code>,{" "}
            <code>purchase_order_number</code>, <code>quotation_number</code>, <code>issue_date</code>
          </p>
          <p>
            Required document column: <code>quotation_document_url</code>
          </p>
          <p>
            Optional columns: <code>order_date</code>, <code>expected_arrival</code>,{" "}
            <code>purchase_order_document_url</code>
          </p>
          <p className="mt-1">
            Use normalized document references for quotation and purchase-order metadata. HTTPS values open as links.
          </p>
          <p>
            This import path is metadata-only. Documents remain in the external document system and are not uploaded into this application.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              className="button-subtle"
              type="button"
              onClick={() => onDownloadImportCsv("/purchase-order-lines/import-template", "purchase_order_lines_import_template.csv")}
            >
              Download Template CSV
            </button>
            <button
              className="button-subtle"
              type="button"
              onClick={() => onDownloadImportCsv("/purchase-order-lines/import-reference", "purchase_order_lines_import_reference.csv")}
            >
              Download Reference CSV
            </button>
          </div>
        </div>
        <form className="grid gap-3 md:grid-cols-3" onSubmit={onPreviewImport}>
          <input
            className="input"
            type="date"
            value={defaultDate}
            onChange={(e) => {
              setDefaultDate(e.target.value);
              onResetImportPreview();
            }}
          />
          <input
            className="input"
            type="file"
            accept=".csv,text/csv"
            multiple
            onChange={(e) => {
              setFiles(Array.from(e.target.files ?? []));
              onResetImportPreview();
            }}
            required
          />
          <button className="button" disabled={loading} type="submit">
            Preview Import
          </button>
        </form>
        <p className="mt-2 text-xs text-slate-500">
          {files.length > 0
            ? `${files.length} file(s) selected`
            : "Select one or more order CSV files. Supplier must be present in every row."}
        </p>
        {message && (
          <div className="mt-3 space-y-2">
            <p className="text-sm text-signal">{message}</p>
            {latestGeneratedArtifact && (
              <button
                className="button-subtle"
                type="button"
                onClick={() => onDownloadGeneratedArtifact(latestGeneratedArtifact)}
              >
                Download Generated CSV
              </button>
            )}
          </div>
        )}
        {importPreview && (
          <div className="mt-4 space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-900">Import Preview</p>
                <p className="mt-1 text-xs text-slate-600">
                  Combined preview across {files.length} file(s). Supplier is resolved per row from the CSV content.
                </p>
              </div>
              <ImportPreviewSummary summary={importPreview.summary} />
            </div>

            {importPreview.blocking_errors.length > 0 && (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                {importPreview.blocking_errors.map((errorText, index) => (
                  <p key={`${errorText}-${index}`}>{errorText}</p>
                ))}
              </div>
            )}

            {(importPreview.locked_purchase_orders ?? []).length > 0 && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <p className="font-semibold">Locked purchase orders</p>
                <div className="mt-2 space-y-2">
                  {(importPreview.locked_purchase_orders ?? []).map((locked) => (
                    <label
                      key={purchaseOrderPreviewKey(locked)}
                      className="flex items-start gap-2 rounded-lg border border-amber-200 bg-white/70 px-3 py-2"
                    >
                      <input
                        checked={previewUnlocks[purchaseOrderPreviewKey(locked)] ?? false}
                        onChange={(event) =>
                          setPreviewUnlocks((prev) => ({
                            ...prev,
                            [purchaseOrderPreviewKey(locked)]: event.target.checked,
                          }))
                        }
                        type="checkbox"
                      />
                      <span>
                        <span className="font-medium">
                          {locked.supplier_name} / {locked.purchase_order_number}
                        </span>
                        <span className="block text-xs text-amber-800">
                          Check to unlock this purchase order and allow import.
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {unresolvedPreviewRows().length > 0 && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 space-y-2">
                <p className="text-sm font-semibold text-amber-900">
                  {unresolvedPreviewRows().length} unresolved item(s) — not yet registered in the catalog
                </p>
                <ol className="list-decimal list-inside text-xs text-amber-800 space-y-1">
                  <li>Download the missing-items CSV below.</li>
                  <li>Go to the <span className="font-semibold">Items</span> page and import it to register the new items.</li>
                  <li>Return here and <span className="font-semibold">re-import the same order file</span> — the newly registered items will now resolve.</li>
                </ol>
                <div className="flex flex-wrap gap-2 pt-1">
                  <button
                    className="button-subtle"
                    type="button"
                    onClick={() =>
                      downloadMissingRowsCsv(
                        unresolvedPreviewRows(),
                        "orders_preview_missing_items.csv"
                      )
                    }
                  >
                    Download Missing Items CSV
                  </button>
                  <button className="button-subtle" type="button" onClick={() => navigate("/items")}>
                    Open Items Page
                  </button>
                </div>
              </div>
            )}

            <div className="overflow-x-auto">
              <table className="min-w-[1100px] text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="px-2 py-2">Row</th>
                    <th className="px-2 py-2">Raw Input</th>
                    <th className="px-2 py-2">Suggested Canonical Match</th>
                    <th className="px-2 py-2">Confidence</th>
                    <th className="px-2 py-2">Status</th>
                    <th className="px-2 py-2">User Action</th>
                  </tr>
                </thead>
                <tbody>
                  {importPreview.rows.map((row) => {
                    const selection = selectedPreviewMatch(row);
                    const canSaveAlias = canOfferAliasSave(row, selection);
                    return (
                      <tr key={orderPreviewRowKey(row)} className="border-b border-slate-100 align-top">
                        <td className="px-2 py-3 font-semibold text-slate-700">#{row.row}</td>
                        <td className="px-2 py-3">
                          <div className="space-y-1">
                            <div className="flex flex-wrap items-start gap-2">
                              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                                  Item Number
                                </p>
                                <p className="font-semibold text-slate-900">{row.item_number}</p>
                              </div>
                              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
                                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-700">
                                  Quantity
                                </p>
                                <p className="text-lg font-semibold leading-none text-emerald-900">
                                  {row.quantity}
                                </p>
                              </div>
                            </div>
                            <p className="text-xs text-slate-500">
                              {row.source_name ? `${row.source_name} | ` : ""}
                              {row.supplier_name} | PO {row.purchase_order_number} | quotation {row.quotation_number}
                            </p>
                            <p className="text-xs text-slate-500">
                              order {row.order_date}
                              {row.expected_arrival ? ` | eta ${row.expected_arrival}` : ""}
                            </p>
                            {row.quotation_document_url && (
                              <p className="text-xs text-slate-500 break-all">{row.quotation_document_url}</p>
                            )}
                            {row.purchase_order_document_url && (
                              <p className="text-xs text-slate-500 break-all">{row.purchase_order_document_url}</p>
                            )}
                            {row.warnings.map((warning, index) => (
                              <p key={`${warning}-${index}`} className="text-xs font-semibold text-red-600">
                                {warning}
                              </p>
                            ))}
                          </div>
                        </td>
                        <td className="px-2 py-3">
                          {row.suggested_match ? (
                            <div className="space-y-1">
                              <p className="font-semibold text-slate-900">
                                {row.suggested_match.display_label}
                              </p>
                              <p className="text-xs text-slate-500">
                                units/order {row.suggested_match.units_per_order}
                              </p>
                              {row.suggested_match.summary && (
                                <p className="text-xs text-slate-500">
                                  {row.suggested_match.summary}
                                </p>
                              )}
                              {row.candidates.length > 1 && (
                                <p className="text-xs text-slate-400">
                                  {row.candidates.length} ranked candidates available
                                </p>
                              )}
                            </div>
                          ) : (
                            <p className="text-sm text-slate-500">No confident suggestion</p>
                          )}
                        </td>
                        <td className="px-2 py-3">
                          {row.confidence_score == null ? "-" : `${row.confidence_score}%`}
                        </td>
                        <td className="px-2 py-3">
                          <span
                            className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${previewStatusTone(row.status)}`}
                          >
                            {previewStatusLabel(row.status)}
                          </span>
                        </td>
                        <td className="px-2 py-3">
                          <div className="space-y-2">
                            <CatalogPicker
                              allowedTypes={["item"]}
                              onChange={(value) =>
                                setPreviewSelections((prev) => ({
                                  ...prev,
                                  [orderPreviewRowKey(row)]: value,
                                }))
                              }
                              placeholder="Search canonical item"
                              recentKey="orders-import-preview-item"
                              value={selection ?? null}
                            />
                            <div className="flex flex-wrap gap-2">
                              <input
                                className="input w-28"
                                min={1}
                                type="number"
                                value={previewUnitsValue(row)}
                                onChange={(event) =>
                                  setPreviewUnits((prev) => ({
                                    ...prev,
                                    [orderPreviewRowKey(row)]: event.target.value,
                                  }))
                                }
                              />
                              <span className="self-center text-xs text-slate-500">
                                units/order
                              </span>
                            </div>
                            {canSaveAlias && (
                              <label className="flex items-center gap-2 text-xs text-slate-600">
                                <input
                                  checked={previewAliasSaves[orderPreviewRowKey(row)] ?? false}
                                  onChange={(event) =>
                                    setPreviewAliasSaves((prev) => ({
                                      ...prev,
                                      [orderPreviewRowKey(row)]: event.target.checked,
                                    }))
                                  }
                                  type="checkbox"
                                />
                                Save supplier alias after import
                              </label>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap gap-2">
                <button
                  className="button"
                  disabled={loading}
                  onClick={() => void onConfirmImportPreview()}
                  type="button"
                >
                Confirm Import
              </button>
              <button
                className="button-subtle"
                disabled={loading}
                onClick={onResetImportPreview}
                type="button"
              >
                Clear Preview
              </button>
              <p className="self-center text-xs text-slate-500">
                High-confidence rows can be confirmed directly; review and unresolved rows can be adjusted here before commit.
              </p>
            </div>
          </div>
        )}
        {missingRows.length > 0 && (
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3">
            <p className="mb-2 text-sm font-semibold text-amber-900">
              Unresolved item numbers in this upload
            </p>
            <ol className="mb-2 list-decimal list-inside text-xs text-amber-800 space-y-1">
              <li>Download the generated CSV and import it on the <span className="font-semibold">Items</span> page to register missing items.</li>
              <li>Then <span className="font-semibold">re-import the same order file here</span> — previously unresolved rows will match.</li>
            </ol>
            <div className="mb-2 flex flex-wrap gap-2">
              {latestGeneratedArtifact && (
                <button
                  className="button-subtle"
                  type="button"
                  onClick={() => onDownloadGeneratedArtifact(latestGeneratedArtifact)}
                >
                  Download Generated CSV
                </button>
              )}
              <button className="button-subtle" type="button" onClick={() => navigate("/items")}>
                Open Items Page
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-[460px] text-sm">
                <thead>
                  <tr className="border-b border-amber-200 text-left text-amber-800">
                    <th className="px-2 py-2">CSV Row</th>
                    <th className="px-2 py-2">Supplier</th>
                    <th className="px-2 py-2">Item Number</th>
                  </tr>
                </thead>
                <tbody>
                  {missingRows.map((row, idx) => (
                    <tr key={`${row.item_number}-${idx}`} className="border-b border-amber-100">
                      <td className="px-2 py-2">{row.row ?? "-"}</td>
                      <td className="px-2 py-2">{row.supplier ?? "-"}</td>
                      <td className="px-2 py-2 font-semibold">{row.item_number}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      <section className="panel p-4">
        {generatedArtifacts.length > 0 && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
            <h3 className="font-medium text-slate-900">Recent Generated Files</h3>
            <p className="mt-1 text-xs text-slate-500">
              Browser download list only. Filesystem storage paths are intentionally hidden.
            </p>
            <div className="mt-2 space-y-2">
              {generatedArtifacts.slice(0, 5).map((artifact) => (
                <div
                  key={artifact.artifact_id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2"
                >
                  <div className="text-sm text-slate-700">
                    <p className="font-medium text-slate-900">{artifact.filename}</p>
                    <p className="text-xs text-slate-500">
                      Created {formatTimestamp(artifact.created_at)} · {(artifact.size_bytes / 1024).toFixed(1)} KB
                    </p>
                  </div>
                  <button
                    className="button-subtle"
                    type="button"
                    onClick={() => onDownloadGeneratedArtifact(artifact)}
                  >
                    Download
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </>
  );
}
