import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiSend } from "@/lib/api";
import type { Item, Order, ProjectRow } from "@/lib/types";
import type { OrderSplitUpdateResult } from "@/features/orders/types";
import { OrderLineTable } from "@/features/orders/components/OrderLineTable";

type OrderLinesSectionProps = {
  ordersData: Order[] | undefined;
  error: unknown;
  isLoading: boolean;
  itemsData: { data: Item[] } | undefined;
  projectsData: ProjectRow[] | undefined;
  refreshOrderViews: () => Promise<unknown>;
  setMessage: (value: string) => void;
};

export type OrderLinesSectionHandle = {
  openOrderDetails: (orderId: number) => void;
};

export const OrderLinesSection = forwardRef<OrderLinesSectionHandle, OrderLinesSectionProps>(
  function OrderLinesSection(
    { ordersData, error, isLoading, itemsData, projectsData, refreshOrderViews, setMessage },
    ref,
  ) {
    const navigate = useNavigate();
    const [loading, setLoading] = useState(false);
    const [orderPrimarySearch, setOrderPrimarySearch] = useState("");
    const [orderFilter, setOrderFilter] = useState("");
    const [editingOrderId, setEditingOrderId] = useState<number | null>(null);
    const [editingOrderExpectedArrival, setEditingOrderExpectedArrival] = useState("");
    const [editingOrderSplitQuantity, setEditingOrderSplitQuantity] = useState("");
    const [editingOrderProjectId, setEditingOrderProjectId] = useState("");
    const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
    const orderDetailsRef = useRef<HTMLDivElement | null>(null);

    const sortedOrders = useMemo(() => {
      const rows = [...(ordersData ?? [])];
      rows.sort((a, b) => b.order_id - a.order_id);
      return rows;
    }, [ordersData]);

    const filteredSortedOrders = useMemo(() => {
      const primaryQuery = orderPrimarySearch.trim().toLowerCase();
      const filterQuery = orderFilter.trim().toLowerCase();
      return sortedOrders.filter((row) => {
        const orderId = String(row.order_id);
        const itemNumber = row.canonical_item_number.toLowerCase();
        const quotationNumber = row.quotation_number.toLowerCase();
        const matchesPrimary =
          !primaryQuery ||
          orderId.includes(primaryQuery) ||
          itemNumber.includes(primaryQuery) ||
          quotationNumber.includes(primaryQuery);
        if (!matchesPrimary) return false;

        if (!filterQuery) return true;
        const projectName = row.project_name ?? "";
        const expectedArrival = row.expected_arrival ?? "";
        return [row.supplier_name, projectName, expectedArrival, row.status]
          .join(" ")
          .toLowerCase()
          .includes(filterQuery);
      });
    }, [orderFilter, orderPrimarySearch, sortedOrders]);

    const itemByNumber = useMemo(() => {
      return new Map((itemsData?.data ?? []).map((item) => [item.item_number, item]));
    }, [itemsData?.data]);

    const selectedOrder = useMemo(
      () => sortedOrders.find((row) => row.order_id === selectedOrderId) ?? null,
      [selectedOrderId, sortedOrders],
    );

    const selectedOrderItem = selectedOrder
      ? itemByNumber.get(selectedOrder.canonical_item_number) ?? null
      : null;

    const sameItemOrders = useMemo(() => {
      if (!selectedOrder) return [];
      return sortedOrders.filter((row) => row.canonical_item_number === selectedOrder.canonical_item_number);
    }, [selectedOrder, sortedOrders]);

    function scrollToSection(refObject: { current: HTMLElement | null }) {
      requestAnimationFrame(() => {
        refObject.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }

    function openOrderDetails(orderId: number) {
      setSelectedOrderId(orderId);
      scrollToSection(orderDetailsRef);
    }

    useImperativeHandle(ref, () => ({ openOrderDetails }));

    function openReservationPrefill(order: Order) {
      const params = new URLSearchParams({
        item_id: String(order.item_id),
        quantity: String(order.order_amount),
        source_purchase_order_line_id: String(order.order_id),
        purpose: `Provisional reserve from purchase order line #${order.order_id}`,
      });
      if (order.project_id) {
        params.set("project_id", String(order.project_id));
      }
      navigate(`/reservations?${params.toString()}`);
    }

    async function markArrived(orderId: number) {
      setLoading(true);
      try {
        await apiSend(`/purchase-order-lines/${orderId}/arrival`, { method: "POST", body: JSON.stringify({}) });
        await refreshOrderViews();
      } finally {
        setLoading(false);
      }
    }

    async function deleteOrder(orderId: number) {
      setLoading(true);
      try {
        await apiSend(`/purchase-order-lines/${orderId}`, { method: "DELETE" });
        setMessage(`Deleted order #${orderId}.`);
        await refreshOrderViews();
      } catch (error) {
        setMessage(`Delete failed: ${String(error ?? "")}`);
      } finally {
        setLoading(false);
      }
    }

    function beginEditOrder(row: Order) {
      setEditingOrderId(row.order_id);
      setEditingOrderExpectedArrival(row.expected_arrival ?? "");
      setEditingOrderSplitQuantity("");
      setEditingOrderProjectId(row.project_id == null ? "" : String(row.project_id));
    }

    function cancelEditOrder() {
      setEditingOrderId(null);
      setEditingOrderExpectedArrival("");
      setEditingOrderSplitQuantity("");
      setEditingOrderProjectId("");
    }

    function formatOrderUpdateError(error: unknown): string {
      const text = String(error ?? "");
      if (text.includes("managed by the ORDERED procurement line")) {
        return "Project assignment failed: this order is controlled by an ORDERED procurement line.";
      }
      if (text.includes("managed by the ORDERED RFQ line")) {
        return "Project assignment failed: this order is controlled by an ORDERED RFQ line.";
      }
      return `Order update failed: ${text}`;
    }

    async function saveOrderEdit(orderId: number) {
      setLoading(true);
      try {
        const currentOrder = (ordersData ?? []).find((row) => row.order_id === orderId) ?? null;
        const splitQuantity = Number(editingOrderSplitQuantity);
        const hasSplit = editingOrderSplitQuantity.trim().length > 0;
        const projectId =
          editingOrderProjectId.trim().length > 0 ? Number(editingOrderProjectId.trim()) : null;
        const expectedArrival = editingOrderExpectedArrival.trim() || null;
        const shouldClearProjectOnSplit =
          hasSplit && currentOrder?.project_id != null && projectId == null;
        if (hasSplit) {
          const splitResult = await apiSend<OrderSplitUpdateResult>(`/purchase-order-lines/${orderId}`, {
            method: "PUT",
            body: JSON.stringify({
              expected_arrival: expectedArrival,
              split_quantity: Number.isFinite(splitQuantity) ? splitQuantity : null,
              ...(shouldClearProjectOnSplit ? { project_id: null } : {}),
            }),
          });
          if (Number.isFinite(projectId)) {
            await apiSend(`/purchase-order-lines/${splitResult.created_order.order_id}`, {
              method: "PUT",
              body: JSON.stringify({
                project_id: projectId,
              }),
            });
          }
        } else {
          await apiSend(`/purchase-order-lines/${orderId}`, {
            method: "PUT",
            body: JSON.stringify({
              expected_arrival: expectedArrival,
              project_id: Number.isFinite(projectId) ? projectId : null,
            }),
          });
        }
        setMessage(
          hasSplit
            ? `Split order #${orderId}, assigned the consumed portion if selected, and postponed ${splitQuantity} units to ${editingOrderExpectedArrival || "(no date)"}.`
            : `Updated order #${orderId}.`,
        );
        cancelEditOrder();
        await refreshOrderViews();
      } catch (error) {
        setMessage(formatOrderUpdateError(error));
      } finally {
        setLoading(false);
      }
    }

    return (
      <OrderLineTable
        ordersData={ordersData}
        filteredSortedOrders={filteredSortedOrders}
        sameItemOrders={sameItemOrders}
        selectedOrder={selectedOrder}
        selectedOrderItem={selectedOrderItem}
        isLoading={isLoading}
        error={error}
        loading={loading}
        selectedOrderId={selectedOrderId}
        editingOrderId={editingOrderId}
        editingOrderExpectedArrival={editingOrderExpectedArrival}
        editingOrderSplitQuantity={editingOrderSplitQuantity}
        editingOrderProjectId={editingOrderProjectId}
        projectsData={projectsData}
        orderPrimarySearch={orderPrimarySearch}
        orderFilter={orderFilter}
        orderDetailsRef={orderDetailsRef}
        setOrderPrimarySearch={setOrderPrimarySearch}
        setOrderFilter={setOrderFilter}
        setSelectedOrderId={setSelectedOrderId}
        setEditingOrderExpectedArrival={setEditingOrderExpectedArrival}
        setEditingOrderSplitQuantity={setEditingOrderSplitQuantity}
        setEditingOrderProjectId={setEditingOrderProjectId}
        openOrderDetails={openOrderDetails}
        openReservationPrefill={openReservationPrefill}
        markArrived={(orderId) => void markArrived(orderId)}
        deleteOrder={(orderId) => void deleteOrder(orderId)}
        beginEditOrder={beginEditOrder}
        cancelEditOrder={cancelEditOrder}
        saveOrderEdit={(orderId) => void saveOrderEdit(orderId)}
      />
    );
  },
);
