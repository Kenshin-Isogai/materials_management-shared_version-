import type { CatalogSearchResult } from "@/lib/types";

export type ItemRowType = "item" | "alias";

export type ItemEntryRow = {
  row_type: ItemRowType;
  item_number: string;
  manufacturer_name: string;
  supplier: string;
  canonical_item_number: string;
  units_per_order: string;
  category: string;
  url: string;
  description: string;
};

export type ItemImportRow = {
  row: number;
  status: "created" | "duplicate" | "error";
  entry_type?: ItemRowType;
  item_id?: number;
  item_number?: string;
  supplier?: string;
  canonical_item_number?: string;
  units_per_order?: number;
  error?: string;
  source_name?: string;
};

export type ItemImportResult = {
  status: string;
  processed: number;
  created_count: number;
  duplicate_count: number;
  failed_count: number;
  import_job_id?: number;
  import_job_ids?: number[];
  rows: ItemImportRow[];
};

export type ItemImportPreviewMatch = CatalogSearchResult & {
  confidence_score?: number | null;
  match_reason?: string | null;
};

export type ItemImportPreviewRow = {
  row: number;
  entry_type: "item" | "alias" | string;
  item_number: string;
  manufacturer_name: string;
  supplier: string;
  canonical_item_number: string;
  units_per_order: string;
  category: string;
  url: string;
  description: string;
  status: "exact" | "high_confidence" | "needs_review" | "unresolved";
  action: string;
  message: string;
  blocking: boolean;
  requires_user_selection: boolean;
  allowed_entity_types: Array<"item">;
  suggested_match: ItemImportPreviewMatch | null;
  candidates: ItemImportPreviewMatch[];
  source_name?: string;
  source_index?: number;
  preview_key?: string;
};

export type ItemImportPreview = {
  source_name: string;
  summary: {
    total_rows: number;
    exact: number;
    high_confidence: number;
    needs_review: number;
    unresolved: number;
  };
  blocking_errors: string[];
  can_auto_accept: boolean;
  rows: ItemImportPreviewRow[];
};

export type ItemImportJobSummary = {
  import_job_id: number;
  import_type: string;
  source_name: string;
  continue_on_error: boolean;
  status: string;
  processed: number;
  created_count: number;
  duplicate_count: number;
  failed_count: number;
  lifecycle_state: "active" | "undone";
  created_at: string;
  undone_at?: string | null;
  redo_of_job_id?: number | null;
  last_redo_job_id?: number | null;
};

export type ItemImportJobEffect = {
  effect_id: number;
  row_number: number;
  status: "created" | "duplicate" | "error";
  entry_type?: ItemRowType;
  effect_type: string;
  item_number?: string;
  supplier_name?: string;
  canonical_item_number?: string;
  units_per_order?: number;
  message?: string;
  code?: string;
};

export type ItemImportJobDetail = {
  job: ItemImportJobSummary;
  effects: ItemImportJobEffect[];
};

export type ItemEditDraft = {
  item_number: string;
  manufacturer_name: string;
  category: string;
  url: string;
  description: string;
};

export type MetadataBulkRow = {
  item_id: string;
  category: string;
  url: string;
  description: string;
};

export type MetadataBulkResultRow = {
  row: number;
  status: "updated" | "error";
  item_id: number;
  item_number?: string;
  error?: string;
  code?: string;
};

export type MetadataBulkResult = {
  status: string;
  processed: number;
  updated_count: number;
  failed_count: number;
  rows: MetadataBulkResultRow[];
};

export type ItemFlowEvent = {
  event_at: string;
  delta: number;
  quantity: number;
  direction: "increase" | "decrease";
  source_type: string;
  source_ref: string;
  reason: string;
  note: string | null;
};

export type ItemFlowTimeline = {
  item_id: number;
  item_number: string;
  manufacturer_name: string;
  current_stock: number;
  events: ItemFlowEvent[];
};
