export type ApiOk<T> = {
  status: "ok";
  data: T;
  pagination?: {
    page: number;
    per_page: number;
    total: number;
    total_pages: number;
  };
};

export type ApiErr = {
  status: "error";
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
};

export type ApiResponse<T> = ApiOk<T> | ApiErr;

export type Item = {
  item_id: number;
  item_number: string;
  category: string | null;
  raw_category?: string | null;
  manufacturer_id: number;
  manufacturer_name: string;
  url?: string | null;
  description?: string | null;
};

export type InventoryRow = {
  ledger_id: number;
  item_id: number;
  item_number: string;
  location: string;
  quantity: number;
  category: string | null;
  manufacturer_name: string;
  last_updated: string | null;
};

export type Reservation = {
  reservation_id: number;
  item_id: number;
  item_number: string;
  quantity: number;
  purpose: string | null;
  deadline: string | null;
  status: "ACTIVE" | "RELEASED" | "CONSUMED";
  note: string | null;
  created_at: string;
};

export type Order = {
  order_id: number;
  item_id: number;
  quotation_id: number;
  project_id: number | null;
  project_name?: string | null;
  canonical_item_number: string;
  order_amount: number;
  ordered_quantity: number;
  ordered_item_number: string;
  order_date: string;
  expected_arrival: string | null;
  arrival_date: string | null;
  status: "Ordered" | "Arrived";
  supplier_name: string;
  quotation_number: string;
};

export type Quotation = {
  quotation_id: number;
  supplier_id: number;
  supplier_name: string;
  quotation_number: string;
  issue_date: string | null;
  pdf_link: string | null;
};

export type Transaction = {
  log_id: number;
  timestamp: string;
  operation_type: string;
  item_id: number;
  item_number: string;
  quantity: number;
  from_location: string | null;
  to_location: string | null;
  note: string | null;
  is_undone: number;
  batch_id: string | null;
};

export type MissingItemResolverRow = {
  row?: number;
  item_number: string;
  supplier: string;
  resolution_type?: "new_item" | "alias";
  category?: string;
  url?: string;
  description?: string;
  canonical_item_number?: string;
  units_per_order?: string;
};

export type CatalogEntityType = "item" | "assembly" | "supplier" | "project";

export type CatalogSearchResult = {
  entity_type: CatalogEntityType;
  entity_id: number;
  value_text: string;
  display_label: string;
  summary: string | null;
  match_source: string | null;
};

export type CatalogSearchResponse = {
  query: string;
  results: CatalogSearchResult[];
};

export type ProjectStatus =
  | "PLANNING"
  | "CONFIRMED"
  | "ACTIVE"
  | "COMPLETED"
  | "CANCELLED";

export type ProjectRequirementType = "INITIAL" | "SPARE" | "REPLACEMENT";

export type ProjectRow = {
  project_id: number;
  name: string;
  status: ProjectStatus;
  planned_start: string | null;
  requirement_count: number;
};

export type ProjectRequirement = {
  requirement_id: number;
  assembly_id: number | null;
  assembly_name?: string | null;
  item_id: number | null;
  item_number?: string | null;
  quantity: number;
  requirement_type: ProjectRequirementType;
  note: string | null;
};

export type ProjectDetail = ProjectRow & {
  description: string | null;
  requirements: ProjectRequirement[];
};

export type AssemblyOption = {
  assembly_id: number;
  name: string;
};

export type ProjectRequirementPreviewMatch = CatalogSearchResult & {
  confidence_score?: number | null;
  match_reason?: string | null;
};

export type ProjectRequirementPreviewRow = {
  row: number;
  raw_line: string;
  raw_target: string;
  quantity: string;
  quantity_raw: string;
  quantity_defaulted: boolean;
  status: "exact" | "high_confidence" | "needs_review" | "unresolved";
  message: string;
  requires_user_selection: boolean;
  allowed_entity_types: Array<"item">;
  suggested_match: ProjectRequirementPreviewMatch | null;
  candidates: ProjectRequirementPreviewMatch[];
};

export type ProjectRequirementPreview = {
  summary: {
    total_rows: number;
    exact: number;
    high_confidence: number;
    needs_review: number;
    unresolved: number;
  };
  can_auto_accept: boolean;
  rows: ProjectRequirementPreviewRow[];
};

export type PlanningSource = {
  source_type: "stock" | "generic_order" | "dedicated_order" | "quoted_rfq";
  quantity: number;
  label: string;
  ref_id: number | null;
  project_id: number | null;
  date: string | null;
  status: string | null;
};

export type PipelineSummary = {
  project_id: number;
  name: string;
  status: ProjectStatus;
  planned_start: string;
  is_planning_preview: boolean;
  item_count: number;
  required_total: number;
  covered_on_time_total: number;
  shortage_at_start_total: number;
  remaining_shortage_total: number;
  generic_committed_total: number;
  cumulative_generic_consumed_before_total: number;
};

export type PlanningAnalysisRow = {
  item_id: number;
  item_number: string | null;
  manufacturer_name: string | null;
  required_quantity: number;
  dedicated_supply_by_start: number;
  generic_available_at_start: number;
  generic_allocated_quantity: number;
  covered_on_time_quantity: number;
  shortage_at_start: number;
  future_generic_recovery_quantity: number;
  future_dedicated_recovery_quantity: number;
  recovered_after_start_quantity: number;
  remaining_shortage_quantity: number;
  supply_sources_by_start: PlanningSource[];
  recovery_sources_after_start: PlanningSource[];
};

export type PlanningAnalysisResult = {
  project: {
    project_id: number;
    name: string;
    status: ProjectStatus;
    planned_start: string | null;
  };
  target_date: string;
  summary: PipelineSummary;
  rows: PlanningAnalysisRow[];
  pipeline: PipelineSummary[];
};

export type WorkspaceProjectSummary = {
  project_id: number;
  name: string;
  description: string | null;
  status: ProjectStatus;
  planned_start: string | null;
  requirement_count: number;
  summary_mode: "authoritative" | "preview_required" | "not_plannable";
  summary_message: string;
  planning_summary: PipelineSummary | null;
  rfq_summary: {
    total_batches: number;
    open_batch_count: number;
    closed_batch_count: number;
    cancelled_batch_count: number;
    draft_line_count: number;
    sent_line_count: number;
    quoted_line_count: number;
    ordered_line_count: number;
    latest_target_date: string | null;
  };
};

export type WorkspaceSummary = {
  generated_at: string;
  projects: WorkspaceProjectSummary[];
  pipeline: PipelineSummary[];
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

export type RfqBatchStatus = "OPEN" | "CLOSED" | "CANCELLED";

export type RfqBatchSummary = {
  rfq_id: number;
  project_id: number;
  project_name: string;
  title: string;
  target_date: string | null;
  status: RfqBatchStatus;
  note: string | null;
  line_count: number;
  finalized_quantity_total: number;
  quoted_line_count: number;
  ordered_line_count: number;
};

export type RfqLineStatus = "DRAFT" | "SENT" | "QUOTED" | "ORDERED" | "CANCELLED";

export type RfqLine = {
  line_id: number;
  item_id: number;
  item_number: string;
  manufacturer_name: string;
  requested_quantity: number;
  finalized_quantity: number;
  supplier_name: string | null;
  lead_time_days: number | null;
  expected_arrival: string | null;
  linked_order_id: number | null;
  status: RfqLineStatus;
  note: string | null;
  linked_order_project_id: number | null;
  linked_order_expected_arrival: string | null;
  linked_quotation_number: string | null;
  linked_order_supplier_name: string | null;
};

export type RfqBatchDetail = RfqBatchSummary & {
  lines: RfqLine[];
};

export type ItemPlanningContextProject = {
  project_id: number;
  project_name: string;
  project_status: ProjectStatus;
  planned_start: string | null;
  is_planning_preview: boolean;
  required_quantity: number;
  dedicated_supply_by_start: number;
  generic_available_at_start: number;
  generic_allocated_quantity: number;
  covered_on_time_quantity: number;
  shortage_at_start: number;
  future_generic_recovery_quantity: number;
  future_dedicated_recovery_quantity: number;
  recovered_after_start_quantity: number;
  remaining_shortage_quantity: number;
  supply_sources_by_start: PlanningSource[];
  recovery_sources_after_start: PlanningSource[];
};

export type ItemPlanningContext = {
  item_id: number;
  item_number: string;
  manufacturer_name: string;
  preview_project_id: number | null;
  target_date: string | null;
  projects: ItemPlanningContextProject[];
};
