import type { Dispatch, SetStateAction } from "react";
import type { CatalogSearchResult } from "@/lib/types";
import { CatalogPicker } from "@/components/CatalogPicker";
import type { ItemImportPreview as ItemImportPreviewType, ItemImportPreviewRow } from "@/features/items/types";
import { itemImportPreviewRowKey, previewStatusTone } from "@/features/items/utils";

export interface ItemImportPreviewProps {
  csvPreview: ItemImportPreviewType;
  showCsvSourceColumn: boolean;
  submitting: boolean;
  onConfirm: () => void;
  onClearPreview: () => void;
  selectedCsvPreviewMatch: (row: ItemImportPreviewRow) => CatalogSearchResult | null;
  previewUnitsValue: (row: ItemImportPreviewRow) => string;
  setCsvPreviewSelections: Dispatch<SetStateAction<Record<string, CatalogSearchResult | null>>>;
  setCsvPreviewUnits: Dispatch<SetStateAction<Record<string, string>>>;
}

export function ItemImportPreview({
  csvPreview,
  showCsvSourceColumn,
  submitting,
  onConfirm,
  onClearPreview,
  selectedCsvPreviewMatch,
  previewUnitsValue,
  setCsvPreviewSelections,
  setCsvPreviewUnits,
}: ItemImportPreviewProps) {
  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded-full bg-emerald-50 px-3 py-1 font-semibold text-emerald-700">
          Exact {csvPreview.summary.exact}
        </span>
        <span className="rounded-full bg-sky-50 px-3 py-1 font-semibold text-sky-700">
          High Confidence {csvPreview.summary.high_confidence}
        </span>
        <span className="rounded-full bg-amber-50 px-3 py-1 font-semibold text-amber-700">
          Review {csvPreview.summary.needs_review}
        </span>
        <span className="rounded-full bg-red-50 px-3 py-1 font-semibold text-red-700">
          Unresolved {csvPreview.summary.unresolved}
        </span>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="min-w-[1260px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              {showCsvSourceColumn && <th className="px-2 py-2">File</th>}
              <th className="px-2 py-2">Row</th>
              <th className="px-2 py-2">Type</th>
              <th className="px-2 py-2">Input</th>
              <th className="px-2 py-2">Resolved Canonical</th>
              <th className="px-2 py-2">Status</th>
              <th className="px-2 py-2">Action</th>
            </tr>
          </thead>
          <tbody>
            {csvPreview.rows.map((row) => (
              <tr key={itemImportPreviewRowKey(row)} className="border-b border-slate-100 align-top">
                {showCsvSourceColumn && <td className="px-2 py-3">{row.source_name ?? "-"}</td>}
                <td className="px-2 py-3 font-semibold">#{row.row}</td>
                <td className="px-2 py-3">
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
                    {row.entry_type}
                  </span>
                </td>
                <td className="px-2 py-3">
                  <div className="space-y-1">
                    <p className="font-semibold text-slate-900">{row.item_number || "No item number"}</p>
                    {row.entry_type === "item" ? (
                      <>
                        <p className="text-xs text-slate-500">{row.manufacturer_name}</p>
                        {row.category && <p className="text-xs text-slate-500">{row.category}</p>}
                      </>
                    ) : (
                      <>
                        <p className="text-xs text-slate-500">supplier {row.supplier || "-"}</p>
                        <p className="text-xs text-slate-500">
                          canonical {row.canonical_item_number || "-"} | units {previewUnitsValue(row)}
                        </p>
                      </>
                    )}
                    {row.description && (
                      <p className="text-xs text-slate-500">{row.description}</p>
                    )}
                  </div>
                </td>
                <td className="px-2 py-3">
                  {selectedCsvPreviewMatch(row) ? (
                    <div className="space-y-1">
                      <p className="font-semibold text-slate-900">
                        {selectedCsvPreviewMatch(row)?.display_label}
                      </p>
                      {selectedCsvPreviewMatch(row)?.summary && (
                        <p className="text-xs text-slate-500">
                          {selectedCsvPreviewMatch(row)?.summary}
                        </p>
                      )}
                    </div>
                  ) : row.suggested_match ? (
                    <div className="space-y-1">
                      <p className="font-semibold text-slate-900">
                        {row.suggested_match.display_label}
                      </p>
                      {row.suggested_match.summary && (
                        <p className="text-xs text-slate-500">{row.suggested_match.summary}</p>
                      )}
                      {row.suggested_match.match_reason && (
                        <p className="text-xs text-slate-500">{row.suggested_match.match_reason}</p>
                      )}
                    </div>
                  ) : row.entry_type === "item" ? (
                    <p className="text-sm text-slate-500">Create new item</p>
                  ) : (
                    <p className="text-sm text-slate-500">
                      {row.canonical_item_number || "Select canonical item"}
                    </p>
                  )}
                </td>
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
                    {row.entry_type === "alias" && (
                      <div className="space-y-2">
                        <CatalogPicker
                          allowedTypes={["item"]}
                          onChange={(value) =>
                            setCsvPreviewSelections((prev) => ({
                              ...prev,
                              [itemImportPreviewRowKey(row)]: value,
                            }))
                          }
                          placeholder="Select canonical item"
                          recentKey="items-import-preview-canonical-item"
                          seedQuery={row.canonical_item_number}
                          value={selectedCsvPreviewMatch(row)}
                        />
                        <input
                          className="input max-w-[180px]"
                          min={1}
                          onChange={(e) =>
                            setCsvPreviewUnits((prev) => ({
                              ...prev,
                              [itemImportPreviewRowKey(row)]: e.target.value,
                            }))
                          }
                          placeholder="Units per order"
                          step={1}
                          type="number"
                          value={previewUnitsValue(row)}
                        />
                        {row.candidates.length > 1 && (
                          <p className="text-xs text-slate-500">
                            Candidates:{" "}
                            {row.candidates
                              .slice(0, 3)
                              .map((candidate) => candidate.display_label)
                              .join(" | ")}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          className="button"
          disabled={submitting}
          onClick={onConfirm}
          type="button"
        >
          Confirm Import
        </button>
        <button
          className="button-subtle"
          disabled={submitting}
          onClick={onClearPreview}
          type="button"
        >
          Clear Preview
        </button>
      </div>
    </div>
  );
}
