import React from "react";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Item, Order, ProjectRow } from "@/lib/types";
import { summaryMetric, renderDocumentReference } from "@/features/orders/utils";

export type OrderLineTableProps = {
  ordersData: Order[] | undefined;
  filteredSortedOrders: Order[];
  sameItemOrders: Order[];
  selectedOrder: Order | null;
  selectedOrderItem: Item | null;
  isLoading: boolean;
  error: unknown;
  loading: boolean;
  selectedOrderId: number | null;
  editingOrderId: number | null;
  editingOrderExpectedArrival: string;
  editingOrderSplitQuantity: string;
  editingOrderProjectId: string;
  projectsData: ProjectRow[] | undefined;
  orderPrimarySearch: string;
  orderFilter: string;
  orderDetailsRef: React.Ref<HTMLDivElement>;
  setOrderPrimarySearch: (value: string) => void;
  setOrderFilter: (value: string) => void;
  setSelectedOrderId: (id: number | null) => void;
  setEditingOrderExpectedArrival: (value: string) => void;
  setEditingOrderSplitQuantity: (value: string) => void;
  setEditingOrderProjectId: (value: string) => void;
  openOrderDetails: (orderId: number) => void;
  openReservationPrefill: (order: Order) => void;
  markArrived: (orderId: number) => void;
  deleteOrder: (orderId: number) => void;
  beginEditOrder: (row: Order) => void;
  cancelEditOrder: () => void;
  saveOrderEdit: (orderId: number) => void;
};

export function OrderLineTable({
  ordersData,
  filteredSortedOrders,
  sameItemOrders,
  selectedOrder,
  selectedOrderItem,
  isLoading,
  error,
  loading,
  selectedOrderId,
  editingOrderId,
  editingOrderExpectedArrival,
  editingOrderSplitQuantity,
  editingOrderProjectId,
  projectsData,
  orderPrimarySearch,
  orderFilter,
  orderDetailsRef,
  setOrderPrimarySearch,
  setOrderFilter,
  setSelectedOrderId,
  setEditingOrderExpectedArrival,
  setEditingOrderSplitQuantity,
  setEditingOrderProjectId,
  openOrderDetails,
  openReservationPrefill,
  markArrived,
  deleteOrder,
  beginEditOrder,
  cancelEditOrder,
  saveOrderEdit,
}: OrderLineTableProps) {
  const [pendingDeleteOrder, setPendingDeleteOrder] = React.useState<Order | null>(null);

  return (
    <section className="panel p-4">
      <div className="mb-3">
        <h2 className="font-display text-lg font-semibold">Purchase Order Lines</h2>
        <p className="mt-1 text-sm text-slate-500">Line-level ETA, split, linked document traceability, and project assignment.</p>
      </div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {summaryMetric("Total lines", ordersData?.length ?? 0, "amber")}
        {summaryMetric("Filtered", filteredSortedOrders.length, "slate")}
        {summaryMetric("Selected item family", sameItemOrders.length, "slate")}
        {summaryMetric("Selected status", selectedOrder?.status ?? "-", "sky")}
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        <input
          className="input"
          value={orderPrimarySearch}
          onChange={(event) => setOrderPrimarySearch(event.target.value)}
          placeholder="Search by order #, item, quotation, or PO number"
        />
        <input
          className="input"
          value={orderFilter}
          onChange={(event) => setOrderFilter(event.target.value)}
          placeholder="Filter by supplier, project, expected date, or status"
        />
      </div>
      {isLoading && <p className="mt-3 text-sm text-slate-500">Loading...</p>}
      {error ? <ApiErrorNotice error={error} area="purchase order line data" className="mt-3" /> : null}
      {ordersData && (
        <div className="mt-3 grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
          <div className="max-h-[42rem] overflow-y-auto pr-1">
            <p className="mb-2 text-xs text-slate-500">Showing {filteredSortedOrders.length} / {ordersData.length} orders</p>
            <div className="space-y-2">
              {filteredSortedOrders.map((row) => (
                <div key={row.order_id} className={`rounded-2xl border px-3.5 py-2.5 ${row.order_id === selectedOrderId ? "border-amber-400 bg-amber-50" : "border-slate-200 bg-white"}`}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-semibold">Line #{row.order_id} · {row.canonical_item_number}</p>
                      <p className="text-sm text-slate-600">
                        {row.supplier_name} · PO {row.purchase_order_number ?? `#${row.purchase_order_id}`} · Quote {row.quotation_number}
                      </p>
                      <p className="text-xs text-slate-500">
                        Qty {row.order_amount} · ETA {row.expected_arrival ?? "-"} · {row.status}
                        {row.project_name ? ` · ${row.project_name}` : ""}
                      </p>
                      {(row.incoming_reserved_quantity ?? 0) > 0 ? (
                        <p className="text-xs text-emerald-700">
                          Reserved by {row.incoming_reservation_count ?? 0} reservation(s) · qty {row.incoming_reserved_quantity}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <button className="button-subtle" onClick={() => openOrderDetails(row.order_id)} disabled={loading}>Line Details</button>
                      {row.status === "Ordered" ? (
                        <>
                          <button className="button-subtle" onClick={() => markArrived(row.order_id)} disabled={loading}>Mark Arrived</button>
                          {editingOrderId === row.order_id ? (
                            <>
                              <button className="button-subtle" onClick={() => saveOrderEdit(row.order_id)} disabled={loading}>Save Order</button>
                              <button className="button-subtle" onClick={cancelEditOrder} disabled={loading}>Cancel</button>
                            </>
                          ) : (
                            <button className="button-subtle" onClick={() => beginEditOrder(row)} disabled={loading}>Edit Order</button>
                          )}
                        </>
                      ) : null}
                      <button
                        className="button-subtle"
                        onClick={() => setPendingDeleteOrder(row)}
                        disabled={loading || row.status === "Arrived"}
                        title={row.status === "Arrived" ? "Arrived orders cannot be deleted" : "Delete this order"}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                  {editingOrderId === row.order_id ? (
                    <div className="mt-2.5 grid gap-2 md:grid-cols-3">
                      <label className="grid gap-1">
                        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Expected Arrival</span>
                        <input
                          aria-label={`Expected Arrival for line #${row.order_id}`}
                          className="input"
                          type="date"
                          value={editingOrderExpectedArrival}
                          onChange={(event) => setEditingOrderExpectedArrival(event.target.value)}
                        />
                      </label>
                      <label className="grid gap-1">
                        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Split Quantity</span>
                        <input className="input" type="number" min={1} max={row.order_amount - 1} placeholder={`Split qty (1-${row.order_amount - 1})`} value={editingOrderSplitQuantity} onChange={(event) => setEditingOrderSplitQuantity(event.target.value)} />
                      </label>
                      <label className="grid gap-1">
                        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Project Assignment</span>
                        <select className="input" value={editingOrderProjectId} onChange={(event) => setEditingOrderProjectId(event.target.value)}>
                          <option value="">No project assignment</option>
                          {(projectsData ?? []).map((project) => (
                            <option key={project.project_id} value={project.project_id}>
                              #{project.project_id} {project.name} ({project.status})
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>

          <div className="border-t border-slate-200 pt-4 xl:border-l xl:border-t-0 xl:pl-4 xl:pt-0" ref={orderDetailsRef}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="font-display text-base font-semibold">Purchase Order Line Details</h3>
              {selectedOrder && (
                <button type="button" className="button-subtle" onClick={() => setSelectedOrderId(null)}>
                  Clear
                </button>
              )}
            </div>
            {!selectedOrder ? (
              <p className="text-sm text-slate-500">Select a line to inspect item metadata and linked quotation / purchase-order headers.</p>
            ) : (
              <div className="space-y-3 text-sm">
                <div className="grid gap-3 md:grid-cols-2">
                  {summaryMetric("Line ID", `#${selectedOrder.order_id}`, "amber")}
                  {summaryMetric("Qty", selectedOrder.order_amount, "slate")}
                  {summaryMetric("Status", selectedOrder.status, "sky")}
                  {summaryMetric("Same-item rows", sameItemOrders.length, "slate")}
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Item</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrder.canonical_item_number}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Supplier</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrder.supplier_name}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Quotation</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrder.quotation_number}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Purchase Order</p>
                      <p className="mt-1 font-medium text-slate-900">
                        {selectedOrder.purchase_order_number ?? "-"} (#{selectedOrder.purchase_order_id})
                      </p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Expected Arrival</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrder.expected_arrival ?? "-"}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Project</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrder.project_name ?? "-"}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Incoming-backed Reservations</p>
                      <p className="mt-1 font-medium text-slate-900">
                        {(selectedOrder.incoming_reservation_count ?? 0) > 0
                          ? `${selectedOrder.incoming_reservation_count} reservation(s) / qty ${selectedOrder.incoming_reserved_quantity ?? 0}`
                          : "-"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Quotation Document</p>
                      <p className="mt-1">{renderDocumentReference(selectedOrder.quotation_document_url)}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Purchase-order Document</p>
                      <p className="mt-1">{renderDocumentReference(selectedOrder.purchase_order_document_url)}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Category</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrderItem?.category ?? "-"}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Description</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedOrderItem?.description ?? "-"}</p>
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" className="button-subtle" onClick={() => openReservationPrefill(selectedOrder)}>
                    Create Provisional Reservation…
                  </button>
                  <p className="text-xs text-slate-500">
                    Opens Reservations with this line preselected as the preferred incoming backing. Stock and incoming backing can be mixed there.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      <Dialog open={pendingDeleteOrder != null} onOpenChange={(open) => !open && setPendingDeleteOrder(null)}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete purchase order line?</DialogTitle>
            <DialogDescription>
              {pendingDeleteOrder
                ? `Line #${pendingDeleteOrder.order_id} (${pendingDeleteOrder.canonical_item_number}) will be deleted from the registered purchase order lines.`
                : "This line will be deleted from the registered purchase order lines."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button type="button" className="button-subtle" onClick={() => setPendingDeleteOrder(null)} disabled={loading}>
              Cancel
            </button>
            <button
              type="button"
              className="button-subtle text-red-700 hover:text-red-800"
              onClick={() => {
                if (!pendingDeleteOrder) return;
                deleteOrder(pendingDeleteOrder.order_id);
                setPendingDeleteOrder(null);
              }}
              disabled={loading || pendingDeleteOrder == null}
            >
              Delete
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
