import { useMemo, useRef, useState } from "react";
import { apiSend } from "@/lib/api";
import type { Order, PurchaseOrder, Quotation } from "@/lib/types";
import { PurchaseOrderTable } from "@/features/orders/components/PurchaseOrderTable";

type PurchaseOrdersSectionProps = {
  ordersData: Order[] | undefined;
  purchaseOrdersData: PurchaseOrder[] | undefined;
  purchaseOrdersLoading: boolean;
  purchaseOrdersError: unknown;
  quotationsData: Quotation[] | undefined;
  refreshOrderViews: () => Promise<unknown>;
  setMessage: (value: string) => void;
  onOpenOrderDetails: (orderId: number) => void;
};

export function PurchaseOrdersSection({
  ordersData,
  purchaseOrdersData,
  purchaseOrdersLoading,
  purchaseOrdersError,
  quotationsData,
  refreshOrderViews,
  setMessage,
  onOpenOrderDetails,
}: PurchaseOrdersSectionProps) {
  const [loading, setLoading] = useState(false);
  const [purchaseOrderSearch, setPurchaseOrderSearch] = useState("");
  const [selectedPurchaseOrderId, setSelectedPurchaseOrderId] = useState<number | null>(null);
  const [editingPurchaseOrderId, setEditingPurchaseOrderId] = useState<number | null>(null);
  const [editingPurchaseOrderNumber, setEditingPurchaseOrderNumber] = useState("");
  const [editingPurchaseOrderDocumentUrl, setEditingPurchaseOrderDocumentUrl] = useState("");
  const [editingPurchaseOrderImportLocked, setEditingPurchaseOrderImportLocked] = useState(true);
  const purchaseOrderDetailsRef = useRef<HTMLDivElement | null>(null);

  const sortedOrders = useMemo(() => {
    const rows = [...(ordersData ?? [])];
    rows.sort((a, b) => b.order_id - a.order_id);
    return rows;
  }, [ordersData]);

  const sortedPurchaseOrders = useMemo(() => {
    const rows = [...(purchaseOrdersData ?? [])];
    rows.sort((a, b) => b.purchase_order_id - a.purchase_order_id);
    return rows;
  }, [purchaseOrdersData]);

  const filteredPurchaseOrders = useMemo(() => {
    const query = purchaseOrderSearch.trim().toLowerCase();
    if (!query) return sortedPurchaseOrders;
    return sortedPurchaseOrders.filter((row) =>
      [
        row.purchase_order_id,
        row.purchase_order_number ?? "",
        row.supplier_name,
        row.purchase_order_document_url ?? "",
        row.first_order_date ?? "",
        row.last_order_date ?? "",
      ]
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [purchaseOrderSearch, sortedPurchaseOrders]);

  const selectedPurchaseOrder = useMemo(
    () => (purchaseOrdersData ?? []).find((row) => row.purchase_order_id === selectedPurchaseOrderId) ?? null,
    [purchaseOrdersData, selectedPurchaseOrderId],
  );

  const purchaseOrderLines = useMemo(() => {
    if (!selectedPurchaseOrderId) return [];
    return sortedOrders.filter((row) => row.purchase_order_id === selectedPurchaseOrderId);
  }, [selectedPurchaseOrderId, sortedOrders]);

  const purchaseOrderQuotations = useMemo(() => {
    if (!purchaseOrderLines.length) return [];
    const quotationIds = new Set(purchaseOrderLines.map((row) => row.quotation_id));
    return (quotationsData ?? []).filter((row) => quotationIds.has(row.quotation_id));
  }, [purchaseOrderLines, quotationsData]);

  function scrollToSection(refObject: { current: HTMLElement | null }) {
    requestAnimationFrame(() => {
      refObject.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function openPurchaseOrderDetails(purchaseOrderId: number) {
    setMessage("");
    setSelectedPurchaseOrderId(purchaseOrderId);
    scrollToSection(purchaseOrderDetailsRef);
  }

  function beginEditPurchaseOrder(row: PurchaseOrder) {
    setEditingPurchaseOrderId(row.purchase_order_id);
    setEditingPurchaseOrderNumber(row.purchase_order_number ?? "");
    setEditingPurchaseOrderDocumentUrl(row.purchase_order_document_url ?? "");
    setEditingPurchaseOrderImportLocked(row.import_locked ?? true);
  }

  async function savePurchaseOrderEdit(purchaseOrderId: number) {
    setLoading(true);
    try {
      await apiSend(`/purchase-orders/${purchaseOrderId}`, {
        method: "PUT",
        body: JSON.stringify({
          purchase_order_number: editingPurchaseOrderNumber.trim(),
          purchase_order_document_url: editingPurchaseOrderDocumentUrl.trim() || null,
          import_locked: editingPurchaseOrderImportLocked,
        }),
      });
      setMessage(`Updated purchase order #${purchaseOrderId}.`);
      setEditingPurchaseOrderId(null);
      await refreshOrderViews();
    } catch (error) {
      setMessage(`Purchase order update failed: ${String(error ?? "")}`);
    } finally {
      setLoading(false);
    }
  }

  async function deletePurchaseOrder(purchaseOrderId: number) {
    setLoading(true);
    try {
      await apiSend(`/purchase-orders/${purchaseOrderId}`, { method: "DELETE" });
      setMessage(`Deleted purchase order #${purchaseOrderId}.`);
      if (editingPurchaseOrderId === purchaseOrderId) setEditingPurchaseOrderId(null);
      if (selectedPurchaseOrderId === purchaseOrderId) setSelectedPurchaseOrderId(null);
      await refreshOrderViews();
    } catch (error) {
      setMessage(`Purchase order delete failed: ${String(error ?? "")}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <PurchaseOrderTable
      purchaseOrdersData={purchaseOrdersData}
      filteredPurchaseOrders={filteredPurchaseOrders}
      purchaseOrderLines={purchaseOrderLines}
      purchaseOrderQuotations={purchaseOrderQuotations}
      selectedPurchaseOrder={selectedPurchaseOrder}
      purchaseOrdersLoading={purchaseOrdersLoading}
      purchaseOrdersError={purchaseOrdersError}
      loading={loading}
      selectedPurchaseOrderId={selectedPurchaseOrderId}
      editingPurchaseOrderId={editingPurchaseOrderId}
      editingPurchaseOrderNumber={editingPurchaseOrderNumber}
      editingPurchaseOrderDocumentUrl={editingPurchaseOrderDocumentUrl}
      editingPurchaseOrderImportLocked={editingPurchaseOrderImportLocked}
      purchaseOrderSearch={purchaseOrderSearch}
      purchaseOrderDetailsRef={purchaseOrderDetailsRef}
      setPurchaseOrderSearch={setPurchaseOrderSearch}
      setSelectedPurchaseOrderId={setSelectedPurchaseOrderId}
      setEditingPurchaseOrderId={setEditingPurchaseOrderId}
      setEditingPurchaseOrderNumber={setEditingPurchaseOrderNumber}
      setEditingPurchaseOrderDocumentUrl={setEditingPurchaseOrderDocumentUrl}
      setEditingPurchaseOrderImportLocked={setEditingPurchaseOrderImportLocked}
      openPurchaseOrderDetails={openPurchaseOrderDetails}
      openOrderDetails={onOpenOrderDetails}
      beginEditPurchaseOrder={beginEditPurchaseOrder}
      savePurchaseOrderEdit={(id) => void savePurchaseOrderEdit(id)}
      deletePurchaseOrder={(id) => void deletePurchaseOrder(id)}
    />
  );
}
