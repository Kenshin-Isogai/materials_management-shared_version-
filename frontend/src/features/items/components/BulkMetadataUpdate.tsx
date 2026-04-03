import type { Dispatch, SetStateAction } from "react";
import type { MetadataBulkRow, MetadataBulkResult, MetadataBulkResultRow } from "@/features/items/types";
import { blankMetadataRow } from "@/features/items/utils";

export interface BulkMetadataUpdateProps {
  metadataRows: MetadataBulkRow[];
  setMetadataRows: Dispatch<SetStateAction<MetadataBulkRow[]>>;
  metadataMessage: string;
  metadataResult: MetadataBulkResult | null;
  metadataBusy: boolean;
  onSubmit: () => void;
  onReset: () => void;
}

export function BulkMetadataUpdate({
  metadataRows,
  setMetadataRows,
  metadataMessage,
  metadataResult,
  metadataBusy,
  onSubmit,
  onReset,
}: BulkMetadataUpdateProps) {
  function updateMetadataRow(index: number, patch: Partial<MetadataBulkRow>) {
    setMetadataRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeMetadataRow(index: number) {
    setMetadataRows((prev) => prev.filter((_, i) => i !== index));
  }

  const metadataIssues = (metadataResult?.rows ?? []).filter(
    (row: MetadataBulkResultRow) => row.status === "error"
  );

  return (
    <section className="panel p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-lg font-semibold">Bulk Metadata Update</h2>
        <button
          className="button-subtle"
          type="button"
          onClick={() => setMetadataRows((prev) => [...prev, blankMetadataRow()])}
        >
          Add Row
        </button>
      </div>
      <p className="text-sm text-slate-600">
        Update only <code>category</code>, <code>url</code>, and <code>description</code> in
        bulk. Item identity fields are not part of this flow.
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="min-w-[920px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              <th className="px-2 py-2">Item ID</th>
              <th className="px-2 py-2">Category</th>
              <th className="px-2 py-2">URL</th>
              <th className="px-2 py-2">Description</th>
              <th className="px-2 py-2">-</th>
            </tr>
          </thead>
          <tbody>
            {metadataRows.map((row, idx) => (
              <tr key={idx} className="border-b border-slate-100">
                <td className="px-2 py-2">
                  <input
                    className="input"
                    type="number"
                    min={1}
                    step={1}
                    value={row.item_id}
                    onChange={(e) => updateMetadataRow(idx, { item_id: e.target.value })}
                    placeholder="123"
                  />
                </td>
                <td className="px-2 py-2">
                  <input
                    className="input"
                    value={row.category}
                    onChange={(e) => updateMetadataRow(idx, { category: e.target.value })}
                    list="category-options"
                  />
                </td>
                <td className="px-2 py-2">
                  <input
                    className="input"
                    value={row.url}
                    onChange={(e) => updateMetadataRow(idx, { url: e.target.value })}
                    placeholder="https://..."
                  />
                </td>
                <td className="px-2 py-2">
                  <input
                    className="input"
                    value={row.description}
                    onChange={(e) => updateMetadataRow(idx, { description: e.target.value })}
                    placeholder="notes"
                  />
                </td>
                <td className="px-2 py-2">
                  <button className="button-subtle" type="button" onClick={() => removeMetadataRow(idx)}>
                    Del
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="button" type="button" disabled={metadataBusy} onClick={onSubmit}>
          Apply Bulk Metadata
        </button>
        <button
          className="button-subtle"
          type="button"
          disabled={metadataBusy}
          onClick={onReset}
        >
          Reset
        </button>
      </div>
      {metadataMessage && <p className="mt-2 text-sm text-signal">{metadataMessage}</p>}
      {metadataIssues.length > 0 && (
        <div className="mt-3 overflow-x-auto rounded-xl border border-amber-200 bg-amber-50 p-3">
          <p className="mb-2 text-sm font-semibold text-amber-900">Bulk metadata issues</p>
          <table className="min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-amber-200 text-left text-amber-800">
                <th className="px-2 py-2">Row</th>
                <th className="px-2 py-2">Item ID</th>
                <th className="px-2 py-2">Code</th>
                <th className="px-2 py-2">Message</th>
              </tr>
            </thead>
            <tbody>
              {metadataIssues.map((row, idx) => (
                <tr key={`${row.row}-${idx}`} className="border-b border-amber-100">
                  <td className="px-2 py-2">{row.row}</td>
                  <td className="px-2 py-2">{row.item_id}</td>
                  <td className="px-2 py-2">{row.code ?? "-"}</td>
                  <td className="px-2 py-2">{row.error ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
