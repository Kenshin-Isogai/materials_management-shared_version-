import { describe, expect, it } from "vitest";

import { createRfqLineDraft } from "../src/lib/editorDrafts";
import {
  buildLinkedOrderSelectOptions,
  buildLineDraftMap,
  mergeRehydratedLineDrafts,
  orderVisibleRfqLines,
  paginateRfqLines,
} from "../src/lib/rfqEditorState";
import type { PurchaseOrderLine, RfqLine } from "../src/lib/types";

const baseLines: RfqLine[] = [
  {
    line_id: 101,
    item_id: 200,
    item_number: "ITEM-200",
    manufacturer_name: "Acme",
    requested_quantity: 5,
    finalized_quantity: 5,
    supplier_name: "Supplier A",
    lead_time_days: 7,
    expected_arrival: "2026-03-10",
    linked_purchase_order_line_id: 7,
    status: "QUOTED",
    note: "existing note",
    linked_purchase_order_line_project_id: null,
    linked_purchase_order_line_expected_arrival: "2026-03-12",
    linked_quotation_number: "Q-7",
    linked_purchase_order_line_supplier_name: "Supplier A",
  },
  {
    line_id: 102,
    item_id: 201,
    item_number: "ITEM-201",
    manufacturer_name: "Acme",
    requested_quantity: 3,
    finalized_quantity: 3,
    supplier_name: null,
    lead_time_days: null,
    expected_arrival: null,
    linked_purchase_order_line_id: null,
    status: "DRAFT",
    note: null,
    linked_purchase_order_line_project_id: null,
    linked_purchase_order_line_expected_arrival: null,
    linked_quotation_number: null,
    linked_purchase_order_line_supplier_name: null,
  },
];

const matchingOrders: PurchaseOrderLine[] = [
  {
    order_id: 7,
    item_id: 200,
    quotation_id: 17,
    project_id: 10,
    project_name: "Project A",
    canonical_item_number: "ITEM-200",
    order_amount: 5,
    ordered_quantity: 5,
    ordered_item_number: "ITEM-200",
    order_date: "2026-03-01",
    expected_arrival: "2026-03-12",
    arrival_date: null,
    status: "Ordered",
    supplier_name: "Supplier A",
    quotation_number: "Q-7",
  },
  {
    order_id: 9,
    item_id: 200,
    quotation_id: 19,
    project_id: null,
    project_name: null,
    canonical_item_number: "ITEM-200",
    order_amount: 2,
    ordered_quantity: 2,
    ordered_item_number: "ITEM-200",
    order_date: "2026-03-02",
    expected_arrival: "2026-03-15",
    arrival_date: null,
    status: "Ordered",
    supplier_name: "Supplier B",
    quotation_number: "Q-9",
  },
];

describe("rfqEditorState", () => {
  it("keeps the full batch visible while surfacing the highlighted item first", () => {
    const ordered = orderVisibleRfqLines(baseLines, 200);

    expect(ordered.map((line) => line.line_id)).toEqual([101, 102]);
  });

  it("rehydrates saved lines from refreshed server detail without changing the batch id", () => {
    const currentDrafts = buildLineDraftMap(baseLines);
    const currentBaseline = buildLineDraftMap(baseLines);
    const refreshedServerDrafts = buildLineDraftMap([
      {
        ...baseLines[0],
        linked_purchase_order_line_id: null,
        linked_purchase_order_line_expected_arrival: null,
        linked_quotation_number: null,
        linked_purchase_order_line_supplier_name: null,
      },
      baseLines[1],
    ]);

    const rehydrated = mergeRehydratedLineDrafts(
      currentDrafts,
      currentBaseline,
      refreshedServerDrafts,
      [101],
    );

    expect(rehydrated.drafts[101]?.linked_purchase_order_line_id).toBe("");
    expect(rehydrated.baseline[101]?.linked_purchase_order_line_id).toBe("");
    expect(rehydrated.drafts[102]).toEqual(createRfqLineDraft(baseLines[1]));
  });

  it("keeps the current linked order visible even before matching options are loaded", () => {
    const options = buildLinkedOrderSelectOptions({
      line: baseLines[0],
      draftLinkedOrderId: "7",
      matchingOrders: [],
      isActive: false,
      isLoading: false,
      loadError: null,
    });

    expect(options).toEqual([
      { value: "", label: "No linked order" },
      { value: "7", label: "#7 / Supplier A / ETA 2026-03-12 / Quote Q-7" },
    ]);
  });

  it("shows the selected order once and appends other loaded choices only for the active row", () => {
    const options = buildLinkedOrderSelectOptions({
      line: baseLines[0],
      draftLinkedOrderId: "7",
      matchingOrders,
      isActive: true,
      isLoading: false,
      loadError: null,
    });

    expect(options.map((option) => option.value)).toEqual(["", "7", "9"]);
    expect(options[1]?.label).toContain("Supplier A");
    expect(options[2]?.label).toContain("Supplier B");
  });

  it("surfaces a loading placeholder while the active row fetches matching open orders", () => {
    const options = buildLinkedOrderSelectOptions({
      line: baseLines[1],
      draftLinkedOrderId: "",
      matchingOrders: [],
      isActive: true,
      isLoading: true,
      loadError: null,
    });

    expect(options).toEqual([
      { value: "", label: "No linked order" },
      { value: "__loading__", label: "Loading matching open orders...", disabled: true },
    ]);
  });

  it("returns only the requested RFQ page slice", () => {
    const lines: RfqLine[] = Array.from({ length: 6 }, (_, index) => ({
      ...baseLines[index % baseLines.length],
      line_id: 200 + index,
    }));

    const pageTwo = paginateRfqLines(lines, 2, 2);

    expect(pageTwo.map((line) => line.line_id)).toEqual([202, 203]);
  });

  it("normalizes invalid paging inputs to a safe first page", () => {
    const page = paginateRfqLines(baseLines, 0, 0);

    expect(page.map((line) => line.line_id)).toEqual([101]);
  });
});
