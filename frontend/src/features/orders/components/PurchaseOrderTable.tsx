import React from "react";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import type { Order, PurchaseOrder, Quotation } from "@/lib/types";
import { summaryMetric, renderDocumentReference } from "@/features/orders/utils";

export type PurchaseOrderTableProps = {
  purchaseOrdersData: PurchaseOrder[] | undefined;
  filteredPurchaseOrders: PurchaseOrder[];
  purchaseOrderLines: Order[];
  purchaseOrderQuotations: Quotation[];
  selectedPurchaseOrder: PurchaseOrder | null;
  purchaseOrdersLoading: boolean;
  purchaseOrdersError: unknown;
  loading: boolean;
  selectedPurchaseOrderId: number | null;
  editingPurchaseOrderId: number | null;
  editingPurchaseOrderNumber: string;
  editingPurchaseOrderDocumentUrl: string;
  editingPurchaseOrderImportLocked: boolean;
  purchaseOrderSearch: string;
  purchaseOrderDetailsRef: React.Ref<HTMLDivElement>;
  setPurchaseOrderSearch: (value: string) => void;
  setSelectedPurchaseOrderId: (id: number | null) => void;
  setEditingPurchaseOrderId: (id: number | null) => void;
  setEditingPurchaseOrderNumber: (value: string) => void;
  setEditingPurchaseOrderDocumentUrl: (value: string) => void;
  setEditingPurchaseOrderImportLocked: (value: boolean) => void;
  openPurchaseOrderDetails: (purchaseOrderId: number) => void;
  openOrderDetails: (orderId: number) => void;
  beginEditPurchaseOrder: (row: PurchaseOrder) => void;
  savePurchaseOrderEdit: (purchaseOrderId: number) => void;
  deletePurchaseOrder: (purchaseOrderId: number) => void;
};

export function PurchaseOrderTable({
  purchaseOrdersData,
  filteredPurchaseOrders,
  purchaseOrderLines,
  purchaseOrderQuotations,
  selectedPurchaseOrder,
  purchaseOrdersLoading,
  purchaseOrdersError,
  loading,
  selectedPurchaseOrderId,
  editingPurchaseOrderId,
  editingPurchaseOrderNumber,
  editingPurchaseOrderDocumentUrl,
  editingPurchaseOrderImportLocked,
  purchaseOrderSearch,
  purchaseOrderDetailsRef,
  setPurchaseOrderSearch,
  setSelectedPurchaseOrderId,
  setEditingPurchaseOrderId,
  setEditingPurchaseOrderNumber,
  setEditingPurchaseOrderDocumentUrl,
  setEditingPurchaseOrderImportLocked,
  openPurchaseOrderDetails,
  openOrderDetails,
  beginEditPurchaseOrder,
  savePurchaseOrderEdit,
  deletePurchaseOrder,
}: PurchaseOrderTableProps) {
  return (
    <div className="panel flex min-h-[46rem] flex-col p-4">
      <div className="mb-3">
        <h2 className="font-display text-lg font-semibold">Purchase Orders</h2>
        <p className="mt-1 text-sm text-slate-500">Purchase-order headers, separated from the line rows they own.</p>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {summaryMetric("Total purchase orders", purchaseOrdersData?.length ?? 0, "emerald")}
        {summaryMetric("Selected linked lines", purchaseOrderLines.length, "slate")}
      </div>
      <div className="mt-3">
        <input className="input" value={purchaseOrderSearch} onChange={(event) => setPurchaseOrderSearch(event.target.value)} placeholder="Search by supplier, PO number, PO id, date, or document URL" />
      </div>
      <div className="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
        {purchaseOrdersLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {purchaseOrdersError ? <ApiErrorNotice error={purchaseOrdersError} area="purchase order header data" /> : null}
        {purchaseOrdersData && (
          <>
            <p className="mb-2 text-xs text-slate-500">Showing {filteredPurchaseOrders.length} / {purchaseOrdersData.length} purchase orders</p>
            <div className="space-y-2">
              {filteredPurchaseOrders.map((row) => (
                <button key={row.purchase_order_id} type="button" onClick={() => openPurchaseOrderDetails(row.purchase_order_id)} className={`w-full rounded-2xl border px-4 py-3 text-left transition ${row.purchase_order_id === selectedPurchaseOrderId ? "border-emerald-400 bg-emerald-50" : "border-slate-200 bg-white hover:border-slate-300"}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold">
                        {row.purchase_order_number?.trim()
                          ? `${row.purchase_order_number} (#${row.purchase_order_id})`
                          : `PO #${row.purchase_order_id}`}
                      </p>
                      <p className="text-sm text-slate-600">{row.supplier_name}</p>
                      <p className="text-xs text-slate-500">{row.first_order_date ?? "-"} to {row.last_order_date ?? "-"}</p>
                    </div>
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">{row.line_count} lines</span>
                  </div>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
      <div className="mt-4 border-t border-slate-200 pt-4" ref={purchaseOrderDetailsRef}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="font-display text-base font-semibold">Purchase Order Details</h3>
          {selectedPurchaseOrder && <button type="button" className="button-subtle" onClick={() => setSelectedPurchaseOrderId(null)}>Clear</button>}
        </div>
        {!selectedPurchaseOrder ? (
          <p className="text-sm text-slate-500">Select a purchase order to inspect header metadata and included lines.</p>
        ) : (
          <div className="space-y-3 text-sm">
            <div className="grid gap-3 md:grid-cols-3">
              {summaryMetric("PO ID", `#${selectedPurchaseOrder.purchase_order_id}`, "emerald")}
              {summaryMetric("PO Number", selectedPurchaseOrder.purchase_order_number ?? "-", "slate")}
              {summaryMetric("Linked quotations", purchaseOrderQuotations.length, "slate")}
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="grid gap-3 md:grid-cols-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Supplier</p>
                  <p className="mt-1 font-medium text-slate-900">{selectedPurchaseOrder.supplier_name}</p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Import Lock</p>
                  <p className="mt-1 font-medium text-slate-900">
                    {selectedPurchaseOrder.import_locked ?? true ? "Locked" : "Unlocked"}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Document</p>
                  <p className="mt-1">{renderDocumentReference(selectedPurchaseOrder.purchase_order_document_url)}</p>
                </div>
              </div>
              <div className="mt-3 flex gap-2">
                {editingPurchaseOrderId === selectedPurchaseOrder.purchase_order_id ? (
                  <>
                    <button className="button-subtle" onClick={() => savePurchaseOrderEdit(selectedPurchaseOrder.purchase_order_id)} disabled={loading}>Save</button>
                    <button className="button-subtle" onClick={() => setEditingPurchaseOrderId(null)} disabled={loading}>Cancel</button>
                  </>
                ) : (
                  <button className="button-subtle" onClick={() => beginEditPurchaseOrder(selectedPurchaseOrder)} disabled={loading}>Edit</button>
                )}
                <button className="button-subtle" onClick={() => deletePurchaseOrder(selectedPurchaseOrder.purchase_order_id)} disabled={loading}>Delete</button>
              </div>
              {editingPurchaseOrderId === selectedPurchaseOrder.purchase_order_id && (
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <input
                    className="input"
                    value={editingPurchaseOrderNumber}
                    onChange={(event) => setEditingPurchaseOrderNumber(event.target.value)}
                    placeholder="PO-2026-001"
                  />
                  <input
                    className="input"
                    value={editingPurchaseOrderDocumentUrl}
                    onChange={(event) => setEditingPurchaseOrderDocumentUrl(event.target.value)}
                    placeholder="Document reference or https://..."
                  />
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input
                      checked={editingPurchaseOrderImportLocked}
                      onChange={(event) => setEditingPurchaseOrderImportLocked(event.target.checked)}
                      type="checkbox"
                    />
                    Keep import lock enabled
                  </label>
                </div>
              )}
            </div>
            {purchaseOrderLines.length ? (
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Included Lines</p>
                <div className="space-y-2">
                  {purchaseOrderLines.map((row) => (
                    <div key={`po-line-${row.order_id}`} className="rounded-xl border border-slate-200 px-3 py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-semibold">Line #{row.order_id} · {row.canonical_item_number}</p>
                          <p className="text-sm text-slate-600">
                            PO {row.purchase_order_number ?? "-"} · Quote {row.quotation_number} · Qty {row.order_amount} · ETA {row.expected_arrival ?? "-"}
                          </p>
                        </div>
                        <button className="button-subtle" type="button" onClick={() => openOrderDetails(row.order_id)}>Line Details</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-500">No purchase-order lines are linked to this header.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
