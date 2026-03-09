import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import useSWR from "swr";
import { CatalogPicker } from "../components/CatalogPicker";
import { apiDownload, apiGetAllPages, apiGetWithPagination, apiSend, apiSendForm } from "../lib/api";
import { formatActionError, resolvePreviewSelection } from "../lib/previewState";
import type {
  CatalogSearchResult,
  Item,
  MissingItemResolverRow,
  Order,
  Quotation,
} from "../lib/types";

const PENDING_MISSING_ITEMS_KEY = "mm.pending_missing_items";
const PENDING_ORDER_IMPORT_KEY = "mm.pending_order_import";
const PENDING_BATCH_RETRY_KEY = "mm.pending_batch_retry";

type PendingOrderImport = {
  supplier_name: string;
  default_order_date: string;
  file_name: string;
  file_text: string;
};

type PendingBatchRetry = {
  csv_path: string;
  unregistered_root: string;
  registered_root: string;
  default_order_date: string;
};

function normalizeMissingRows(
  rows: MissingItemResolverRow[] | undefined,
  fallbackSupplier: string
): MissingItemResolverRow[] {
  return (rows ?? [])
    .filter((row) => String(row.item_number ?? "").trim())
    .map((row) => ({
      row: row.row,
      item_number: row.item_number.trim(),
      supplier: String(row.supplier ?? fallbackSupplier).trim() || fallbackSupplier,
      resolution_type: "new_item",
      category: row.category ?? "",
      url: row.url ?? "",
      description: row.description ?? "",
      canonical_item_number: row.canonical_item_number ?? "",
      units_per_order: row.units_per_order ?? ""
    }));
}

type ImportResult = {
  status: string;
  imported_count?: number;
  missing_count?: number;
  missing_csv_path?: string;
  saved_alias_count?: number;
  rows?: MissingItemResolverRow[];
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
  item_number: string;
  quantity: number;
  quotation_number: string;
  issue_date: string | null;
  order_date: string;
  expected_arrival: string | null;
  pdf_link: string | null;
  status: OrderImportPreviewStatus;
  confidence_score: number | null;
  suggested_match: OrderImportPreviewMatch | null;
  candidates: OrderImportPreviewMatch[];
  warnings: string[];
  order_amount: number | null;
};

type OrderImportPreview = {
  source_name: string;
  supplier: {
    supplier_id: number | null;
    supplier_name: string;
    exists: boolean;
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

type BatchNormalization = {
  kind?: string;
  from: string;
  to: string;
  file?: string;
  quotation_number?: string;
  row?: string;
  quotation_id?: string;
};

type UnregisteredFileReport = {
  file: string;
  supplier?: string;
  status: string;
  error?: string;
  missing_count?: number;
  missing_csv_path?: string;
  missing_rows?: MissingItemResolverRow[];
  warnings?: string[];
  normalizations?: BatchNormalization[];
};

type BatchErrorReport = {
  phase: "register" | "import";
  file: string;
  supplier?: string;
  error: string;
};

type RegisterBatchResult = {
  status: string;
  processed: number;
  succeeded: number;
  failed: number;
  files?: UnregisteredFileReport[];
  warnings?: string[];
  normalizations?: BatchNormalization[];
};

type ImportBatchResult = {
  status: string;
  processed: number;
  succeeded: number;
  missing_items: number;
  failed: number;
  files?: UnregisteredFileReport[];
  warnings?: string[];
  normalizations?: BatchNormalization[];
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

export function OrdersPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [supplier, setSupplier] = useState("");
  const [supplierSelection, setSupplierSelection] = useState<CatalogSearchResult | null>(null);
  const [defaultDate, setDefaultDate] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [unregisteredRoot, setUnregisteredRoot] = useState("");
  const [registeredRoot, setRegisteredRoot] = useState("");
  const [message, setMessage] = useState<string>("");
  const [missingRows, setMissingRows] = useState<MissingItemResolverRow[]>([]);
  const [importPreview, setImportPreview] = useState<OrderImportPreview | null>(null);
  const [previewSelections, setPreviewSelections] = useState<Record<number, CatalogSearchResult | null>>({});
  const [previewUnits, setPreviewUnits] = useState<Record<number, string>>({});
  const [previewAliasSaves, setPreviewAliasSaves] = useState<Record<number, boolean>>({});
  const [batchMissingReports, setBatchMissingReports] = useState<UnregisteredFileReport[]>([]);
  const [batchErrorReports, setBatchErrorReports] = useState<BatchErrorReport[]>([]);
  const [batchWarnings, setBatchWarnings] = useState<string[]>([]);
  const [batchNormalizations, setBatchNormalizations] = useState<BatchNormalization[]>([]);
  const [showAdvancedBatch, setShowAdvancedBatch] = useState(false);
  const [loading, setLoading] = useState(false);
  const [editingQuotationId, setEditingQuotationId] = useState<number | null>(null);
  const [editingQuotationPdfLink, setEditingQuotationPdfLink] = useState("");
  const [editingQuotationIssueDate, setEditingQuotationIssueDate] = useState("");
  const [sortKey, setSortKey] = useState<"order_id" | "supplier_name" | "project_name" | "canonical_item_number" | "order_amount" | "expected_arrival" | "status">("order_id");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [quotationSortKey, setQuotationSortKey] = useState<"quotation_id" | "supplier_name" | "quotation_number" | "issue_date" | "pdf_link">("quotation_id");
  const [quotationSortDirection, setQuotationSortDirection] = useState<"asc" | "desc">("desc");
  const [orderPrimarySearch, setOrderPrimarySearch] = useState("");
  const [orderFilter, setOrderFilter] = useState("");
  const [quotationNumberSearch, setQuotationNumberSearch] = useState("");
  const [quotationFilter, setQuotationFilter] = useState("");
  const [isOrderListExpanded, setIsOrderListExpanded] = useState(false);
  const [isImportedQuotationsExpanded, setIsImportedQuotationsExpanded] = useState(false);
  const [editingOrderId, setEditingOrderId] = useState<number | null>(null);
  const [editingOrderExpectedArrival, setEditingOrderExpectedArrival] = useState("");
  const [editingOrderSplitQuantity, setEditingOrderSplitQuantity] = useState("");
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
  const [selectedQuotationId, setSelectedQuotationId] = useState<number | null>(null);
  const orderDetailsRef = useRef<HTMLElement | null>(null);
  const quotationDetailsRef = useRef<HTMLElement | null>(null);

  const { data: ordersData, error, isLoading, mutate: mutateOrders } = useSWR("/orders", () =>
    apiGetAllPages<Order>("/orders?per_page=200")
  );
  const {
    data: quotationsData,
    error: quotationsError,
    isLoading: quotationsLoading,
    mutate: mutateQuotations,
  } = useSWR("/quotations", () => apiGetAllPages<Quotation>("/quotations?per_page=200"));
  const { data: itemsData } = useSWR("/items-orders-context", () =>
    apiGetWithPagination<Item[]>("/items?per_page=500")
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
      const pdfLink = row.pdf_link ?? "";
      return [row.supplier_name, issueDate, pdfLink]
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

  function scrollToSection(ref: { current: HTMLElement | null }) {
    requestAnimationFrame(() => {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function openOrderDetails(orderId: number) {
    setSelectedOrderId(orderId);
    setIsOrderListExpanded(false);
    scrollToSection(orderDetailsRef);
  }

  function openQuotationDetails(quotationId: number) {
    setMessage("");
    setSelectedQuotationId(quotationId);
    setIsImportedQuotationsExpanded(false);
    scrollToSection(quotationDetailsRef);
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

  useEffect(() => {
    const state = location.state as { autoMessage?: string } | null;
    if (!state?.autoMessage) return;
    setMessage(state.autoMessage);
    navigate(location.pathname, { replace: true, state: null });
  }, [location.pathname, location.state, navigate]);

  async function rememberPendingOrderImport(sourceFile: File) {
    const payload: PendingOrderImport = {
      supplier_name: supplier.trim(),
      default_order_date: defaultDate.trim(),
      file_name: sourceFile.name || "order_import.csv",
      file_text: await sourceFile.text(),
    };
    sessionStorage.setItem(PENDING_ORDER_IMPORT_KEY, JSON.stringify(payload));
  }

  function openMissingResolver(rows: MissingItemResolverRow[]) {
    if (!rows.length) return;
    sessionStorage.setItem(PENDING_MISSING_ITEMS_KEY, JSON.stringify(rows));
    navigate("/items", {
      state: {
        pendingMissingRows: rows,
      },
    });
  }

  function uniqueWarnings(values: string[]): string[] {
    return Array.from(new Set(values.filter((value) => value.trim())));
  }

  function uniqueNormalizations(values: BatchNormalization[]): BatchNormalization[] {
    const seen = new Set<string>();
    const result: BatchNormalization[] = [];
    for (const value of values) {
      const key = JSON.stringify(value);
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(value);
    }
    return result;
  }

  function toBatchErrorReports(
    phase: "register" | "import",
    files: UnregisteredFileReport[] | undefined
  ): BatchErrorReport[] {
    return (files ?? [])
      .filter((entry) => entry.status === "error" && String(entry.error ?? "").trim())
      .map((entry) => ({
        phase,
        file: entry.file,
        supplier: entry.supplier,
        error: String(entry.error),
      }));
  }

  function resetImportPreview() {
    setImportPreview(null);
    setPreviewSelections({});
    setPreviewUnits({});
    setPreviewAliasSaves({});
  }

  function applyImportPreview(preview: OrderImportPreview) {
    const nextSelections: Record<number, CatalogSearchResult | null> = {};
    const nextUnits: Record<number, string> = {};
    const nextAliasSaves: Record<number, boolean> = {};
    for (const row of preview.rows) {
      nextSelections[row.row] = row.suggested_match
        ? previewMatchToCatalogResult(row.suggested_match)
        : null;
      nextUnits[row.row] = String(row.suggested_match?.units_per_order ?? 1);
      nextAliasSaves[row.row] = false;
    }
    setImportPreview(preview);
    setPreviewSelections(nextSelections);
    setPreviewUnits(nextUnits);
    setPreviewAliasSaves(nextAliasSaves);
  }

  function selectedPreviewMatch(row: OrderImportPreviewRow): CatalogSearchResult | null {
    return resolvePreviewSelection(
      previewSelections,
      row.row,
      row.suggested_match ? previewMatchToCatalogResult(row.suggested_match) : null
    );
  }

  function previewUnitsValue(row: OrderImportPreviewRow): string {
    return previewUnits[row.row] ?? String(row.suggested_match?.units_per_order ?? 1);
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

  async function openPreviewMissingResolver() {
    if (!file) return;
    const unresolved = unresolvedPreviewRows();
    if (!unresolved.length) return;
    try {
      await rememberPendingOrderImport(file);
    } catch {
      // Keep the resolver path available even if session storage write fails.
    }
    openMissingResolver(unresolved);
  }

  async function previewImport(event: FormEvent) {
    event.preventDefault();
    if (!file || !supplier.trim()) return;
    setLoading(true);
    setMessage("");
    setMissingRows([]);
    resetImportPreview();
    sessionStorage.removeItem(PENDING_BATCH_RETRY_KEY);
    try {
      const form = new FormData();
      form.append("file", file);
      if (supplierSelection) {
        form.append("supplier_id", String(supplierSelection.entity_id));
      } else {
        form.append("supplier_name", supplier);
      }
      if (defaultDate.trim()) form.append("default_order_date", defaultDate.trim());
      const result = await apiSendForm<OrderImportPreview>("/orders/import-preview", form);
      applyImportPreview(result);
      setMessage(
        result.can_auto_accept
          ? `Preview ready: ${result.summary.total_rows} row(s) are auto-acceptable.`
          : `Preview ready: ${result.summary.total_rows} row(s), review=${result.summary.needs_review}, unresolved=${result.summary.unresolved}.`
      );
    } catch (error) {
      const messageText = String(error ?? "");
      if (messageText.includes("imports/orders/registered/pdf_files")) {
        setMessage(
          "Preview failed: Manual import requires pdf_link to be blank, filename-only, or imports/orders/registered/pdf_files/<supplier>/<file>.pdf. " +
          "For unregistered folder CSV files, use 'Unregistered Folder Batch'."
        );
      } else {
        setMessage(formatActionError("Preview failed", error));
      }
    } finally {
      setLoading(false);
    }
  }

  async function confirmImportPreview() {
    if (!file || !supplier.trim() || !importPreview) return;
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

    const rowOverrides: Record<number, { item_id: number; units_per_order: number }> = {};
    const aliasSaves: Array<{
      ordered_item_number: string;
      item_id: number;
      units_per_order: number;
    }> = [];

    for (const row of importPreview.rows) {
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

      if (previewAliasSaves[row.row] && canOfferAliasSave(row, selection)) {
        aliasSaves.push({
          ordered_item_number: row.item_number,
          item_id: selection.entity_id,
          units_per_order: unitsValue,
        });
      }
    }

    setLoading(true);
    setMessage("");
    setMissingRows([]);
    sessionStorage.removeItem(PENDING_BATCH_RETRY_KEY);
    try {
      const form = new FormData();
      form.append("file", file);
      if (supplierSelection) {
        form.append("supplier_id", String(supplierSelection.entity_id));
      } else {
        form.append("supplier_name", supplier);
      }
      if (defaultDate.trim()) form.append("default_order_date", defaultDate.trim());
      if (Object.keys(rowOverrides).length > 0) {
        form.append("row_overrides", JSON.stringify(rowOverrides));
      }
      if (aliasSaves.length > 0) {
        form.append("alias_saves", JSON.stringify(aliasSaves));
      }

      const result = await apiSendForm<ImportResult>("/orders/import", form);
      if (result.status === "missing_items") {
        const unresolved = normalizeMissingRows(result.rows, supplier.trim());
        setMissingRows(unresolved);
        try {
          await rememberPendingOrderImport(file);
        } catch {
          // Keep working even if browser storage quota blocks auto-retry cache.
        }
        setMessage(
          `Missing items detected (${result.missing_count}). CSV generated: ${result.missing_csv_path}`
        );
        openMissingResolver(unresolved);
      } else {
        resetImportPreview();
        setMissingRows([]);
        sessionStorage.removeItem(PENDING_MISSING_ITEMS_KEY);
        sessionStorage.removeItem(PENDING_ORDER_IMPORT_KEY);
        sessionStorage.removeItem(PENDING_BATCH_RETRY_KEY);
        const savedAliasCount = result.saved_alias_count ?? 0;
        setMessage(
          savedAliasCount > 0
            ? `Imported ${result.imported_count ?? 0} rows and saved ${savedAliasCount} alias mapping(s).`
            : `Imported ${result.imported_count ?? 0} rows.`
        );
      }
      await Promise.all([mutateOrders(), mutateQuotations()]);
    } catch (error) {
      const messageText = String(error ?? "");
      if (messageText.includes("imports/orders/registered/pdf_files")) {
        setMessage(
          "Import failed: Manual import requires pdf_link to be blank, filename-only, or imports/orders/registered/pdf_files/<supplier>/<file>.pdf. " +
          "For unregistered folder CSV files, use 'Unregistered Folder Batch'."
        );
      } else {
        setMessage(formatActionError("Import failed", error));
      }
    } finally {
      setLoading(false);
    }
  }

  function downloadImportCsv(path: string, fallbackFilename: string) {
    void apiDownload(path, fallbackFilename).catch((error) => {
      setMessage(error instanceof Error ? error.message : String(error));
    });
  }

  async function markArrived(orderId: number) {
    setLoading(true);
    try {
      await apiSend(`/orders/${orderId}/arrival`, { method: "POST", body: JSON.stringify({}) });
      await Promise.all([mutateOrders(), mutateQuotations()]);
    } finally {
      setLoading(false);
    }
  }

  async function deleteOrder(orderId: number) {
    setLoading(true);
    try {
      await apiSend(`/orders/${orderId}`, { method: "DELETE" });
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
  }

  function cancelEditOrder() {
    setEditingOrderId(null);
    setEditingOrderExpectedArrival("");
    setEditingOrderSplitQuantity("");
  }

  async function saveOrderEdit(orderId: number) {
    setLoading(true);
    try {
      const splitQuantity = Number(editingOrderSplitQuantity);
      const hasSplit = editingOrderSplitQuantity.trim().length > 0;
      await apiSend(`/orders/${orderId}`, {
        method: "PUT",
        body: JSON.stringify({
          expected_arrival: editingOrderExpectedArrival.trim() || null,
          split_quantity: hasSplit && Number.isFinite(splitQuantity) ? splitQuantity : null,
        }),
      });
      setMessage(
        hasSplit
          ? `Split order #${orderId} and postponed ${splitQuantity} units to ${editingOrderExpectedArrival || "(no date)"}.`
          : `Updated expected arrival for order #${orderId}.`
      );
      cancelEditOrder();
      await Promise.all([mutateOrders(), mutateQuotations()]);
    } catch (error) {
      setMessage(`Order update failed: ${String(error ?? "")}`);
    } finally {
      setLoading(false);
    }
  }

  function beginEditQuotation(row: Quotation) {
    setEditingQuotationId(row.quotation_id);
    setEditingQuotationPdfLink(row.pdf_link ?? "");
    setEditingQuotationIssueDate(row.issue_date ?? "");
  }

  async function saveQuotationEdit(quotationId: number) {
    setLoading(true);
    try {
      await apiSend(`/quotations/${quotationId}`, {
        method: "PUT",
        body: JSON.stringify({
          issue_date: editingQuotationIssueDate.trim() || null,
          pdf_link: editingQuotationPdfLink.trim() || null,
        }),
      });
      setMessage(`Updated quotation #${quotationId}.`);
      setEditingQuotationId(null);
      await Promise.all([mutateOrders(), mutateQuotations()]);
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
      await Promise.all([mutateOrders(), mutateQuotations()]);
    } catch (error) {
      setMessage(`Quotation delete failed: ${String(error ?? "")}`);
    } finally {
      setLoading(false);
    }
  }



  async function runImportUnregisteredOrders() {
    setLoading(true);
    setMessage("");
    setBatchMissingReports([]);
    setBatchErrorReports([]);
    setBatchWarnings([]);
    setBatchNormalizations([]);
    try {
      const result = await apiSend<ImportBatchResult>("/orders/import-unregistered", {
        method: "POST",
        body: JSON.stringify({
          unregistered_root: unregisteredRoot || null,
          registered_root: registeredRoot || null,
          default_order_date: defaultDate || null,
          continue_on_error: true
        })
      });
      setBatchMissingReports(
        (result.files ?? []).filter((entry) => entry.status === "missing_items")
      );
      setBatchErrorReports(toBatchErrorReports("import", result.files));
      setBatchWarnings(uniqueWarnings(result.warnings ?? []));
      setBatchNormalizations(uniqueNormalizations(result.normalizations ?? []));
      setMessage(
        `Unregistered import batch: status=${result.status}, processed=${result.processed}, succeeded=${result.succeeded}, missing_items=${result.missing_items}, failed=${result.failed}`
      );
      await Promise.all([mutateOrders(), mutateQuotations()]);
    } finally {
      setLoading(false);
    }
  }

  async function runDefaultUnregisteredBatch() {
    setLoading(true);
    setMessage("");
    setBatchMissingReports([]);
    setBatchErrorReports([]);
    setBatchWarnings([]);
    setBatchNormalizations([]);
    try {
      const importResult = await apiSend<ImportBatchResult>("/orders/import-unregistered", {
        method: "POST",
        body: JSON.stringify({
          unregistered_root: null,
          registered_root: null,
          default_order_date: defaultDate || null,
          continue_on_error: true
        })
      });
      setBatchMissingReports(
        (importResult.files ?? []).filter((entry) => entry.status === "missing_items")
      );
      setBatchErrorReports(toBatchErrorReports("import", importResult.files));

      const mergedWarnings = uniqueWarnings(importResult.warnings ?? []);
      const mergedNormalizations = uniqueNormalizations(importResult.normalizations ?? []);
      setBatchWarnings(mergedWarnings);
      setBatchNormalizations(mergedNormalizations);
      setMessage(
        `Unregistered batch complete: import(status=${importResult.status}, processed=${importResult.processed}, succeeded=${importResult.succeeded}, missing_items=${importResult.missing_items}, failed=${importResult.failed})`
      );
      await Promise.all([mutateOrders(), mutateQuotations()]);
    } finally {
      setLoading(false);
    }
  }

  function openBatchEntryResolver(entry: UnregisteredFileReport) {
    const fallbackSupplier = (entry.supplier ?? supplier).trim() || "UNKNOWN";
    const unresolved = normalizeMissingRows(entry.missing_rows, fallbackSupplier);
    sessionStorage.removeItem(PENDING_ORDER_IMPORT_KEY);
    const retryContext: PendingBatchRetry = {
      csv_path: entry.file,
      unregistered_root: unregisteredRoot || "",
      registered_root: registeredRoot || "",
      default_order_date: defaultDate || "",
    };
    sessionStorage.setItem(PENDING_BATCH_RETRY_KEY, JSON.stringify(retryContext));
    openMissingResolver(unresolved);
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Orders</h1>
        <p className="mt-1 text-sm text-slate-600">
          CSV order import, missing-item workflow, and arrival processing.
        </p>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Import Orders CSV</h2>
        <div className="mb-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
          <p className="font-semibold text-slate-900">CSV Format</p>
          <p className="mt-1">
            Required columns: <code>item_number</code>, <code>quantity</code>,{" "}
            <code>quotation_number</code>, <code>issue_date</code>
          </p>
          <p>
            Optional columns: <code>order_date</code>, <code>expected_arrival</code>,{" "}
            <code>pdf_link</code>
          </p>
          <p className="mt-1">
            For manual import, <code>pdf_link</code> should be{" "}
            <code>{"imports/orders/registered/pdf_files/<supplier>/<file>.pdf"}</code> or blank.
          </p>
          <p>
            If you provide only a filename like <code>Q-2026-001.pdf</code>, it is auto-normalized
            to the canonical registered path for the selected supplier.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              className="button-subtle"
              type="button"
              onClick={() => downloadImportCsv("/orders/import-template", "orders_import_template.csv")}
            >
              Download Template CSV
            </button>
            <button
              className="button-subtle"
              type="button"
              onClick={() => {
                const query = supplier.trim()
                  ? `?supplier_name=${encodeURIComponent(supplier.trim())}`
                  : "";
                downloadImportCsv(
                  `/orders/import-reference${query}`,
                  "orders_import_reference.csv"
                );
              }}
            >
              Download Reference CSV
            </button>
          </div>
        </div>
        <form className="grid gap-3 md:grid-cols-4" onSubmit={previewImport}>
          <CatalogPicker
            allowedTypes={["supplier"]}
            onChange={(value) => {
              setSupplierSelection(value);
              setSupplier(value?.value_text ?? "");
              resetImportPreview();
            }}
            onQueryChange={(value) => {
              setSupplier(value);
              if (supplierSelection && value !== supplierSelection.value_text) {
                setSupplierSelection(null);
              }
              resetImportPreview();
            }}
            placeholder="Type or search supplier"
            recentKey="orders-import-supplier"
            seedQuery={supplier}
            value={supplierSelection}
          />
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
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              resetImportPreview();
            }}
            required
          />
          <button className="button" disabled={loading} type="submit">
            Preview Import
          </button>
        </form>
        {message && <p className="mt-3 text-sm text-signal">{message}</p>}
        {importPreview && (
          <div className="mt-4 space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-900">Import Preview</p>
                <p className="mt-1 text-xs text-slate-600">
                  Supplier context:{" "}
                  <strong>{importPreview.supplier.supplier_name}</strong>
                  {importPreview.supplier.exists ? " (existing supplier)" : " (new supplier on commit)"}
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
                  onClick={() => void openPreviewMissingResolver()}
                >
                  Open Missing Resolver In Items
                </button>
                <p className="self-center text-xs text-slate-500">
                  Use this only when the required canonical item is not in the catalog yet.
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
                      <tr key={row.row} className="border-b border-slate-100 align-top">
                        <td className="px-2 py-3 font-semibold text-slate-700">#{row.row}</td>
                        <td className="px-2 py-3">
                          <div className="space-y-1">
                            <p className="font-semibold text-slate-900">{row.item_number}</p>
                            <p className="text-xs text-slate-500">
                              qty {row.quantity} | quotation {row.quotation_number}
                            </p>
                            <p className="text-xs text-slate-500">
                              order {row.order_date}
                              {row.expected_arrival ? ` | eta ${row.expected_arrival}` : ""}
                            </p>
                            {row.pdf_link && (
                              <p className="text-xs text-slate-500">{row.pdf_link}</p>
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
                                  [row.row]: value,
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
                                    [row.row]: event.target.value,
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
                                  checked={previewAliasSaves[row.row] ?? false}
                                  onChange={(event) =>
                                    setPreviewAliasSaves((prev) => ({
                                      ...prev,
                                      [row.row]: event.target.checked,
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
            <button
              className="button-subtle mb-2"
              type="button"
              onClick={() => openMissingResolver(missingRows)}
            >
              Open Resolver In Items
            </button>
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
                      <td className="px-2 py-2">{row.supplier ?? supplier}</td>
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
        <h2 className="mb-3 font-display text-lg font-semibold">Unregistered Folder Batch</h2>
        <p className="mb-3 text-sm text-slate-600">
          Run the default batch for canonical folders, or open advanced controls for explicit roots.
        </p>
        <p className="mb-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
          Canonical layout:
          {" "}
          <code>{"imports/orders/unregistered/csv_files/<supplier>/*.csv"}</code>
          {" "}
          and
          {" "}
          <code>{"imports/orders/unregistered/pdf_files/<supplier>/*"}</code>
          .
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="button" onClick={runDefaultUnregisteredBatch} disabled={loading}>
            Run Unregistered Batch (Default Roots)
          </button>
          <button
            className="button-subtle"
            type="button"
            onClick={() => setShowAdvancedBatch((prev) => !prev)}
            disabled={loading}
          >
            {showAdvancedBatch ? "Hide Advanced Controls" : "Show Advanced Controls"}
          </button>
        </div>
        {showAdvancedBatch && (
          <div className="mt-3 space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div className="grid gap-3 md:grid-cols-2">
              <input
                className="input"
                placeholder="Unregistered root (optional absolute path)"
                value={unregisteredRoot}
                onChange={(e) => setUnregisteredRoot(e.target.value)}
              />
              <input
                className="input"
                placeholder="Registered root (optional absolute path)"
                value={registeredRoot}
                onChange={(e) => setRegisteredRoot(e.target.value)}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="button-subtle" onClick={runImportUnregisteredOrders} disabled={loading}>
                Import Unregistered Orders
              </button>
            </div>
          </div>
        )}
        {(batchWarnings.length > 0 || batchNormalizations.length > 0) && (
          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
            {batchWarnings.length > 0 && (
              <>
                <p className="font-semibold text-slate-900">Batch Warnings</p>
                <ul className="mt-1 list-disc pl-5">
                  {batchWarnings.map((warning, index) => (
                    <li key={`${warning}-${index}`}>{warning}</li>
                  ))}
                </ul>
              </>
            )}
            {batchNormalizations.length > 0 && (
              <>
                <p className="mt-3 font-semibold text-slate-900">Path Normalizations</p>
                <div className="mt-2 overflow-x-auto">
                  <table className="min-w-[520px] text-xs">
                    <thead>
                      <tr className="border-b border-slate-200 text-left text-slate-600">
                        <th className="px-2 py-1">From</th>
                        <th className="px-2 py-1">To</th>
                        <th className="px-2 py-1">Context</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batchNormalizations.map((entry, index) => (
                        <tr key={`${entry.from}-${entry.to}-${index}`} className="border-b border-slate-100">
                          <td className="px-2 py-1">{entry.from}</td>
                          <td className="px-2 py-1">{entry.to}</td>
                          <td className="px-2 py-1">{entry.file ?? entry.quotation_id ?? "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}
        {batchErrorReports.length > 0 && (
          <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3">
            <p className="mb-2 text-sm font-semibold text-red-900">Batch Errors</p>
            <div className="overflow-x-auto">
              <table className="min-w-[760px] text-sm">
                <thead>
                  <tr className="border-b border-red-200 text-left text-red-800">
                    <th className="px-2 py-2">Phase</th>
                    <th className="px-2 py-2">Supplier</th>
                    <th className="px-2 py-2">File</th>
                    <th className="px-2 py-2">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {batchErrorReports.map((entry, idx) => (
                    <tr key={`${entry.phase}-${entry.file}-${idx}`} className="border-b border-red-100">
                      <td className="px-2 py-2">{entry.phase}</td>
                      <td className="px-2 py-2">{entry.supplier ?? "-"}</td>
                      <td className="px-2 py-2">{entry.file}</td>
                      <td className="px-2 py-2">{entry.error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {batchMissingReports.length > 0 && (
          <div className="mt-3 space-y-3">
            {batchMissingReports.map((entry, idx) => (
              <div key={`${entry.file}-${idx}`} className="rounded-xl border border-amber-200 bg-amber-50 p-3">
                <p className="text-sm font-semibold text-amber-900">
                  Missing items: {entry.file}
                </p>
                <p className="mt-1 text-xs text-amber-800">
                  Generated CSV: {entry.missing_csv_path}
                </p>
                <button
                  className="button-subtle mt-2"
                  type="button"
                  onClick={() => openBatchEntryResolver(entry)}
                >
                  Open Resolver In Items
                </button>
                {entry.missing_rows && entry.missing_rows.length > 0 && (
                  <div className="mt-2 overflow-x-auto">
                    <table className="min-w-[420px] text-sm">
                      <thead>
                        <tr className="border-b border-amber-200 text-left text-amber-800">
                          <th className="px-2 py-2">CSV Row</th>
                          <th className="px-2 py-2">Item Number</th>
                        </tr>
                      </thead>
                      <tbody>
                        {entry.missing_rows.map((row, rowIndex) => (
                          <tr
                            key={`${entry.file}-${row.item_number}-${rowIndex}`}
                            className="border-b border-amber-100"
                          >
                            <td className="px-2 py-2">{row.row ?? "-"}</td>
                            <td className="px-2 py-2 font-semibold">{row.item_number}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-display text-lg font-semibold">Order List</h2>
          <button
            type="button"
            className="button-subtle"
            onClick={() => setIsOrderListExpanded((prev) => !prev)}
            aria-expanded={isOrderListExpanded}
          >
            {isOrderListExpanded ? "Collapse" : "Expand"}
          </button>
        </div>
        {isOrderListExpanded && (
          <>
            <div className="mb-3 grid gap-2 md:grid-cols-2">
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
            {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
            {error && <p className="text-sm text-red-600">{String(error)}</p>}
            {ordersData && (
              <>
                <p className="mb-2 text-xs text-slate-500">Showing {filteredSortedOrders.length} / {ordersData.length} orders</p>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-left text-slate-500">
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("order_id")}>Order {sortIndicator("order_id")}</button></th>
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("supplier_name")}>Supplier {sortIndicator("supplier_name")}</button></th>
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("project_name")}>Project {sortIndicator("project_name")}</button></th>
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("canonical_item_number")}>Item {sortIndicator("canonical_item_number")}</button></th>
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("order_amount")}>Qty {sortIndicator("order_amount")}</button></th>
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("expected_arrival")}>Expected {sortIndicator("expected_arrival")}</button></th>
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("status")}>Status {sortIndicator("status")}</button></th>
                        <th className="px-2 py-2">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSortedOrders.map((row) => (
                        <tr key={row.order_id} className="border-b border-slate-100">
                          <td className="px-2 py-2">#{row.order_id}</td>
                          <td className="px-2 py-2">{row.supplier_name}</td>
                          <td className="px-2 py-2">{row.project_name ?? "-"}</td>
                          <td className="px-2 py-2 font-semibold">{row.canonical_item_number}</td>
                          <td className="px-2 py-2">{row.order_amount}</td>
                          <td className="px-2 py-2">
                            {editingOrderId === row.order_id ? (
                              <div className="space-y-2">
                                <input
                                  className="input"
                                  type="date"
                                  value={editingOrderExpectedArrival}
                                  onChange={(event) => setEditingOrderExpectedArrival(event.target.value)}
                                />
                                <input
                                  className="input"
                                  type="number"
                                  min={1}
                                  max={row.order_amount - 1}
                                  placeholder={`Split qty (1-${row.order_amount - 1})`}
                                  value={editingOrderSplitQuantity}
                                  onChange={(event) => setEditingOrderSplitQuantity(event.target.value)}
                                />
                              </div>
                            ) : (
                              row.expected_arrival ?? "-"
                            )}
                          </td>
                          <td className="px-2 py-2">{row.status}</td>
                          <td className="px-2 py-2">
                            <div className="flex gap-2">
                              {row.status === "Ordered" ? (
                                <>
                                  <button
                                    className="button-subtle"
                                    onClick={() => markArrived(row.order_id)}
                                    disabled={loading}
                                  >
                                    Mark Arrived
                                  </button>
                                  {editingOrderId === row.order_id ? (
                                    <>
                                      <button
                                        className="button-subtle"
                                        onClick={() => saveOrderEdit(row.order_id)}
                                        disabled={loading}
                                      >
                                        Save ETA / Split
                                      </button>
                                      <button className="button-subtle" onClick={cancelEditOrder} disabled={loading}>
                                        Cancel
                                      </button>
                                    </>
                                  ) : (
                                    <button
                                      className="button-subtle"
                                      onClick={() => beginEditOrder(row)}
                                      disabled={loading}
                                    >
                                      Edit ETA
                                    </button>
                                  )}
                                </>
                              ) : (
                                <span className="text-slate-400">-</span>
                              )}
                              <button
                                className="button-subtle"
                                onClick={() => openOrderDetails(row.order_id)}
                                disabled={loading}
                              >
                                Order Details
                              </button>
                              <button
                                className="button-subtle"
                                onClick={() => deleteOrder(row.order_id)}
                                disabled={loading || row.status === "Arrived"}
                                title={row.status === "Arrived" ? "Arrived orders cannot be deleted" : "Delete this order"}
                              >
                                Delete
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}
      </section>

      <section className="panel p-4" ref={orderDetailsRef}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-display text-lg font-semibold">Order Details</h2>
          {selectedOrder && (
            <button type="button" className="button-subtle" onClick={() => setSelectedOrderId(null)}>
              Clear
            </button>
          )}
        </div>
        {!selectedOrder && (
          <p className="text-sm text-slate-500">
            Select <strong>Order Details</strong> from any order row to review the selected order, item metadata, and
            same-item purchasing history. Use <strong>Edit ETA</strong> to change the entire order date, or enter{" "}
            <strong>Split qty</strong> to postpone only part of an open order.
          </p>
        )}
        {selectedOrder && (
          <div className="space-y-3 text-sm">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p>
                <strong>Order:</strong> #{selectedOrder.order_id}
              </p>
              <p>
                <strong>Item:</strong> {selectedOrder.canonical_item_number}
              </p>
              <p>
                <strong>Supplier:</strong> {selectedOrder.supplier_name} / <strong>Quotation:</strong>{" "}
                {selectedOrder.quotation_number}
              </p>
              <p>
                <strong>Expected arrival:</strong> {selectedOrder.expected_arrival ?? "-"}
              </p>
              <p>
                <strong>Project:</strong> {selectedOrder.project_name ?? "-"} / <strong>Status:</strong>{" "}
                {selectedOrder.status}
              </p>
              <p>
                <strong>Category:</strong> {selectedOrderItem?.category ?? "-"} / <strong>Description:</strong>{" "}
                {selectedOrderItem?.description ?? "-"}
              </p>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Same-item orders</p>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-slate-500">
                      <th className="px-2 py-2">Order</th>
                      <th className="px-2 py-2">Supplier</th>
                      <th className="px-2 py-2">Quotation</th>
                      <th className="px-2 py-2">Qty</th>
                      <th className="px-2 py-2">Expected</th>
                      <th className="px-2 py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sameItemOrders.map((row) => (
                      <tr key={`related-${row.order_id}`} className="border-b border-slate-100">
                        <td className="px-2 py-2">#{row.order_id}</td>
                        <td className="px-2 py-2">{row.supplier_name}</td>
                        <td className="px-2 py-2">{row.quotation_number}</td>
                        <td className="px-2 py-2">{row.order_amount}</td>
                        <td className="px-2 py-2">{row.expected_arrival ?? "-"}</td>
                        <td className="px-2 py-2">{row.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="space-y-1">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Same-item quotations</p>
              {sameItemQuotations.length ? (
                sameItemQuotations.map((row) => (
                  <p key={`q-${row.quotation_id}`} className="text-sm text-slate-700">
                    #{row.quotation_id} {row.quotation_number} ({row.supplier_name}) / issue: {row.issue_date ?? "-"}
                    {row.pdf_link ? ` / ${row.pdf_link}` : ""}
                  </p>
                ))
              ) : (
                <p className="text-sm text-slate-500">No related quotation metadata loaded.</p>
              )}
            </div>
          </div>
        )}
      </section>

      <section className="panel p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-display text-lg font-semibold">Imported Quotations</h2>
          <button
            type="button"
            className="button-subtle"
            onClick={() => setIsImportedQuotationsExpanded((prev) => !prev)}
            aria-expanded={isImportedQuotationsExpanded}
          >
            {isImportedQuotationsExpanded ? "Collapse" : "Expand"}
          </button>
        </div>
        {isImportedQuotationsExpanded && (
          <>
            <div className="mb-3 grid gap-2 md:grid-cols-2">
              <input
                className="input"
                value={quotationNumberSearch}
                onChange={(event) => setQuotationNumberSearch(event.target.value)}
                placeholder="Search by quotation number"
              />
              <input
                className="input"
                value={quotationFilter}
                onChange={(event) => setQuotationFilter(event.target.value)}
                placeholder="Filter by supplier, issue date, or PDF link"
              />
            </div>
            {quotationsLoading && <p className="text-sm text-slate-500">Loading...</p>}
            {quotationsError && <p className="text-sm text-red-600">{String(quotationsError)}</p>}
            {quotationsData && (
              <>
                <p className="mb-2 text-xs text-slate-500">Showing {filteredSortedQuotations.length} / {quotationsData.length} quotations</p>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-left text-slate-500">
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleQuotationSort("quotation_id")}>ID {quotationSortIndicator("quotation_id")}</button></th>
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleQuotationSort("supplier_name")}>Supplier {quotationSortIndicator("supplier_name")}</button></th>
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleQuotationSort("quotation_number")}>Quotation # {quotationSortIndicator("quotation_number")}</button></th>
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleQuotationSort("issue_date")}>Issue Date {quotationSortIndicator("issue_date")}</button></th>
                        <th className="px-2 py-2"><button type="button" onClick={() => toggleQuotationSort("pdf_link")}>PDF Link {quotationSortIndicator("pdf_link")}</button></th>
                        <th className="px-2 py-2">Orders</th>
                        <th className="px-2 py-2">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSortedQuotations.map((row) => (
                        <tr key={row.quotation_id} className="border-b border-slate-100">
                          <td className="px-2 py-2">#{row.quotation_id}</td>
                          <td className="px-2 py-2">{row.supplier_name}</td>
                          <td className="px-2 py-2 font-semibold">{row.quotation_number}</td>
                          <td className="px-2 py-2">
                            {editingQuotationId === row.quotation_id ? (
                              <input
                                className="input"
                                value={editingQuotationIssueDate}
                                onChange={(event) => setEditingQuotationIssueDate(event.target.value)}
                                placeholder="YYYY-MM-DD"
                              />
                            ) : (
                              row.issue_date ?? "-"
                            )}
                          </td>
                          <td className="px-2 py-2 text-slate-600">
                            {editingQuotationId === row.quotation_id ? (
                              <input
                                className="input"
                                value={editingQuotationPdfLink}
                                onChange={(event) => setEditingQuotationPdfLink(event.target.value)}
                                placeholder="imports/orders/registered/pdf_files/<supplier>/<file>.pdf"
                              />
                            ) : (
                              row.pdf_link ?? "-"
                            )}
                          </td>
                          <td className="px-2 py-2">{orderCountByQuotationId.get(row.quotation_id) ?? 0}</td>
                          <td className="px-2 py-2">
                            <div className="flex gap-2">
                              <button className="button-subtle" onClick={() => openQuotationDetails(row.quotation_id)} disabled={loading}>View Orders</button>
                              {editingQuotationId === row.quotation_id ? (
                                <>
                                  <button className="button-subtle" onClick={() => saveQuotationEdit(row.quotation_id)} disabled={loading}>Save</button>
                                  <button className="button-subtle" onClick={() => setEditingQuotationId(null)} disabled={loading}>Cancel</button>
                                </>
                              ) : (
                                <button className="button-subtle" onClick={() => beginEditQuotation(row)} disabled={loading}>Edit</button>
                              )}
                              <button className="button-subtle" onClick={() => deleteQuotation(row.quotation_id)} disabled={loading}>Delete</button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}
      </section>

      <section className="panel p-4" ref={quotationDetailsRef}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-display text-lg font-semibold">Quotation Details</h2>
          {selectedQuotation && (
            <button type="button" className="button-subtle" onClick={() => setSelectedQuotationId(null)}>
              Clear
            </button>
          )}
        </div>
        {!selectedQuotation && (
          <p className="text-sm text-slate-500">
            Select <strong>View Orders</strong> from any quotation row to review the quotation metadata and every order
            linked to that quotation.
          </p>
        )}
        {selectedQuotation && (
          <div className="space-y-3 text-sm">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p>
                <strong>Quotation:</strong> #{selectedQuotation.quotation_id} {selectedQuotation.quotation_number}
              </p>
              <p>
                <strong>Supplier:</strong> {selectedQuotation.supplier_name}
              </p>
              <p>
                <strong>Issue date:</strong> {selectedQuotation.issue_date ?? "-"}
              </p>
              <p>
                <strong>PDF link:</strong> {selectedQuotation.pdf_link ?? "-"}
              </p>
              <p>
                <strong>Linked orders:</strong> {quotationOrders.length}
              </p>
            </div>

            {quotationOrders.length ? (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-slate-500">
                      <th className="px-2 py-2">Order</th>
                      <th className="px-2 py-2">Project</th>
                      <th className="px-2 py-2">Supplier</th>
                      <th className="px-2 py-2">Item</th>
                      <th className="px-2 py-2">Qty</th>
                      <th className="px-2 py-2">Expected</th>
                      <th className="px-2 py-2">Status</th>
                      <th className="px-2 py-2">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quotationOrders.map((row) => (
                      <tr key={`quotation-${row.order_id}`} className="border-b border-slate-100">
                        <td className="px-2 py-2">#{row.order_id}</td>
                        <td className="px-2 py-2">{row.project_name ?? "-"}</td>
                        <td className="px-2 py-2">{row.supplier_name}</td>
                        <td className="px-2 py-2 font-semibold">{row.canonical_item_number}</td>
                        <td className="px-2 py-2">{row.order_amount}</td>
                        <td className="px-2 py-2">{row.expected_arrival ?? "-"}</td>
                        <td className="px-2 py-2">{row.status}</td>
                        <td className="px-2 py-2">
                          <button className="button-subtle" type="button" onClick={() => openOrderDetails(row.order_id)}>
                            Order Details
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-slate-500">No linked orders found for this quotation.</p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
