import type { Dispatch, SetStateAction } from "react";
import type { Item } from "@/lib/types";
import type { ItemEntryRow, ItemRowType } from "@/features/items/types";
import { blankRow } from "@/features/items/utils";

export interface BulkItemEntryProps {
  bulkRows: ItemEntryRow[];
  setBulkRows: Dispatch<SetStateAction<ItemEntryRow[]>>;
  itemOptions: Item[];
  submitting: boolean;
  entryMessage: string;
  onCreateBulk: () => void;
}

export function BulkItemEntry({
  bulkRows,
  setBulkRows,
  itemOptions,
  submitting,
  entryMessage,
  onCreateBulk,
}: BulkItemEntryProps) {
  function updateBulkRow(index: number, patch: Partial<ItemEntryRow>) {
    setBulkRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeBulkRow(index: number) {
    setBulkRows((prev) => prev.filter((_, i) => i !== index));
  }

  const itemLabel = (item: Item) => `${item.item_number} (${item.manufacturer_name}) #${item.item_id}`;

  return (
    <>
      <section>
        <div className="panel space-y-3 p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-lg font-semibold">Bulk Item Entry</h2>
            <button
              className="button-subtle"
              type="button"
              onClick={() => setBulkRows((prev) => [...prev, blankRow()])}
            >
              Add Row
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-[1280px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="min-w-[110px] px-2 py-2">Type</th>
                  <th className="px-2 py-2">Item Number</th>
                  <th className="px-2 py-2">Manufacturer</th>
                  <th className="px-2 py-2">Alias Supplier</th>
                  <th className="px-2 py-2">Canonical Item (alias)</th>
                  <th className="px-2 py-2">Units/Order (alias)</th>
                  <th className="px-2 py-2">Category</th>
                  <th className="px-2 py-2">URL</th>
                  <th className="px-2 py-2">Description</th>
                  <th className="px-2 py-2">-</th>
                </tr>
              </thead>
              <tbody>
                {bulkRows.map((row, idx) => (
                  <tr key={idx} className="border-b border-slate-100">
                    <td className="min-w-[110px] px-2 py-2">
                      <select
                        className="input min-w-[110px]"
                        value={row.row_type}
                        onChange={(e) =>
                          updateBulkRow(idx, { row_type: e.target.value as ItemRowType })
                        }
                      >
                        <option value="item">item</option>
                        <option value="alias">alias</option>
                      </select>
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.item_number}
                        onChange={(e) => updateBulkRow(idx, { item_number: e.target.value })}
                        placeholder={row.row_type === "alias" ? "ER2-P4" : "LENS-001"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.manufacturer_name}
                        onChange={(e) => updateBulkRow(idx, { manufacturer_name: e.target.value })}
                        placeholder="Thorlabs"
                        disabled={row.row_type === "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.supplier}
                        onChange={(e) => updateBulkRow(idx, { supplier: e.target.value })}
                        placeholder="Supplier for alias"
                        disabled={row.row_type !== "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <select
                        className="input"
                        value={row.canonical_item_number}
                        onChange={(e) => updateBulkRow(idx, { canonical_item_number: e.target.value })}
                        disabled={row.row_type !== "alias"}
                      >
                        <option value="">Select canonical item</option>
                        {itemOptions.map((item) => (
                          <option key={item.item_id} value={item.item_number}>
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
                        step={1}
                        value={row.units_per_order}
                        onChange={(e) => updateBulkRow(idx, { units_per_order: e.target.value })}
                        placeholder="1"
                        disabled={row.row_type !== "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.category}
                        onChange={(e) => updateBulkRow(idx, { category: e.target.value })}
                        placeholder="Lens"
                        disabled={row.row_type === "alias"}
                        list="category-options"
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.url}
                        onChange={(e) => updateBulkRow(idx, { url: e.target.value })}
                        placeholder="https://..."
                        disabled={row.row_type === "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.description}
                        onChange={(e) => updateBulkRow(idx, { description: e.target.value })}
                        placeholder="notes"
                        disabled={row.row_type === "alias"}
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
          <p className="text-xs text-slate-500">
            Alias supplier means the supplier namespace where the ordered SKU alias is defined.
          </p>
          <button className="button w-full" disabled={submitting} onClick={onCreateBulk}>
            Submit Bulk Rows
          </button>
        </div>
      </section>
      {entryMessage && <p className="text-sm text-signal">{entryMessage}</p>}
    </>
  );
}
