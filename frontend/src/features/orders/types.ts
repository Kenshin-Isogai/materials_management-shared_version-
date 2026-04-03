import type { MissingItemResolverRow, Order } from "@/lib/types";

export type ImportResult = {
  status: string;
  imported_count?: number;
  missing_count?: number;
  missing_artifact?: GeneratedArtifact;
  saved_alias_count?: number;
  rows?: MissingItemResolverRow[];
};

export type GeneratedArtifact = {
  artifact_id: string;
  artifact_type: string;
  filename: string;
  size_bytes: number;
  created_at: string;
  detail_path?: string;
  download_path?: string;
  source_job_type?: string;
  source_job_id?: string;
};

export type OrderImportPreviewStatus = "exact" | "high_confidence" | "needs_review" | "unresolved";

export type OrderImportPreviewMatch = {
  item_id: number;
  canonical_item_number: string;
  manufacturer_name: string;
  units_per_order: number;
  display_label: string;
  summary: string | null;
  match_source: string;
  match_reason: string;
  confidence_score: number;
};

export type OrderImportPreviewRow = {
  row: number;
  supplier_name: string;
  supplier_id?: number | null;
  item_number: string;
  quantity: number;
  purchase_order_number: string;
  quotation_number: string;
  issue_date: string | null;
  order_date: string;
  expected_arrival: string | null;
  quotation_document_url: string | null;
  purchase_order_document_url: string | null;
  status: OrderImportPreviewStatus;
  confidence_score: number | null;
  suggested_match: OrderImportPreviewMatch | null;
  candidates: OrderImportPreviewMatch[];
  warnings: string[];
  order_amount: number | null;
  source_name?: string;
  source_index?: number;
  preview_key?: string;
};

export type LockedPurchaseOrderPreview = {
  purchase_order_id: number;
  supplier_id: number;
  supplier_name: string;
  purchase_order_number: string;
  purchase_order_document_url: string | null;
  import_locked: boolean;
};

export type OrderImportPreview = {
  source_name: string;
  supplier: {
    supplier_id: number | null;
    supplier_name: string;
    exists: boolean;
    mode?: string;
  };
  thresholds: {
    auto_accept: number;
    review: number;
  };
  summary: {
    total_rows: number;
    exact: number;
    high_confidence: number;
    needs_review: number;
    unresolved: number;
  };
  blocking_errors: string[];
  duplicate_quotation_numbers: string[];
  locked_purchase_orders?: LockedPurchaseOrderPreview[];
  can_auto_accept: boolean;
  rows: OrderImportPreviewRow[];
};

export type OrderSplitUpdateResult = {
  order_id: number;
  split_order_id: number;
  updated_order: Order;
  created_order: Order;
};
