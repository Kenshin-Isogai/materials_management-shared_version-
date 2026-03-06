import { describe, expect, it } from "vitest";

import { createRfqLineDraft } from "../src/lib/editorDrafts";
import {
  buildLineDraftMap,
  mergeRehydratedLineDrafts,
  orderVisibleRfqLines,
} from "../src/lib/rfqEditorState";
import type { RfqLine } from "../src/lib/types";

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
    linked_order_id: 7,
    status: "QUOTED",
    note: "existing note",
    linked_order_project_id: null,
    linked_order_expected_arrival: "2026-03-12",
    linked_quotation_number: "Q-7",
    linked_order_supplier_name: "Supplier A",
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
    linked_order_id: null,
    status: "DRAFT",
    note: null,
    linked_order_project_id: null,
    linked_order_expected_arrival: null,
    linked_quotation_number: null,
    linked_order_supplier_name: null,
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
        linked_order_id: null,
        linked_order_expected_arrival: null,
        linked_quotation_number: null,
        linked_order_supplier_name: null,
      },
      baseLines[1],
    ]);

    const rehydrated = mergeRehydratedLineDrafts(
      currentDrafts,
      currentBaseline,
      refreshedServerDrafts,
      [101],
    );

    expect(rehydrated.drafts[101]?.linked_order_id).toBe("");
    expect(rehydrated.baseline[101]?.linked_order_id).toBe("");
    expect(rehydrated.drafts[102]).toEqual(createRfqLineDraft(baseLines[1]));
  });
});
