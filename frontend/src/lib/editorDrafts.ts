import type { ProjectRequirementType, RfqLine, RfqLineStatus } from "./types";

export type RequirementDraft = {
  target_type: "ITEM" | "ASSEMBLY";
  target_id: string;
  quantity: string;
  requirement_type: ProjectRequirementType;
  note: string;
  target_query: string;
  match_status?: "matched" | "unregistered";
};

export type RfqLineDraft = {
  requested_quantity: string;
  finalized_quantity: string;
  supplier_name: string;
  lead_time_days: string;
  expected_arrival: string;
  linked_order_id: string;
  status: RfqLineStatus;
  note: string;
};

export function blankRequirementDraft(): RequirementDraft {
  return {
    target_type: "ITEM",
    target_id: "",
    quantity: "1",
    requirement_type: "INITIAL",
    note: "",
    target_query: "",
    match_status: undefined,
  };
}

export function isRequirementDraftBlank(row: RequirementDraft): boolean {
  return (
    row.target_type === "ITEM" &&
    !row.target_id.trim() &&
    !row.target_query.trim() &&
    row.quantity.trim() === "1" &&
    row.requirement_type === "INITIAL" &&
    !row.note.trim() &&
    row.match_status == null
  );
}

export function normalizeRequirementDrafts(rows: RequirementDraft[]): Array<{
  target_type: "ITEM" | "ASSEMBLY";
  target_id: string;
  quantity: string;
  requirement_type: ProjectRequirementType;
  note: string;
  target_query: string;
  match_status: "matched" | "unregistered" | null;
}> {
  const normalized = rows.map((row) => ({
    target_type: row.target_type,
    target_id: row.target_id.trim(),
    quantity: row.quantity.trim(),
    requirement_type: row.requirement_type,
    note: row.note.trim(),
    target_query: row.target_id.trim() ? "" : row.target_query.trim(),
    match_status: row.match_status ?? null,
  }));
  let trimIndex = normalized.length;
  while (trimIndex > 0) {
    const row = rows[trimIndex - 1];
    if (!row || !isRequirementDraftBlank(row)) break;
    trimIndex -= 1;
  }
  return normalized.slice(0, trimIndex);
}

export function createRfqLineDraft(line: RfqLine): RfqLineDraft {
  return {
    requested_quantity: String(line.requested_quantity),
    finalized_quantity: String(line.finalized_quantity),
    supplier_name: line.supplier_name ?? "",
    lead_time_days: line.lead_time_days == null ? "" : String(line.lead_time_days),
    expected_arrival: line.expected_arrival ?? "",
    linked_order_id: line.linked_order_id == null ? "" : String(line.linked_order_id),
    status: line.status,
    note: line.note ?? "",
  };
}

export function areRfqLineDraftsEqual(
  left: RfqLineDraft | undefined,
  right: RfqLineDraft | undefined,
): boolean {
  if (!left || !right) return left === right;
  return (
    left.requested_quantity === right.requested_quantity &&
    left.finalized_quantity === right.finalized_quantity &&
    left.supplier_name === right.supplier_name &&
    left.lead_time_days === right.lead_time_days &&
    left.expected_arrival === right.expected_arrival &&
    left.linked_order_id === right.linked_order_id &&
    left.status === right.status &&
    left.note === right.note
  );
}
