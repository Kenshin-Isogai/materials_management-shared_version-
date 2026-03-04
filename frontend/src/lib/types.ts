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
