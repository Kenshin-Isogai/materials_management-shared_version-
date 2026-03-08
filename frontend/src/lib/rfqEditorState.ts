import {
  areRfqLineDraftsEqual,
  createRfqLineDraft,
  type RfqLineDraft,
} from "./editorDrafts";
import type { Order, RfqBatchDetail, RfqBatchStatus, RfqLine } from "./types";

export type RfqBatchBaseline = {
  title: string;
  status: RfqBatchStatus;
  note: string;
};

export type RfqLinkedOrderSelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

export function buildLineDraftMap(lines: RfqLine[]): Record<number, RfqLineDraft> {
  return Object.fromEntries(lines.map((line) => [line.line_id, createRfqLineDraft(line)]));
}

export function createRfqBatchBaseline(detail: Pick<RfqBatchDetail, "title" | "status" | "note">): RfqBatchBaseline {
  return {
    title: detail.title,
    status: detail.status,
    note: detail.note ?? "",
  };
}

export function orderVisibleRfqLines(lines: RfqLine[], highlightedItemId: number | null): RfqLine[] {
  if (!highlightedItemId) return lines;
  const matching = lines.filter((line) => line.item_id === highlightedItemId);
  if (!matching.length) return lines;
  return [...matching, ...lines.filter((line) => line.item_id !== highlightedItemId)];
}

export function paginateRfqLines(lines: RfqLine[], page: number, pageSize: number): RfqLine[] {
  const normalizedPage = Math.max(1, Number.isInteger(page) ? page : 1);
  const normalizedPageSize = Math.max(1, Number.isInteger(pageSize) ? pageSize : 1);
  const startIndex = (normalizedPage - 1) * normalizedPageSize;
  return lines.slice(startIndex, startIndex + normalizedPageSize);
}

function parseLinkedOrderId(value: string | null | undefined): number | null {
  const trimmed = String(value ?? "").trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function formatRfqLinkedOrderOptionLabel(
  order: Pick<Order, "order_id" | "supplier_name" | "order_amount" | "expected_arrival" | "project_name">,
): string {
  return `#${order.order_id} / ${order.supplier_name} / qty ${order.order_amount} / ETA ${
    order.expected_arrival ?? "-"
  }${order.project_name ? ` / ${order.project_name}` : ""}`;
}

function formatFallbackLinkedOrderLabel(
  line: Pick<
    RfqLine,
    "linked_order_id" | "linked_order_supplier_name" | "linked_order_expected_arrival" | "linked_quotation_number"
  >,
  selectedOrderId: number,
): string {
  if (line.linked_order_id !== selectedOrderId) {
    return `#${selectedOrderId} / Selected order`;
  }
  const parts = [`#${selectedOrderId}`];
  if (line.linked_order_supplier_name) parts.push(line.linked_order_supplier_name);
  if (line.linked_order_expected_arrival) parts.push(`ETA ${line.linked_order_expected_arrival}`);
  if (line.linked_quotation_number) parts.push(`Quote ${line.linked_quotation_number}`);
  return parts.join(" / ");
}

export function buildLinkedOrderSelectOptions({
  line,
  draftLinkedOrderId,
  matchingOrders,
  isActive,
  isLoading,
  loadError,
}: {
  line: Pick<
    RfqLine,
    "linked_order_id" | "linked_order_supplier_name" | "linked_order_expected_arrival" | "linked_quotation_number"
  >;
  draftLinkedOrderId: string;
  matchingOrders: Order[];
  isActive: boolean;
  isLoading: boolean;
  loadError: string | null;
}): RfqLinkedOrderSelectOption[] {
  const options: RfqLinkedOrderSelectOption[] = [{ value: "", label: "No linked order" }];
  const seen = new Set<string>([""]);
  const selectedOrderId = parseLinkedOrderId(draftLinkedOrderId);

  if (selectedOrderId != null) {
    const selectedKey = String(selectedOrderId);
    const selectedOrder = matchingOrders.find((order) => order.order_id === selectedOrderId);
    seen.add(selectedKey);
    options.push({
      value: selectedKey,
      label: selectedOrder
        ? formatRfqLinkedOrderOptionLabel(selectedOrder)
        : formatFallbackLinkedOrderLabel(line, selectedOrderId),
    });
  }

  if (isActive) {
    if (isLoading) {
      options.push({
        value: "__loading__",
        label: "Loading matching open orders...",
        disabled: true,
      });
    } else if (loadError) {
      options.push({
        value: "__error__",
        label: "Failed to load matching open orders",
        disabled: true,
      });
    }

    for (const order of matchingOrders) {
      const key = String(order.order_id);
      if (seen.has(key)) continue;
      seen.add(key);
      options.push({
        value: key,
        label: formatRfqLinkedOrderOptionLabel(order),
      });
    }
  }

  return options;
}

export function mergeRehydratedLineDrafts(
  currentDrafts: Record<number, RfqLineDraft>,
  currentBaseline: Record<number, RfqLineDraft>,
  serverDrafts: Record<number, RfqLineDraft>,
  pendingLineIds: number[],
): {
  drafts: Record<number, RfqLineDraft>;
  baseline: Record<number, RfqLineDraft>;
} {
  const pendingIds = new Set(pendingLineIds);
  const nextDrafts = { ...currentDrafts };
  const nextBaseline = { ...currentBaseline };

  for (const lineId of pendingIds) {
    const serverDraft = serverDrafts[lineId];
    if (!serverDraft) continue;
    if (!areRfqLineDraftsEqual(nextDrafts[lineId], serverDraft)) {
      nextDrafts[lineId] = serverDraft;
    }
    if (!areRfqLineDraftsEqual(nextBaseline[lineId], serverDraft)) {
      nextBaseline[lineId] = serverDraft;
    }
  }

  return {
    drafts: nextDrafts,
    baseline: nextBaseline,
  };
}
