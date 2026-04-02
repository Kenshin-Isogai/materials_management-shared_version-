import { FormEvent, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { CatalogPicker } from "../components/CatalogPicker";
import { apiDownload, apiGet, apiGetAllPages, apiGetWithPagination, apiSend, apiSendForm } from "../lib/api";
import { formatActionError, resolvePreviewSelection } from "../lib/previewState";
import type {
  CatalogSearchResult,
  Item,
  MissingItemResolverRow,
  Order,
  ProjectRow,
  PurchaseOrder,
  Quotation,
} from "../lib/types";

function normalizeMissingRows(
  rows: MissingItemResolverRow[] | undefined
): MissingItemResolverRow[] {
  return (rows ?? [])
    .filter((row) => String(row.item_number ?? "").trim())
    .map((row) => ({
      row: row.row,
      item_number: row.item_number.trim(),
      supplier: String(row.supplier ?? "").trim(),
      resolution_type: "new_item",
      category: row.category ?? "",
      url: row.url ?? "",
      description: row.description ?? "",
      canonical_item_number: row.canonical_item_number ?? "",
      units_per_order: row.units_per_order ?? ""
    }));
}

function downloadMissingRowsCsv(rows: MissingItemResolverRow[], filename: string) {
  if (!rows.length) return;
  const escapeCell = (value: string | null | undefined) => {
    const text = String(value ?? "");
    if (/[",\n\r]/.test(text)) {
      return `"${text.split("\"").join("\"\"")}"`;
    }
    return text;
  };
  const header = [
    "resolution_type",
    "supplier",
    "item_number",
    "manufacturer_name",
    "category",
    "url",
    "description",
    "canonical_item_number",
    "units_per_order",
  ];
  const lines = [
    header.join(","),
    ...rows.map((row) =>
      [
        row.resolution_type ?? "new_item",
        row.supplier ?? "",
        row.item_number ?? "",
        row.manufacturer_name ?? "UNKNOWN",
        row.category ?? "",
        row.url ?? "",
        row.description ?? "",
        row.canonical_item_number ?? "",
        row.units_per_order ?? "",
      ]
        .map(escapeCell)
        .join(",")
    ),
  ];
  const blob = new Blob(["\uFEFF", lines.join("\r\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

type ImportResult = {
  status: string;
  imported_count?: number;
  missing_count?: number;
  missing_artifact?: GeneratedArtifact;
  saved_alias_count?: number;
  rows?: MissingItemResolverRow[];
};

type GeneratedArtifact = {
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

type OrderImportPreviewStatus = "exact" | "high_confidence" | "needs_review" | "unresolved";

type OrderImportPreviewMatch = {
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

type OrderImportPreviewRow = {
  row: number;
  supplier_name: string;
  supplier_id?: number | null;
  item_number: string;
  quantity: number;
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

type OrderImportPreview = {
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
  can_auto_accept: boolean;
  rows: OrderImportPreviewRow[];
};

type OrderSplitUpdateResult = {
  order_id: number;
  split_order_id: number;
  updated_order: Order;
  created_order: Order;
};

function previewMatchToCatalogResult(match: OrderImportPreviewMatch): CatalogSearchResult {
  return {
    entity_type: "item",
    entity_id: match.item_id,
    value_text: match.canonical_item_number,
    display_label: match.display_label,
    summary: match.summary,
    match_source: match.match_source,
  };
}

function orderPreviewRowKey(row: OrderImportPreviewRow): string {
  return row.preview_key ?? `${row.source_name ?? "orders_import.csv"}:${row.row}`;
}

function mergeOrderImportPreviews(previews: OrderImportPreview[]): OrderImportPreview {
  const rows: OrderImportPreviewRow[] = [];
  const blockingErrors: string[] = [];
  const duplicateQuotationNumbers = new Set<string>();
  const summary = {
    total_rows: 0,
    exact: 0,
    high_confidence: 0,
    needs_review: 0,
    unresolved: 0,
  };

  previews.forEach((preview, sourceIndex) => {
    summary.total_rows += preview.summary.total_rows;
    summary.exact += preview.summary.exact;
    summary.high_confidence += preview.summary.high_confidence;
    summary.needs_review += preview.summary.needs_review;
    summary.unresolved += preview.summary.unresolved;
    blockingErrors.push(...preview.blocking_errors);
    preview.duplicate_quotation_numbers.forEach((value) => duplicateQuotationNumbers.add(value));
    preview.rows.forEach((row) => {
      rows.push({
        ...row,
        source_name: preview.source_name,
        source_index: sourceIndex,
        preview_key: `${sourceIndex}:${row.row}`,
      });
    });
  });

  return {
    source_name:
      previews.length === 1
        ? previews[0].source_name
        : `${previews.length} files`,
    supplier: {
      supplier_id: null,
      supplier_name: "Per-row supplier",
      exists: false,
      mode: previews.length > 0 ? "per_row" : "empty",
    },
    thresholds: previews[0]?.thresholds ?? { auto_accept: 0, review: 0 },
    summary,
    blocking_errors: blockingErrors,
    duplicate_quotation_numbers: Array.from(duplicateQuotationNumbers),
    can_auto_accept:
      previews.length > 0 &&
      previews.every((preview) => preview.can_auto_accept),
    rows,
  };
}

function normalizeCatalogValue(value: string): string {
  return value.trim().toLowerCase().replace(/[\s_-]+/g, "");
}

function previewStatusLabel(status: OrderImportPreviewStatus): string {
  switch (status) {
    case "exact":
      return "Exact";
    case "high_confidence":
      return "High Confidence";
    case "needs_review":
      return "Needs Review";
    case "unresolved":
      return "Unresolved";
    default:
      return status;
  }
}

function previewStatusTone(status: OrderImportPreviewStatus): string {
  switch (status) {
    case "exact":
      return "bg-emerald-50 text-emerald-700";
    case "high_confidence":
      return "bg-sky-50 text-sky-700";
    case "needs_review":
      return "bg-amber-50 text-amber-700";
    case "unresolved":
      return "bg-red-50 text-red-700";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function renderDocumentLink(url: string | null | undefined, label = "Open document") {
  if (!url) return "-";
  return (
    <a
      className="text-sky-700 underline underline-offset-2"
      href={url}
      target="_blank"
      rel="noreferrer noopener"
    >
      {label}
    </a>
  );
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function summaryMetric(label: string, value: string | number, tone: "slate" | "sky" | "emerald" | "amber" = "slate") {
  const toneClass =
    tone === "sky"
      ? "border-sky-200 bg-sky-50 text-sky-900"
      : tone === "emerald"
        ? "border-emerald-200 bg-emerald-50 text-emerald-900"
        : tone === "amber"
          ? "border-amber-200 bg-amber-50 text-amber-900"
          : "border-slate-200 bg-slate-50 text-slate-900";
  return (
    <div className={`rounded-xl border px-3 py-3 ${toneClass}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-bold">{value}</p>
    </div>
  );
}

export function OrdersPage() {
  const navigate = useNavigate();
  const [defaultDate, setDefaultDate] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [message, setMessage] = useState<string>("");
  const [latestGeneratedArtifact, setLatestGeneratedArtifact] = useState<GeneratedArtifact | null>(null);
  const [missingRows, setMissingRows] = useState<MissingItemResolverRow[]>([]);
  const [importPreview, setImportPreview] = useState<OrderImportPreview | null>(null);
  const [previewSelections, setPreviewSelections] = useState<Record<string, CatalogSearchResult | null>>({});
  const [previewUnits, setPreviewUnits] = useState<Record<string, string>>({});
  const [previewAliasSaves, setPreviewAliasSaves] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [editingQuotationId, setEditingQuotationId] = useState<number | null>(null);
  const [editingQuotationDocumentUrl, setEditingQuotationDocumentUrl] = useState("");
  const [editingQuotationIssueDate, setEditingQuotationIssueDate] = useState("");
  const [sortKey, setSortKey] = useState<"order_id" | "supplier_name" | "project_name" | "canonical_item_number" | "order_amount" | "expected_arrival" | "status">("order_id");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [quotationSortKey, setQuotationSortKey] = useState<"quotation_id" | "supplier_name" | "quotation_number" | "issue_date" | "quotation_document_url">("quotation_id");
  const [quotationSortDirection, setQuotationSortDirection] = useState<"asc" | "desc">("desc");
  const [orderPrimarySearch, setOrderPrimarySearch] = useState("");
  const [orderFilter, setOrderFilter] = useState("");
  const [quotationNumberSearch, setQuotationNumberSearch] = useState("");
  const [quotationFilter, setQuotationFilter] = useState("");
  const [purchaseOrderSearch, setPurchaseOrderSearch] = useState("");
  const [editingOrderId, setEditingOrderId] = useState<number | null>(null);
  const [editingOrderExpectedArrival, setEditingOrderExpectedArrival] = useState("");
  const [editingOrderSplitQuantity, setEditingOrderSplitQuantity] = useState("");
  const [editingOrderProjectId, setEditingOrderProjectId] = useState("");
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
  const [selectedQuotationId, setSelectedQuotationId] = useState<number | null>(null);
  const [selectedPurchaseOrderId, setSelectedPurchaseOrderId] = useState<number | null>(null);
  const [editingPurchaseOrderId, setEditingPurchaseOrderId] = useState<number | null>(null);
  const [editingPurchaseOrderDocumentUrl, setEditingPurchaseOrderDocumentUrl] = useState("");
  const orderDetailsRef = useRef<HTMLDivElement | null>(null);
  const quotationDetailsRef = useRef<HTMLDivElement | null>(null);
  const purchaseOrderDetailsRef = useRef<HTMLDivElement | null>(null);

  const { data: ordersData, error, isLoading, mutate: mutateOrders } = useSWR("/purchase-order-lines", () =>
    apiGetAllPages<Order>("/purchase-order-lines?per_page=200")
  );
  const {
    data: quotationsData,
    error: quotationsError,
    isLoading: quotationsLoading,
    mutate: mutateQuotations,
  } = useSWR("/quotations", () => apiGetAllPages<Quotation>("/quotations?per_page=200"));
  const {
    data: purchaseOrdersData,
    error: purchaseOrdersError,
    isLoading: purchaseOrdersLoading,
    mutate: mutatePurchaseOrders,
  } = useSWR("/purchase-orders", () => apiGetAllPages<PurchaseOrder>("/purchase-orders?per_page=200"));
  const { data: generatedArtifacts = [], mutate: mutateGeneratedArtifacts } = useSWR(
    "/artifacts?artifact_type=missing_items_register",
    apiGet<GeneratedArtifact[]>
  );
  const { data: itemsData } = useSWR("/items-orders-context", () =>
    apiGetWithPagination<Item[]>("/items?per_page=500")
  );
  const { data: projectsData } = useSWR("/projects-orders-context", () =>
    apiGetAllPages<ProjectRow>("/projects?per_page=200")
  );

  const sortedOrders = useMemo(() => {
    const rows = [...(ordersData ?? [])];
    rows.sort((a, b) => {
      const left = a[sortKey];
      const right = b[sortKey];
      const normalizedLeft = left ?? "";
      const normalizedRight = right ?? "";

      if (typeof normalizedLeft === "number" && typeof normalizedRight === "number") {
        return sortDirection === "asc" ? normalizedLeft - normalizedRight : normalizedRight - normalizedLeft;
      }

      const compare = String(normalizedLeft).localeCompare(String(normalizedRight));
      return sortDirection === "asc" ? compare : -compare;
    });
    return rows;
  }, [ordersData, sortDirection, sortKey]);

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

  const filteredSortedQuotations = useMemo(() => {
    const numberQuery = quotationNumberSearch.trim().toLowerCase();
    const filterQuery = quotationFilter.trim().toLowerCase();
    const rows = (quotationsData ?? []).filter((row) => {
      const quotationNumber = row.quotation_number.toLowerCase();
      const matchesNumber = !numberQuery || quotationNumber.includes(numberQuery);
      if (!matchesNumber) return false;

      if (!filterQuery) return true;
      const issueDate = row.issue_date ?? "";
      const quotationDocumentUrl = row.quotation_document_url ?? "";
      return [row.supplier_name, issueDate, quotationDocumentUrl]
        .join(" ")
        .toLowerCase()
        .includes(filterQuery);
    });

    rows.sort((a, b) => {
      const left = a[quotationSortKey] ?? "";
      const right = b[quotationSortKey] ?? "";
      if (typeof left === "number" && typeof right === "number") {
        return quotationSortDirection === "asc" ? left - right : right - left;
      }
      const compare = String(left).localeCompare(String(right));
      return quotationSortDirection === "asc" ? compare : -compare;
    });
    return rows;
  }, [quotationsData, quotationFilter, quotationNumberSearch, quotationSortDirection, quotationSortKey]);

  const orderCountByQuotationId = useMemo(() => {
    const counts = new Map<number, number>();
    for (const row of sortedOrders) {
      counts.set(row.quotation_id, (counts.get(row.quotation_id) ?? 0) + 1);
    }
    return counts;
  }, [sortedOrders]);

  const sortedPurchaseOrders = useMemo(() => {
    const rows = [...(purchaseOrdersData ?? [])];
    rows.sort((a, b) => b.purchase_order_id - a.purchase_order_id);
    return rows;
  }, [purchaseOrdersData]);

  const filteredPurchaseOrders = useMemo(() => {
    const query = purchaseOrderSearch.trim().toLowerCase();
    if (!query) return sortedPurchaseOrders;
    return sortedPurchaseOrders.filter((row) =>
      [
        row.purchase_order_id,
        row.supplier_name,
        row.purchase_order_document_url ?? "",
        row.first_order_date ?? "",
        row.last_order_date ?? "",
      ]
        .join(" ")
        .toLowerCase()
        .includes(query)
    );
  }, [purchaseOrderSearch, sortedPurchaseOrders]);

  const itemByNumber = useMemo(() => {
    return new Map((itemsData?.data ?? []).map((item) => [item.item_number, item]));
  }, [itemsData?.data]);

  const selectedOrder = useMemo(
    () => sortedOrders.find((row) => row.order_id === selectedOrderId) ?? null,
    [selectedOrderId, sortedOrders]
  );

  const selectedOrderItem = selectedOrder ? itemByNumber.get(selectedOrder.canonical_item_number) ?? null : null;

  const sameItemOrders = useMemo(() => {
    if (!selectedOrder) return [];
    return sortedOrders.filter((row) => row.canonical_item_number === selectedOrder.canonical_item_number);
  }, [selectedOrder, sortedOrders]);

  const sameItemQuotations = useMemo(() => {
    if (!sameItemOrders.length) return [];
    const quotationNumbers = new Set(sameItemOrders.map((row) => row.quotation_number));
    return (quotationsData ?? []).filter((row) => quotationNumbers.has(row.quotation_number));
  }, [quotationsData, sameItemOrders]);

  const selectedQuotation = useMemo(
    () => (quotationsData ?? []).find((row) => row.quotation_id === selectedQuotationId) ?? null,
    [quotationsData, selectedQuotationId]
  );

  const quotationOrders = useMemo(() => {
    if (!selectedQuotationId) return [];
    return sortedOrders.filter((row) => row.quotation_id === selectedQuotationId);
  }, [selectedQuotationId, sortedOrders]);

  const selectedPurchaseOrder = useMemo(
    () => (purchaseOrdersData ?? []).find((row) => row.purchase_order_id === selectedPurchaseOrderId) ?? null,
    [purchaseOrdersData, selectedPurchaseOrderId]
  );

  const purchaseOrderLines = useMemo(() => {
    if (!selectedPurchaseOrderId) return [];
    return sortedOrders.filter((row) => row.purchase_order_id === selectedPurchaseOrderId);
  }, [selectedPurchaseOrderId, sortedOrders]);

  const purchaseOrderQuotations = useMemo(() => {
    if (!purchaseOrderLines.length) return [];
    const quotationIds = new Set(purchaseOrderLines.map((row) => row.quotation_id));
    return (quotationsData ?? []).filter((row) => quotationIds.has(row.quotation_id));
  }, [purchaseOrderLines, quotationsData]);

  function scrollToSection(ref: { current: HTMLElement | null }) {
    requestAnimationFrame(() => {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function openOrderDetails(orderId: number) {
    setSelectedOrderId(orderId);
    scrollToSection(orderDetailsRef);
  }

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

  function openQuotationDetails(quotationId: number) {
    setMessage("");
    setSelectedQuotationId(quotationId);
    scrollToSection(quotationDetailsRef);
  }

  function openPurchaseOrderDetails(purchaseOrderId: number) {
    setMessage("");
    setSelectedPurchaseOrderId(purchaseOrderId);
    scrollToSection(purchaseOrderDetailsRef);
  }

  function toggleSort(nextKey: typeof sortKey) {
    if (sortKey === nextKey) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextKey);
    setSortDirection("asc");
  }

  function sortIndicator(key: typeof sortKey): string {
    if (key !== sortKey) return "↕";
    return sortDirection === "asc" ? "↑" : "↓";
  }

  function toggleQuotationSort(nextKey: typeof quotationSortKey) {
    if (quotationSortKey === nextKey) {
      setQuotationSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setQuotationSortKey(nextKey);
    setQuotationSortDirection("asc");
  }

  function quotationSortIndicator(key: typeof quotationSortKey): string {
    if (key !== quotationSortKey) return "↕";
    return quotationSortDirection === "asc" ? "↑" : "↓";
  }

  function resetImportPreview() {
    setImportPreview(null);
    setPreviewSelections({});
    setPreviewUnits({});
    setPreviewAliasSaves({});
  }

  function applyImportPreview(preview: OrderImportPreview) {
    const nextSelections: Record<string, CatalogSearchResult | null> = {};
    const nextUnits: Record<string, string> = {};
    const nextAliasSaves: Record<string, boolean> = {};
    for (const row of preview.rows) {
      const key = orderPreviewRowKey(row);
      nextSelections[key] = row.suggested_match
        ? previewMatchToCatalogResult(row.suggested_match)
        : null;
      nextUnits[key] = String(row.suggested_match?.units_per_order ?? 1);
      nextAliasSaves[key] = false;
    }
    setImportPreview(preview);
    setPreviewSelections(nextSelections);
    setPreviewUnits(nextUnits);
    setPreviewAliasSaves(nextAliasSaves);
  }

  function selectedPreviewMatch(row: OrderImportPreviewRow): CatalogSearchResult | null {
    return resolvePreviewSelection(
      previewSelections,
      orderPreviewRowKey(row),
      row.suggested_match ? previewMatchToCatalogResult(row.suggested_match) : null
    );
  }

  function previewUnitsValue(row: OrderImportPreviewRow): string {
    return previewUnits[orderPreviewRowKey(row)] ?? String(row.suggested_match?.units_per_order ?? 1);
  }

  function canOfferAliasSave(
    row: OrderImportPreviewRow,
    selected: CatalogSearchResult | null
  ): boolean {
    if (!selected) return false;
    return normalizeCatalogValue(row.item_number) !== normalizeCatalogValue(selected.value_text);
  }

  function unresolvedPreviewRows(): MissingItemResolverRow[] {
    if (!importPreview) return [];
    return importPreview.rows
      .filter((row) => row.status === "unresolved" && !selectedPreviewMatch(row))
      .map((row) => ({
        row: row.row,
        item_number: row.item_number,
        supplier: row.supplier_name,
        resolution_type: "new_item",
        category: "",
        url: "",
        description: "",
        canonical_item_number: "",
        units_per_order: "",
      }));
  }

  async function previewImport(event: FormEvent) {
    event.preventDefault();
    if (!files.length) return;
    setLoading(true);
    setMessage("");
    setLatestGeneratedArtifact(null);
    setMissingRows([]);
    resetImportPreview();
    try {
      const previews: OrderImportPreview[] = [];
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        if (defaultDate.trim()) form.append("default_order_date", defaultDate.trim());
        previews.push(await apiSendForm<OrderImportPreview>("/purchase-order-lines/import-preview", form));
      }
      const result = mergeOrderImportPreviews(previews);
      applyImportPreview(result);
      setMessage(
        result.can_auto_accept
          ? `Preview ready: files=${files.length}, rows=${result.summary.total_rows} are auto-acceptable.`
          : `Preview ready: files=${files.length}, rows=${result.summary.total_rows}, review=${result.summary.needs_review}, unresolved=${result.summary.unresolved}.`
      );
    } catch (error) {
      setMessage(formatActionError("Preview failed", error));
    } finally {
      setLoading(false);
    }
  }

  async function confirmImportPreview() {
    if (!files.length || !importPreview) return;
    if (importPreview.blocking_errors.length > 0) {
      setMessage(importPreview.blocking_errors[0]);
      return;
    }

    const unresolvedRows = importPreview.rows.filter((row) => !selectedPreviewMatch(row));
    if (unresolvedRows.length > 0) {
      setMessage(
        `Resolve preview rows before import: ${unresolvedRows.map((row) => row.row).join(", ")}`
      );
      return;
    }

    setLoading(true);
    setMessage("");
    setMissingRows([]);
    try {
      let totalImportedCount = 0;
      let totalSavedAliasCount = 0;
      for (const [sourceIndex, file] of files.entries()) {
        const rowOverrides: Record<number, { item_id: number; units_per_order: number }> = {};
        const aliasSaves: Array<{
          supplier_name: string;
          ordered_item_number: string;
          item_id: number;
          units_per_order: number;
        }> = [];
        for (const row of importPreview.rows.filter((entry) => entry.source_index === sourceIndex)) {
          const selection = selectedPreviewMatch(row);
          if (!selection) continue;
          const unitsValue = Number(previewUnitsValue(row));
          if (!Number.isInteger(unitsValue) || unitsValue <= 0) {
            setMessage(`Row ${row.row}: units/order must be an integer greater than 0.`);
            return;
          }

          const suggested = row.suggested_match;
          const requiresOverride =
            row.status !== "exact" ||
            suggested == null ||
            suggested.item_id !== selection.entity_id ||
            suggested.units_per_order !== unitsValue;

          if (requiresOverride) {
            rowOverrides[row.row] = {
              item_id: selection.entity_id,
              units_per_order: unitsValue,
            };
          }

          if (previewAliasSaves[orderPreviewRowKey(row)] && canOfferAliasSave(row, selection)) {
            aliasSaves.push({
              supplier_name: row.supplier_name,
              ordered_item_number: row.item_number,
              item_id: selection.entity_id,
              units_per_order: unitsValue,
            });
          }
        }

        const form = new FormData();
        form.append("file", file);
        if (defaultDate.trim()) form.append("default_order_date", defaultDate.trim());
        if (Object.keys(rowOverrides).length > 0) {
          form.append("row_overrides", JSON.stringify(rowOverrides));
        }
        if (aliasSaves.length > 0) {
          form.append("alias_saves", JSON.stringify(aliasSaves));
        }

        const result = await apiSendForm<ImportResult>("/purchase-order-lines/import", form);
        if (result.status === "missing_items") {
          const unresolved = normalizeMissingRows(result.rows);
          setMissingRows(unresolved);
          setLatestGeneratedArtifact(result.missing_artifact ?? null);
          setMessage(
            `Missing items detected (${result.missing_count}) in ${file.name}. Download the generated CSV, update it, then import it from Items.`
          );
          return;
        }
        totalImportedCount += result.imported_count ?? 0;
        totalSavedAliasCount += result.saved_alias_count ?? 0;
      }
      resetImportPreview();
      setLatestGeneratedArtifact(null);
      setMissingRows([]);
      setMessage(
        totalSavedAliasCount > 0
          ? `Imported ${totalImportedCount} rows across ${files.length} file(s) and saved ${totalSavedAliasCount} alias mapping(s).`
          : `Imported ${totalImportedCount} rows across ${files.length} file(s).`
      );
      await Promise.all([mutateOrders(), mutateQuotations()]);
    } catch (error) {
      setMessage(formatActionError("Import failed", error));
    } finally {
      setLoading(false);
    }
  }

  function downloadImportCsv(path: string, fallbackFilename: string) {
    void apiDownload(path, fallbackFilename).catch((error) => {
      setMessage(error instanceof Error ? error.message : String(error));
    });
  }

  function downloadGeneratedArtifact(artifact: GeneratedArtifact) {
    void apiDownload(`/artifacts/${artifact.artifact_id}/download`, artifact.filename).catch((error) => {
      setMessage(error instanceof Error ? error.message : String(error));
    });
  }

  async function markArrived(orderId: number) {
    setLoading(true);
    try {
      await apiSend(`/purchase-order-lines/${orderId}/arrival`, { method: "POST", body: JSON.stringify({}) });
      await Promise.all([mutateOrders(), mutateQuotations()]);
    } finally {
      setLoading(false);
    }
  }

  async function deleteOrder(orderId: number) {
    setLoading(true);
    try {
      await apiSend(`/purchase-order-lines/${orderId}`, { method: "DELETE" });
      setMessage(`Deleted order #${orderId}.`);
      await Promise.all([mutateOrders(), mutateQuotations()]);
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
          : `Updated order #${orderId}.`
      );
      cancelEditOrder();
      await Promise.all([mutateOrders(), mutateQuotations(), mutatePurchaseOrders()]);
    } catch (error) {
      setMessage(formatOrderUpdateError(error));
    } finally {
      setLoading(false);
    }
  }

  function beginEditQuotation(row: Quotation) {
    setEditingQuotationId(row.quotation_id);
    setEditingQuotationDocumentUrl(row.quotation_document_url ?? "");
    setEditingQuotationIssueDate(row.issue_date ?? "");
  }

  async function saveQuotationEdit(quotationId: number) {
    setLoading(true);
    try {
      await apiSend(`/quotations/${quotationId}`, {
        method: "PUT",
        body: JSON.stringify({
          issue_date: editingQuotationIssueDate.trim() || null,
          quotation_document_url: editingQuotationDocumentUrl.trim() || null,
        }),
      });
      setMessage(`Updated quotation #${quotationId}.`);
      setEditingQuotationId(null);
      await Promise.all([mutateOrders(), mutateQuotations(), mutatePurchaseOrders()]);
    } catch (error) {
      setMessage(`Quotation update failed: ${String(error ?? "")}`);
    } finally {
      setLoading(false);
    }
  }

  async function deleteQuotation(quotationId: number) {
    setLoading(true);
    try {
      await apiSend(`/quotations/${quotationId}`, { method: "DELETE" });
      setMessage(`Deleted quotation #${quotationId} and related orders.`);
      if (editingQuotationId === quotationId) setEditingQuotationId(null);
      await Promise.all([mutateOrders(), mutateQuotations(), mutatePurchaseOrders()]);
    } catch (error) {
      setMessage(`Quotation delete failed: ${String(error ?? "")}`);
    } finally {
      setLoading(false);
    }
  }

  function beginEditPurchaseOrder(row: PurchaseOrder) {
    setEditingPurchaseOrderId(row.purchase_order_id);
    setEditingPurchaseOrderDocumentUrl(row.purchase_order_document_url ?? "");
  }

  async function savePurchaseOrderEdit(purchaseOrderId: number) {
    setLoading(true);
    try {
      await apiSend(`/purchase-orders/${purchaseOrderId}`, {
        method: "PUT",
        body: JSON.stringify({
          purchase_order_document_url: editingPurchaseOrderDocumentUrl.trim() || null,
        }),
      });
      setMessage(`Updated purchase order #${purchaseOrderId}.`);
      setEditingPurchaseOrderId(null);
      await Promise.all([mutateOrders(), mutateQuotations(), mutatePurchaseOrders()]);
    } catch (error) {
      setMessage(`Purchase order update failed: ${String(error ?? "")}`);
    } finally {
      setLoading(false);
    }
  }

  async function deletePurchaseOrder(purchaseOrderId: number) {
    setLoading(true);
    try {
      await apiSend(`/purchase-orders/${purchaseOrderId}`, { method: "DELETE" });
      setMessage(`Deleted purchase order #${purchaseOrderId}.`);
      if (editingPurchaseOrderId === purchaseOrderId) setEditingPurchaseOrderId(null);
      if (selectedPurchaseOrderId === purchaseOrderId) setSelectedPurchaseOrderId(null);
      await Promise.all([mutateOrders(), mutateQuotations(), mutatePurchaseOrders()]);
    } catch (error) {
      setMessage(`Purchase order delete failed: ${String(error ?? "")}`);
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Purchase Orders</h1>
        <p className="mt-1 text-sm text-slate-600">
          Purchase-order-line import, quotation and PO header management, and line-level purchasing traceability.
        </p>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Import Purchase Order Lines CSV</h2>
        <div className="mb-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
          <p className="font-semibold text-slate-900">CSV Format</p>
          <p className="mt-1">
            Required columns: <code>supplier</code>, <code>item_number</code>, <code>quantity</code>,{" "}
            <code>quotation_number</code>, <code>issue_date</code>
          </p>
          <p>
            Required document column: <code>quotation_document_url</code>
          </p>
          <p>
            Optional columns: <code>order_date</code>, <code>expected_arrival</code>,{" "}
            <code>purchase_order_document_url</code>
          </p>
          <p className="mt-1">
            Use full HTTPS document URLs, such as a SharePoint link, for quotation and purchase-order references.
          </p>
          <p>
            This import path is metadata-only. Documents remain in the external document system and are not uploaded into this application.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              className="button-subtle"
              type="button"
              onClick={() => downloadImportCsv("/purchase-order-lines/import-template", "purchase_order_lines_import_template.csv")}
            >
              Download Template CSV
            </button>
            <button
              className="button-subtle"
              type="button"
              onClick={() => downloadImportCsv("/purchase-order-lines/import-reference", "purchase_order_lines_import_reference.csv")}
            >
              Download Reference CSV
            </button>
          </div>
        </div>
        <form className="grid gap-3 md:grid-cols-3" onSubmit={previewImport}>
          <input
            className="input"
            type="date"
            value={defaultDate}
            onChange={(e) => {
              setDefaultDate(e.target.value);
              resetImportPreview();
            }}
          />
          <input
            className="input"
            type="file"
            accept=".csv,text/csv"
            multiple
            onChange={(e) => {
              setFiles(Array.from(e.target.files ?? []));
              resetImportPreview();
            }}
            required
          />
          <button className="button" disabled={loading} type="submit">
            Preview Import
          </button>
        </form>
        <p className="mt-2 text-xs text-slate-500">
          {files.length > 0
            ? `${files.length} file(s) selected`
            : "Select one or more order CSV files. Supplier must be present in every row."}
        </p>
        {message && (
          <div className="mt-3 space-y-2">
            <p className="text-sm text-signal">{message}</p>
            {latestGeneratedArtifact && (
              <button
                className="button-subtle"
                type="button"
                onClick={() => downloadGeneratedArtifact(latestGeneratedArtifact)}
              >
                Download Generated CSV
              </button>
            )}
          </div>
        )}
        {importPreview && (
          <div className="mt-4 space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-900">Import Preview</p>
                <p className="mt-1 text-xs text-slate-600">
                  Combined preview across {files.length} file(s). Supplier is resolved per row from the CSV content.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-emerald-50 px-3 py-1 font-semibold text-emerald-700">
                  Exact {importPreview.summary.exact}
                </span>
                <span className="rounded-full bg-sky-50 px-3 py-1 font-semibold text-sky-700">
                  High {importPreview.summary.high_confidence}
                </span>
                <span className="rounded-full bg-amber-50 px-3 py-1 font-semibold text-amber-700">
                  Review {importPreview.summary.needs_review}
                </span>
                <span className="rounded-full bg-red-50 px-3 py-1 font-semibold text-red-700">
                  Unresolved {importPreview.summary.unresolved}
                </span>
              </div>
            </div>

            {importPreview.blocking_errors.length > 0 && (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                {importPreview.blocking_errors.map((errorText, index) => (
                  <p key={`${errorText}-${index}`}>{errorText}</p>
                ))}
              </div>
            )}

            {unresolvedPreviewRows().length > 0 && (
              <div className="flex flex-wrap gap-2">
                <button
                  className="button-subtle"
                  type="button"
                  onClick={() =>
                    downloadMissingRowsCsv(
                      unresolvedPreviewRows(),
                      "orders_preview_missing_items.csv"
                    )
                  }
                >
                  Download Missing Items CSV
                </button>
                <button className="button-subtle" type="button" onClick={() => navigate("/items")}>
                  Open Items Page
                </button>
                <p className="self-center text-xs text-slate-500">
                  Use this when the required canonical item is not in the catalog yet.
                </p>
              </div>
            )}

            <div className="overflow-x-auto">
              <table className="min-w-[1100px] text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="px-2 py-2">Row</th>
                    <th className="px-2 py-2">Raw Input</th>
                    <th className="px-2 py-2">Suggested Canonical Match</th>
                    <th className="px-2 py-2">Confidence</th>
                    <th className="px-2 py-2">Status</th>
                    <th className="px-2 py-2">User Action</th>
                  </tr>
                </thead>
                <tbody>
                  {importPreview.rows.map((row) => {
                    const selection = selectedPreviewMatch(row);
                    const canSaveAlias = canOfferAliasSave(row, selection);
                    return (
                      <tr key={orderPreviewRowKey(row)} className="border-b border-slate-100 align-top">
                        <td className="px-2 py-3 font-semibold text-slate-700">#{row.row}</td>
                        <td className="px-2 py-3">
                          <div className="space-y-1">
                            <p className="font-semibold text-slate-900">{row.item_number}</p>
                            <p className="text-xs text-slate-500">
                              {row.source_name ? `${row.source_name} | ` : ""}{row.supplier_name} | qty {row.quantity} | quotation {row.quotation_number}
                            </p>
                            <p className="text-xs text-slate-500">
                              order {row.order_date}
                              {row.expected_arrival ? ` | eta ${row.expected_arrival}` : ""}
                            </p>
                            {row.quotation_document_url && (
                              <p className="text-xs text-slate-500 break-all">{row.quotation_document_url}</p>
                            )}
                            {row.purchase_order_document_url && (
                              <p className="text-xs text-slate-500 break-all">{row.purchase_order_document_url}</p>
                            )}
                            {row.warnings.map((warning, index) => (
                              <p key={`${warning}-${index}`} className="text-xs font-semibold text-red-600">
                                {warning}
                              </p>
                            ))}
                          </div>
                        </td>
                        <td className="px-2 py-3">
                          {row.suggested_match ? (
                            <div className="space-y-1">
                              <p className="font-semibold text-slate-900">
                                {row.suggested_match.display_label}
                              </p>
                              <p className="text-xs text-slate-500">
                                units/order {row.suggested_match.units_per_order}
                              </p>
                              {row.suggested_match.summary && (
                                <p className="text-xs text-slate-500">
                                  {row.suggested_match.summary}
                                </p>
                              )}
                              {row.candidates.length > 1 && (
                                <p className="text-xs text-slate-400">
                                  {row.candidates.length} ranked candidates available
                                </p>
                              )}
                            </div>
                          ) : (
                            <p className="text-sm text-slate-500">No confident suggestion</p>
                          )}
                        </td>
                        <td className="px-2 py-3">
                          {row.confidence_score == null ? "-" : `${row.confidence_score}%`}
                        </td>
                        <td className="px-2 py-3">
                          <span
                            className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${previewStatusTone(row.status)}`}
                          >
                            {previewStatusLabel(row.status)}
                          </span>
                        </td>
                        <td className="px-2 py-3">
                          <div className="space-y-2">
                            <CatalogPicker
                              allowedTypes={["item"]}
                              onChange={(value) =>
                                setPreviewSelections((prev) => ({
                                  ...prev,
                                  [orderPreviewRowKey(row)]: value,
                                }))
                              }
                              placeholder="Search canonical item"
                              recentKey="orders-import-preview-item"
                              value={selection ?? null}
                            />
                            <div className="flex flex-wrap gap-2">
                              <input
                                className="input w-28"
                                min={1}
                                type="number"
                                value={previewUnitsValue(row)}
                                onChange={(event) =>
                                  setPreviewUnits((prev) => ({
                                    ...prev,
                                    [orderPreviewRowKey(row)]: event.target.value,
                                  }))
                                }
                              />
                              <span className="self-center text-xs text-slate-500">
                                units/order
                              </span>
                            </div>
                            {canSaveAlias && (
                              <label className="flex items-center gap-2 text-xs text-slate-600">
                                <input
                                  checked={previewAliasSaves[orderPreviewRowKey(row)] ?? false}
                                  onChange={(event) =>
                                    setPreviewAliasSaves((prev) => ({
                                      ...prev,
                                      [orderPreviewRowKey(row)]: event.target.checked,
                                    }))
                                  }
                                  type="checkbox"
                                />
                                Save supplier alias after import
                              </label>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                className="button"
                disabled={loading || importPreview.blocking_errors.length > 0}
                onClick={() => void confirmImportPreview()}
                type="button"
              >
                Confirm Import
              </button>
              <button
                className="button-subtle"
                disabled={loading}
                onClick={resetImportPreview}
                type="button"
              >
                Clear Preview
              </button>
              <p className="self-center text-xs text-slate-500">
                High-confidence rows can be confirmed directly; review and unresolved rows can be adjusted here before commit.
              </p>
            </div>
          </div>
        )}
        {missingRows.length > 0 && (
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3">
            <p className="mb-2 text-sm font-semibold text-amber-900">
              Unresolved item numbers in this upload
            </p>
            <div className="mb-2 flex flex-wrap gap-2">
              {latestGeneratedArtifact && (
                <button
                  className="button-subtle"
                  type="button"
                  onClick={() => downloadGeneratedArtifact(latestGeneratedArtifact)}
                >
                  Download Generated CSV
                </button>
              )}
              <button className="button-subtle" type="button" onClick={() => navigate("/items")}>
                Open Items Page
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-[460px] text-sm">
                <thead>
                  <tr className="border-b border-amber-200 text-left text-amber-800">
                    <th className="px-2 py-2">CSV Row</th>
                    <th className="px-2 py-2">Supplier</th>
                    <th className="px-2 py-2">Item Number</th>
                  </tr>
                </thead>
                <tbody>
                  {missingRows.map((row, idx) => (
                    <tr key={`${row.item_number}-${idx}`} className="border-b border-amber-100">
                      <td className="px-2 py-2">{row.row ?? "-"}</td>
                      <td className="px-2 py-2">{row.supplier ?? "-"}</td>
                      <td className="px-2 py-2 font-semibold">{row.item_number}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      <section className="panel p-4">
        {generatedArtifacts.length > 0 && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
            <h3 className="font-medium text-slate-900">Recent Generated Files</h3>
            <p className="mt-1 text-xs text-slate-500">
              Browser download list only. Filesystem storage paths are intentionally hidden.
            </p>
            <div className="mt-2 space-y-2">
              {generatedArtifacts.slice(0, 5).map((artifact) => (
                <div
                  key={artifact.artifact_id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2"
                >
                  <div className="text-sm text-slate-700">
                    <p className="font-medium text-slate-900">{artifact.filename}</p>
                    <p className="text-xs text-slate-500">
                      Created {formatTimestamp(artifact.created_at)} · {(artifact.size_bytes / 1024).toFixed(1)} KB
                    </p>
                  </div>
                  <button
                    className="button-subtle"
                    type="button"
                    onClick={() => downloadGeneratedArtifact(artifact)}
                  >
                    Download
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="panel p-4">
        <div className="mb-3">
          <h2 className="font-display text-lg font-semibold">Purchase Order Lines</h2>
          <p className="mt-1 text-sm text-slate-500">Line-level ETA, split, linked document traceability, and project assignment.</p>
        </div>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {summaryMetric("Total lines", ordersData?.length ?? 0, "amber")}
          {summaryMetric("Filtered", filteredSortedOrders.length, "slate")}
          {summaryMetric("Selected item family", sameItemOrders.length, "slate")}
          {summaryMetric("Selected status", selectedOrder?.status ?? "-", "sky")}
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <input
            className="input"
            value={orderPrimarySearch}
            onChange={(event) => setOrderPrimarySearch(event.target.value)}
            placeholder="Search by order #, item, or quotation number"
          />
          <input
            className="input"
            value={orderFilter}
            onChange={(event) => setOrderFilter(event.target.value)}
            placeholder="Filter by supplier, project, expected date, or status"
          />
        </div>
        {isLoading && <p className="mt-3 text-sm text-slate-500">Loading...</p>}
        {error && <ApiErrorNotice error={error} area="purchase order line data" className="mt-3" />}
        {ordersData && (
          <div className="mt-3 grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
            <div className="max-h-[42rem] overflow-y-auto pr-1">
              <p className="mb-2 text-xs text-slate-500">Showing {filteredSortedOrders.length} / {ordersData.length} orders</p>
              <div className="space-y-2">
                {filteredSortedOrders.map((row) => (
                  <div key={row.order_id} className={`rounded-2xl border px-4 py-3 ${row.order_id === selectedOrderId ? "border-amber-400 bg-amber-50" : "border-slate-200 bg-white"}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold">Line #{row.order_id} · {row.canonical_item_number}</p>
                        <p className="text-sm text-slate-600">{row.supplier_name} · PO #{row.purchase_order_id} · Quote {row.quotation_number}</p>
                        <p className="text-xs text-slate-500">
                          Qty {row.order_amount} · ETA {row.expected_arrival ?? "-"} · {row.status}
                          {row.project_name ? ` · ${row.project_name}` : ""}
                        </p>
                      </div>
                      <button className="button-subtle" onClick={() => openOrderDetails(row.order_id)} disabled={loading}>Line Details</button>
                    </div>
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      <div>
                        {editingOrderId === row.order_id ? (
                          <div className="space-y-2">
                            <input className="input" type="date" value={editingOrderExpectedArrival} onChange={(event) => setEditingOrderExpectedArrival(event.target.value)} />
                            <input className="input" type="number" min={1} max={row.order_amount - 1} placeholder={`Split qty (1-${row.order_amount - 1})`} value={editingOrderSplitQuantity} onChange={(event) => setEditingOrderSplitQuantity(event.target.value)} />
                            <select className="input" value={editingOrderProjectId} onChange={(event) => setEditingOrderProjectId(event.target.value)}>
                              <option value="">No project assignment</option>
                              {(projectsData ?? []).map((project) => (
                                <option key={project.project_id} value={project.project_id}>
                                  #{project.project_id} {project.name} ({project.status})
                                </option>
                              ))}
                            </select>
                          </div>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-start justify-end gap-2">
                        {row.status === "Ordered" ? (
                          <>
                            <button className="button-subtle" onClick={() => markArrived(row.order_id)} disabled={loading}>Mark Arrived</button>
                            {editingOrderId === row.order_id ? (
                              <>
                                <button className="button-subtle" onClick={() => saveOrderEdit(row.order_id)} disabled={loading}>Save Order</button>
                                <button className="button-subtle" onClick={cancelEditOrder} disabled={loading}>Cancel</button>
                              </>
                            ) : (
                              <button className="button-subtle" onClick={() => beginEditOrder(row)} disabled={loading}>Edit Order</button>
                            )}
                          </>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                        <button className="button-subtle" onClick={() => deleteOrder(row.order_id)} disabled={loading || row.status === "Arrived"} title={row.status === "Arrived" ? "Arrived orders cannot be deleted" : "Delete this order"}>
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="border-t border-slate-200 pt-4 xl:border-l xl:border-t-0 xl:pl-4 xl:pt-0" ref={orderDetailsRef}>
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="font-display text-base font-semibold">Purchase Order Line Details</h3>
                {selectedOrder && (
                  <button type="button" className="button-subtle" onClick={() => setSelectedOrderId(null)}>
                    Clear
                  </button>
                )}
              </div>
              {!selectedOrder ? (
                <p className="text-sm text-slate-500">Select a line to inspect item metadata and linked quotation / purchase-order headers.</p>
              ) : (
                <div className="space-y-3 text-sm">
                  <div className="grid gap-3 md:grid-cols-2">
                    {summaryMetric("Line ID", `#${selectedOrder.order_id}`, "amber")}
                    {summaryMetric("Qty", selectedOrder.order_amount, "slate")}
                    {summaryMetric("Status", selectedOrder.status, "sky")}
                    {summaryMetric("Same-item rows", sameItemOrders.length, "slate")}
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="grid gap-3 md:grid-cols-2">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Item</p>
                        <p className="mt-1 font-medium text-slate-900">{selectedOrder.canonical_item_number}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Supplier</p>
                        <p className="mt-1 font-medium text-slate-900">{selectedOrder.supplier_name}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Quotation</p>
                        <p className="mt-1 font-medium text-slate-900">{selectedOrder.quotation_number}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Purchase Order</p>
                        <p className="mt-1 font-medium text-slate-900">#{selectedOrder.purchase_order_id}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Expected Arrival</p>
                        <p className="mt-1 font-medium text-slate-900">{selectedOrder.expected_arrival ?? "-"}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Project</p>
                        <p className="mt-1 font-medium text-slate-900">{selectedOrder.project_name ?? "-"}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Quotation Document</p>
                        <p className="mt-1">{renderDocumentLink(selectedOrder.quotation_document_url)}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Purchase-order Document</p>
                        <p className="mt-1">{renderDocumentLink(selectedOrder.purchase_order_document_url)}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Category</p>
                        <p className="mt-1 font-medium text-slate-900">{selectedOrderItem?.category ?? "-"}</p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Description</p>
                        <p className="mt-1 font-medium text-slate-900">{selectedOrderItem?.description ?? "-"}</p>
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button type="button" className="button-subtle" onClick={() => openReservationPrefill(selectedOrder)}>
                      Create Provisional Reservation…
                    </button>
                    <p className="text-xs text-slate-500">
                      Creates a stock-backed reservation draft on the Reservations page. Order dedication remains managed from
                      order/procurement linkage rules.
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      <section className="grid gap-4 xl:grid-cols-2 xl:items-start">
        <div className="panel flex min-h-[46rem] flex-col p-4">
          <div className="mb-3">
            <h2 className="font-display text-lg font-semibold">Quotations</h2>
            <p className="mt-1 text-sm text-slate-500">Quotation headers and the purchase-order lines created from them.</p>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {summaryMetric("Total quotations", quotationsData?.length ?? 0, "sky")}
            {summaryMetric("Selected linked lines", quotationOrders.length, "slate")}
          </div>
          <div className="mt-3 grid gap-2">
            <input className="input" value={quotationNumberSearch} onChange={(event) => setQuotationNumberSearch(event.target.value)} placeholder="Search by quotation number" />
            <input className="input" value={quotationFilter} onChange={(event) => setQuotationFilter(event.target.value)} placeholder="Filter by supplier, issue date, or document URL" />
          </div>
          <div className="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
            {quotationsLoading && <p className="text-sm text-slate-500">Loading...</p>}
            {quotationsError && <ApiErrorNotice error={quotationsError} area="quotation data" />}
            {quotationsData && (
              <>
                <p className="mb-2 text-xs text-slate-500">Showing {filteredSortedQuotations.length} / {quotationsData.length} quotations</p>
                <div className="space-y-2">
                  {filteredSortedQuotations.map((row) => (
                    <button key={row.quotation_id} type="button" onClick={() => openQuotationDetails(row.quotation_id)} className={`w-full rounded-2xl border px-4 py-3 text-left transition ${row.quotation_id === selectedQuotationId ? "border-sky-400 bg-sky-50" : "border-slate-200 bg-white hover:border-slate-300"}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-semibold">#{row.quotation_id} {row.quotation_number}</p>
                          <p className="text-sm text-slate-600">{row.supplier_name}</p>
                          <p className="text-xs text-slate-500">Issue {row.issue_date ?? "-"}</p>
                        </div>
                        <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">{orderCountByQuotationId.get(row.quotation_id) ?? 0} lines</span>
                      </div>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          <div className="mt-4 border-t border-slate-200 pt-4" ref={quotationDetailsRef}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="font-display text-base font-semibold">Quotation Details</h3>
              {selectedQuotation && <button type="button" className="button-subtle" onClick={() => setSelectedQuotationId(null)}>Clear</button>}
            </div>
            {!selectedQuotation ? (
              <p className="text-sm text-slate-500">Select a quotation to inspect its document metadata and linked lines.</p>
            ) : (
              <div className="space-y-3 text-sm">
                <div className="grid gap-3 md:grid-cols-2">
                  {summaryMetric("Quotation ID", `#${selectedQuotation.quotation_id}`, "sky")}
                  {summaryMetric("Linked lines", quotationOrders.length, "slate")}
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Supplier</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedQuotation.supplier_name}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Quotation Number</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedQuotation.quotation_number}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Issue Date</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedQuotation.issue_date ?? "-"}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Document</p>
                      <p className="mt-1">{renderDocumentLink(selectedQuotation.quotation_document_url)}</p>
                    </div>
                  </div>
                  <div className="mt-3 flex gap-2">
                    {editingQuotationId === selectedQuotation.quotation_id ? (
                      <>
                        <button className="button-subtle" onClick={() => saveQuotationEdit(selectedQuotation.quotation_id)} disabled={loading}>Save</button>
                        <button className="button-subtle" onClick={() => setEditingQuotationId(null)} disabled={loading}>Cancel</button>
                      </>
                    ) : (
                      <button className="button-subtle" onClick={() => beginEditQuotation(selectedQuotation)} disabled={loading}>Edit</button>
                    )}
                    <button className="button-subtle" onClick={() => deleteQuotation(selectedQuotation.quotation_id)} disabled={loading}>Delete</button>
                  </div>
                  {editingQuotationId === selectedQuotation.quotation_id && (
                    <div className="mt-3 grid gap-2">
                      <input className="input" value={editingQuotationIssueDate} onChange={(event) => setEditingQuotationIssueDate(event.target.value)} placeholder="YYYY-MM-DD" />
                      <input className="input" value={editingQuotationDocumentUrl} onChange={(event) => setEditingQuotationDocumentUrl(event.target.value)} placeholder="https://..." />
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="panel flex min-h-[46rem] flex-col p-4">
          <div className="mb-3">
            <h2 className="font-display text-lg font-semibold">Purchase Orders</h2>
            <p className="mt-1 text-sm text-slate-500">Purchase-order headers, separated from the line rows they own.</p>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {summaryMetric("Total purchase orders", purchaseOrdersData?.length ?? 0, "emerald")}
            {summaryMetric("Selected linked lines", purchaseOrderLines.length, "slate")}
          </div>
          <div className="mt-3">
            <input className="input" value={purchaseOrderSearch} onChange={(event) => setPurchaseOrderSearch(event.target.value)} placeholder="Search by supplier, PO id, date, or document URL" />
          </div>
          <div className="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
            {purchaseOrdersLoading && <p className="text-sm text-slate-500">Loading...</p>}
            {purchaseOrdersError && <ApiErrorNotice error={purchaseOrdersError} area="purchase order header data" />}
            {purchaseOrdersData && (
              <>
                <p className="mb-2 text-xs text-slate-500">Showing {filteredPurchaseOrders.length} / {purchaseOrdersData.length} purchase orders</p>
                <div className="space-y-2">
                  {filteredPurchaseOrders.map((row) => (
                    <button key={row.purchase_order_id} type="button" onClick={() => openPurchaseOrderDetails(row.purchase_order_id)} className={`w-full rounded-2xl border px-4 py-3 text-left transition ${row.purchase_order_id === selectedPurchaseOrderId ? "border-emerald-400 bg-emerald-50" : "border-slate-200 bg-white hover:border-slate-300"}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-semibold">PO #{row.purchase_order_id}</p>
                          <p className="text-sm text-slate-600">{row.supplier_name}</p>
                          <p className="text-xs text-slate-500">{row.first_order_date ?? "-"} to {row.last_order_date ?? "-"}</p>
                        </div>
                        <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">{row.line_count} lines</span>
                      </div>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          <div className="mt-4 border-t border-slate-200 pt-4" ref={purchaseOrderDetailsRef}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="font-display text-base font-semibold">Purchase Order Details</h3>
              {selectedPurchaseOrder && <button type="button" className="button-subtle" onClick={() => setSelectedPurchaseOrderId(null)}>Clear</button>}
            </div>
            {!selectedPurchaseOrder ? (
              <p className="text-sm text-slate-500">Select a purchase order to inspect header metadata and included lines.</p>
            ) : (
              <div className="space-y-3 text-sm">
                <div className="grid gap-3 md:grid-cols-2">
                  {summaryMetric("PO ID", `#${selectedPurchaseOrder.purchase_order_id}`, "emerald")}
                  {summaryMetric("Linked quotations", purchaseOrderQuotations.length, "slate")}
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Supplier</p>
                      <p className="mt-1 font-medium text-slate-900">{selectedPurchaseOrder.supplier_name}</p>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Document</p>
                      <p className="mt-1">{renderDocumentLink(selectedPurchaseOrder.purchase_order_document_url)}</p>
                    </div>
                  </div>
                  <div className="mt-3 flex gap-2">
                    {editingPurchaseOrderId === selectedPurchaseOrder.purchase_order_id ? (
                      <>
                        <button className="button-subtle" onClick={() => savePurchaseOrderEdit(selectedPurchaseOrder.purchase_order_id)} disabled={loading}>Save</button>
                        <button className="button-subtle" onClick={() => setEditingPurchaseOrderId(null)} disabled={loading}>Cancel</button>
                      </>
                    ) : (
                      <button className="button-subtle" onClick={() => beginEditPurchaseOrder(selectedPurchaseOrder)} disabled={loading}>Edit</button>
                    )}
                    <button className="button-subtle" onClick={() => deletePurchaseOrder(selectedPurchaseOrder.purchase_order_id)} disabled={loading}>Delete</button>
                  </div>
                  {editingPurchaseOrderId === selectedPurchaseOrder.purchase_order_id && (
                    <div className="mt-3">
                      <input className="input" value={editingPurchaseOrderDocumentUrl} onChange={(event) => setEditingPurchaseOrderDocumentUrl(event.target.value)} placeholder="https://..." />
                    </div>
                  )}
                </div>
                {purchaseOrderLines.length ? (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Included Lines</p>
                    <div className="space-y-2">
                      {purchaseOrderLines.map((row) => (
                        <div key={`po-line-${row.order_id}`} className="rounded-xl border border-slate-200 px-3 py-3">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="font-semibold">Line #{row.order_id} · {row.canonical_item_number}</p>
                              <p className="text-sm text-slate-600">Quote {row.quotation_number} · Qty {row.order_amount} · ETA {row.expected_arrival ?? "-"}</p>
                            </div>
                            <button className="button-subtle" type="button" onClick={() => openOrderDetails(row.order_id)}>Line Details</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">No purchase-order lines are linked to this header.</p>
                )}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
