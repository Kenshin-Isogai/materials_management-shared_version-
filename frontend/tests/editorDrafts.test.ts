import { describe, expect, it } from "vitest";
import {
  areRfqLineDraftsEqual,
  blankRequirementDraft,
  createRfqLineDraft,
  normalizeRequirementDrafts,
} from "../src/lib/editorDrafts";
import type { RfqLine } from "../src/lib/types";

describe("editorDrafts helpers", () => {
  it("trims trailing blank requirement rows but keeps unresolved input", () => {
    const unresolved = {
      ...blankRequirementDraft(),
      target_query: "UNREGISTERED-ITEM",
      match_status: "unregistered" as const,
      quantity: "3",
    };

    expect(
      normalizeRequirementDrafts([
        unresolved,
        blankRequirementDraft(),
        blankRequirementDraft(),
      ]),
    ).toEqual([
      {
        target_type: "ITEM",
        target_id: "",
        quantity: "3",
        requirement_type: "INITIAL",
        note: "",
        target_query: "UNREGISTERED-ITEM",
        match_status: "unregistered",
      },
    ]);
  });

  it("creates comparable RFQ line drafts from API rows", () => {
    const line: RfqLine = {
      line_id: 10,
      item_id: 4,
      item_number: "RFQ-ITEM-001",
      manufacturer_name: "RFQ-MFG",
      requested_quantity: 2,
      finalized_quantity: 3,
      supplier_name: "Supplier A",
      lead_time_days: 14,
      expected_arrival: "2026-03-30",
      linked_order_id: 8,
      status: "QUOTED",
      note: "quoted",
      linked_order_project_id: 2,
      linked_order_expected_arrival: "2026-03-30",
      linked_quotation_number: "Q-1",
      linked_order_supplier_name: "Supplier A",
    };

    const draft = createRfqLineDraft(line);
    expect(areRfqLineDraftsEqual(draft, createRfqLineDraft(line))).toBe(true);
    expect(
      areRfqLineDraftsEqual(draft, {
        ...draft,
        expected_arrival: "2026-04-02",
      }),
    ).toBe(false);
  });
});
