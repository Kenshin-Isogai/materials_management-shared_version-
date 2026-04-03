import type { Dispatch, SetStateAction } from "react";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import type { Item } from "@/lib/types";
import type { ItemEditDraft } from "@/features/items/types";

type SortKey = "item_id" | "item_number" | "manufacturer_name" | "category" | "url";

export interface ItemBrowseTableProps {
  sortedItems: Item[];
  isLoading: boolean;
  error: unknown;
  isItemListExpanded: boolean;
  setIsItemListExpanded: Dispatch<SetStateAction<boolean>>;
  q: string;
  setQ: Dispatch<SetStateAction<string>>;
  listMessage: string;
  listBusy: boolean;
  editingItemId: number | null;
  editDraft: ItemEditDraft | null;
  setEditDraft: Dispatch<SetStateAction<ItemEditDraft | null>>;
  sortKey: SortKey;
  sortDirection: "asc" | "desc";
  hasData: boolean;
  onToggleSort: (key: SortKey) => void;
  onStartEdit: (item: Item) => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onRemoveItem: (item: Item) => void;
  onSelectFlowItem: (itemId: number) => void;
}

export function ItemBrowseTable({
  sortedItems,
  isLoading,
  error,
  isItemListExpanded,
  setIsItemListExpanded,
  q,
  setQ,
  listMessage,
  listBusy,
  editingItemId,
  editDraft,
  setEditDraft,
  sortKey,
  sortDirection,
  hasData,
  onToggleSort,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onRemoveItem,
  onSelectFlowItem,
}: ItemBrowseTableProps) {
  function sortIndicator(key: SortKey): string {
    if (key !== sortKey) return "↕";
    return sortDirection === "asc" ? "↑" : "↓";
  }

  return (
    <section className="panel p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="font-display text-lg font-semibold">Item List</h2>
        <button
          type="button"
          className="button-subtle"
          onClick={() => setIsItemListExpanded((prev) => !prev)}
          aria-expanded={isItemListExpanded}
        >
          {isItemListExpanded ? "Collapse" : "Expand"}
        </button>
        <input
          className="input w-80"
          placeholder="Search keywords (space = AND)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      {listMessage && <p className="mb-2 text-sm text-signal">{listMessage}</p>}
      <p className="mb-2 text-xs text-slate-500">
        Referenced items can update metadata, but item number/manufacturer changes are blocked.
      </p>
      {isItemListExpanded && isLoading && <p className="text-sm text-slate-500">Loading...</p>}
      {isItemListExpanded && error ? <ApiErrorNotice error={error} area="item list data" /> : null}
      {isItemListExpanded && hasData && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="px-2 py-2"><button type="button" onClick={() => onToggleSort("item_id")}>ID {sortIndicator("item_id")}</button></th>
                <th className="px-2 py-2"><button type="button" onClick={() => onToggleSort("item_number")}>Item Number {sortIndicator("item_number")}</button></th>
                <th className="px-2 py-2"><button type="button" onClick={() => onToggleSort("manufacturer_name")}>Manufacturer {sortIndicator("manufacturer_name")}</button></th>
                <th className="px-2 py-2"><button type="button" onClick={() => onToggleSort("category")}>Category {sortIndicator("category")}</button></th>
                <th className="px-2 py-2"><button type="button" onClick={() => onToggleSort("url")}>URL {sortIndicator("url")}</button></th>
                <th className="px-2 py-2">Description</th>
                <th className="px-2 py-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {sortedItems.map((item) => (
                <tr key={item.item_id} className="border-b border-slate-100">
                  <td className="px-2 py-2">{item.item_id}</td>
                  <td className="px-2 py-2 font-semibold">
                    {editingItemId === item.item_id ? (
                      <input
                        className="input"
                        value={editDraft?.item_number ?? ""}
                        onChange={(e) =>
                          setEditDraft((prev) => (prev ? { ...prev, item_number: e.target.value } : prev))
                        }
                      />
                    ) : (
                      item.item_number
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {editingItemId === item.item_id ? (
                      <input
                        className="input"
                        value={editDraft?.manufacturer_name ?? ""}
                        onChange={(e) =>
                          setEditDraft((prev) =>
                            prev ? { ...prev, manufacturer_name: e.target.value } : prev
                          )
                        }
                      />
                    ) : (
                      item.manufacturer_name
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {editingItemId === item.item_id ? (
                      <input
                        className="input"
                        value={editDraft?.category ?? ""}
                        onChange={(e) =>
                          setEditDraft((prev) => (prev ? { ...prev, category: e.target.value } : prev))
                        }
                      />
                    ) : (
                      item.category ?? "-"
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {editingItemId === item.item_id ? (
                      <input
                        className="input"
                        value={editDraft?.url ?? ""}
                        onChange={(e) =>
                          setEditDraft((prev) => (prev ? { ...prev, url: e.target.value } : prev))
                        }
                      />
                    ) : (
                      item.url ? (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 underline"
                        >
                          {item.url}
                        </a>
                      ) : (
                        "-"
                      )
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {editingItemId === item.item_id ? (
                      <input
                        className="input"
                        value={editDraft?.description ?? ""}
                        onChange={(e) =>
                          setEditDraft((prev) => (prev ? { ...prev, description: e.target.value } : prev))
                        }
                      />
                    ) : (
                      item.description ?? "-"
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {editingItemId === item.item_id ? (
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="button-subtle"
                          type="button"
                          disabled={listBusy}
                          onClick={onSaveEdit}
                        >
                          Save
                        </button>
                        <button
                          className="button-subtle"
                          type="button"
                          disabled={listBusy}
                          onClick={onCancelEdit}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="button-subtle"
                          type="button"
                          disabled={listBusy}
                          onClick={() => onStartEdit(item)}
                        >
                          Edit
                        </button>
                        <button
                          className="button-subtle"
                          type="button"
                          disabled={listBusy}
                          onClick={() => onSelectFlowItem(item.item_id)}
                        >
                          Flow
                        </button>
                        <button
                          className="button-subtle"
                          type="button"
                          disabled={listBusy}
                          onClick={() => onRemoveItem(item)}
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
