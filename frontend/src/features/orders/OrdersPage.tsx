import { FormEvent, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { apiDownload, apiGet, apiGetAllPages, apiGetWithPagination, apiSend, apiSendForm } from "@/lib/api";
import { formatActionError, resolvePreviewSelection } from "@/lib/previewState";
import type {
  CatalogSearchResult,
  Item,
  MissingItemResolverRow,
  Order,
  ProjectRow,
  PurchaseOrder,
  Quotation,
} from "@/lib/types";
import type {
  GeneratedArtifact,
  ImportResult,
  LockedPurchaseOrderPreview,
  OrderImportPreview,
  OrderImportPreviewRow,
  OrderSplitUpdateResult,
} from "@/features/orders/types";
import {
  normalizeMissingRows,
  previewMatchToCatalogResult,
  orderPreviewRowKey,
  purchaseOrderPreviewKey,
  mergeOrderImportPreviews,
  normalizeCatalogValue,
} from "@/features/orders/utils";
import { OrderImportForm } from "@/features/orders/components/OrderImportForm";
import { OrderLineTable } from "@/features/orders/components/OrderLineTable";
import { QuotationTable } from "@/features/orders/components/QuotationTable";
import { PurchaseOrderTable } from "@/features/orders/components/PurchaseOrderTable";

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
  const [previewUnlocks, setPreviewUnlocks] = useState<Record<string, boolean>>({});
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
  const [editingPurchaseOrderNumber, setEditingPurchaseOrderNumber] = useState("");
  const [editingPurchaseOrderDocumentUrl, setEditingPurchaseOrderDocumentUrl] = useState("");
  const [editingPurchaseOrderImportLocked, setEditingPurchaseOrderImportLocked] = useState(true);
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
        row.purchase_order_number ?? "",
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
    setPreviewUnlocks({});
  }

  async function refreshOrderViews() {
    await Promise.all([mutateOrders(), mutateQuotations(), mutatePurchaseOrders()]);
  }

  function applyImportPreview(preview: OrderImportPreview) {
    const nextSelections: Record<string, CatalogSearchResult | null> = {};
    const nextUnits: Record<string, string> = {};
    const nextAliasSaves: Record<string, boolean> = {};
    const nextUnlocks: Record<string, boolean> = {};
    for (const row of preview.rows) {
      const key = orderPreviewRowKey(row);
      nextSelections[key] = row.suggested_match
        ? previewMatchToCatalogResult(row.suggested_match)
        : null;
      nextUnits[key] = String(row.suggested_match?.units_per_order ?? 1);
      nextAliasSaves[key] = false;
    }
    for (const locked of preview.locked_purchase_orders ?? []) {
      nextUnlocks[purchaseOrderPreviewKey(locked)] = false;
    }
    setImportPreview(preview);
    setPreviewSelections(nextSelections);
    setPreviewUnits(nextUnits);
    setPreviewAliasSaves(nextAliasSaves);
    setPreviewUnlocks(nextUnlocks);
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

  function lockedPurchaseOrdersForSource(sourceIndex: number): LockedPurchaseOrderPreview[] {
    if (!importPreview) return [];
    const keys = new Set(
      importPreview.rows
        .filter((entry) => entry.source_index === sourceIndex)
        .map((row) =>
          purchaseOrderPreviewKey({
            supplier_id: Number(row.supplier_id ?? 0),
            purchase_order_number: row.purchase_order_number,
          })
        )
    );
    return (importPreview.locked_purchase_orders ?? []).filter((locked) =>
      keys.has(purchaseOrderPreviewKey(locked))
    );
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
    const unresolvedLocks = (importPreview.locked_purchase_orders ?? []).filter(
      (locked) => !previewUnlocks[purchaseOrderPreviewKey(locked)]
    );
    if (unresolvedLocks.length > 0) {
      setMessage(
        `Unlock locked purchase orders before import: ${unresolvedLocks
          .map((locked) => locked.purchase_order_number)
          .join(", ")}`
      );
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
        const unlockPurchaseOrders = lockedPurchaseOrdersForSource(sourceIndex)
          .filter((locked) => previewUnlocks[purchaseOrderPreviewKey(locked)])
          .map((locked) => ({
            supplier_id: locked.supplier_id,
            supplier_name: locked.supplier_name,
            purchase_order_number: locked.purchase_order_number,
          }));
        if (unlockPurchaseOrders.length > 0) {
          form.append("unlock_purchase_orders", JSON.stringify(unlockPurchaseOrders));
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
      await refreshOrderViews();
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
      await refreshOrderViews();
    } finally {
      setLoading(false);
    }
  }

  async function deleteOrder(orderId: number) {
    setLoading(true);
    try {
      await apiSend(`/purchase-order-lines/${orderId}`, { method: "DELETE" });
      setMessage(`Deleted order #${orderId}.`);
      await refreshOrderViews();
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
      await refreshOrderViews();
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
      await refreshOrderViews();
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
      await refreshOrderViews();
    } catch (error) {
      setMessage(`Quotation delete failed: ${String(error ?? "")}`);
    } finally {
      setLoading(false);
    }
  }

  function beginEditPurchaseOrder(row: PurchaseOrder) {
    setEditingPurchaseOrderId(row.purchase_order_id);
    setEditingPurchaseOrderNumber(row.purchase_order_number ?? "");
    setEditingPurchaseOrderDocumentUrl(row.purchase_order_document_url ?? "");
    setEditingPurchaseOrderImportLocked(row.import_locked ?? true);
  }

  async function savePurchaseOrderEdit(purchaseOrderId: number) {
    setLoading(true);
    try {
      await apiSend(`/purchase-orders/${purchaseOrderId}`, {
        method: "PUT",
        body: JSON.stringify({
          purchase_order_number: editingPurchaseOrderNumber.trim(),
          purchase_order_document_url: editingPurchaseOrderDocumentUrl.trim() || null,
          import_locked: editingPurchaseOrderImportLocked,
        }),
      });
      setMessage(`Updated purchase order #${purchaseOrderId}.`);
      setEditingPurchaseOrderId(null);
      await refreshOrderViews();
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
      await refreshOrderViews();
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

      <OrderImportForm
        files={files}
        setFiles={setFiles}
        defaultDate={defaultDate}
        setDefaultDate={setDefaultDate}
        loading={loading}
        message={message}
        latestGeneratedArtifact={latestGeneratedArtifact}
        missingRows={missingRows}
        generatedArtifacts={generatedArtifacts}
        onPreviewImport={previewImport}
        onResetImportPreview={resetImportPreview}
        onDownloadImportCsv={downloadImportCsv}
        onDownloadGeneratedArtifact={downloadGeneratedArtifact}
        importPreview={importPreview}
        previewSelections={previewSelections}
        previewUnits={previewUnits}
        previewAliasSaves={previewAliasSaves}
        previewUnlocks={previewUnlocks}
        setPreviewSelections={setPreviewSelections}
        setPreviewUnits={setPreviewUnits}
        setPreviewAliasSaves={setPreviewAliasSaves}
        setPreviewUnlocks={setPreviewUnlocks}
        selectedPreviewMatch={selectedPreviewMatch}
        previewUnitsValue={previewUnitsValue}
        canOfferAliasSave={canOfferAliasSave}
        unresolvedPreviewRows={unresolvedPreviewRows}
        onConfirmImportPreview={() => void confirmImportPreview()}
      />

      <OrderLineTable
        ordersData={ordersData}
        filteredSortedOrders={filteredSortedOrders}
        sameItemOrders={sameItemOrders}
        selectedOrder={selectedOrder}
        selectedOrderItem={selectedOrderItem}
        isLoading={isLoading}
        error={error}
        loading={loading}
        selectedOrderId={selectedOrderId}
        editingOrderId={editingOrderId}
        editingOrderExpectedArrival={editingOrderExpectedArrival}
        editingOrderSplitQuantity={editingOrderSplitQuantity}
        editingOrderProjectId={editingOrderProjectId}
        projectsData={projectsData}
        orderPrimarySearch={orderPrimarySearch}
        orderFilter={orderFilter}
        sortKey={sortKey}
        sortDirection={sortDirection}
        orderDetailsRef={orderDetailsRef}
        setOrderPrimarySearch={setOrderPrimarySearch}
        setOrderFilter={setOrderFilter}
        setSelectedOrderId={setSelectedOrderId}
        setEditingOrderExpectedArrival={setEditingOrderExpectedArrival}
        setEditingOrderSplitQuantity={setEditingOrderSplitQuantity}
        setEditingOrderProjectId={setEditingOrderProjectId}
        openOrderDetails={openOrderDetails}
        openReservationPrefill={openReservationPrefill}
        toggleSort={toggleSort}
        sortIndicator={sortIndicator}
        markArrived={(orderId) => void markArrived(orderId)}
        deleteOrder={(orderId) => void deleteOrder(orderId)}
        beginEditOrder={beginEditOrder}
        cancelEditOrder={cancelEditOrder}
        saveOrderEdit={(orderId) => void saveOrderEdit(orderId)}
      />

      <section className="grid gap-4 xl:grid-cols-2 xl:items-start">
        <QuotationTable
          quotationsData={quotationsData}
          filteredSortedQuotations={filteredSortedQuotations}
          quotationOrders={quotationOrders}
          selectedQuotation={selectedQuotation}
          quotationsLoading={quotationsLoading}
          quotationsError={quotationsError}
          loading={loading}
          selectedQuotationId={selectedQuotationId}
          editingQuotationId={editingQuotationId}
          editingQuotationDocumentUrl={editingQuotationDocumentUrl}
          editingQuotationIssueDate={editingQuotationIssueDate}
          quotationNumberSearch={quotationNumberSearch}
          quotationFilter={quotationFilter}
          orderCountByQuotationId={orderCountByQuotationId}
          quotationDetailsRef={quotationDetailsRef}
          setQuotationNumberSearch={setQuotationNumberSearch}
          setQuotationFilter={setQuotationFilter}
          setSelectedQuotationId={setSelectedQuotationId}
          setEditingQuotationId={setEditingQuotationId}
          setEditingQuotationDocumentUrl={setEditingQuotationDocumentUrl}
          setEditingQuotationIssueDate={setEditingQuotationIssueDate}
          openQuotationDetails={openQuotationDetails}
          beginEditQuotation={beginEditQuotation}
          saveQuotationEdit={(id) => void saveQuotationEdit(id)}
          deleteQuotation={(id) => void deleteQuotation(id)}
        />

        <PurchaseOrderTable
          purchaseOrdersData={purchaseOrdersData}
          filteredPurchaseOrders={filteredPurchaseOrders}
          purchaseOrderLines={purchaseOrderLines}
          purchaseOrderQuotations={purchaseOrderQuotations}
          selectedPurchaseOrder={selectedPurchaseOrder}
          purchaseOrdersLoading={purchaseOrdersLoading}
          purchaseOrdersError={purchaseOrdersError}
          loading={loading}
          selectedPurchaseOrderId={selectedPurchaseOrderId}
          editingPurchaseOrderId={editingPurchaseOrderId}
          editingPurchaseOrderNumber={editingPurchaseOrderNumber}
          editingPurchaseOrderDocumentUrl={editingPurchaseOrderDocumentUrl}
          editingPurchaseOrderImportLocked={editingPurchaseOrderImportLocked}
          purchaseOrderSearch={purchaseOrderSearch}
          purchaseOrderDetailsRef={purchaseOrderDetailsRef}
          setPurchaseOrderSearch={setPurchaseOrderSearch}
          setSelectedPurchaseOrderId={setSelectedPurchaseOrderId}
          setEditingPurchaseOrderId={setEditingPurchaseOrderId}
          setEditingPurchaseOrderNumber={setEditingPurchaseOrderNumber}
          setEditingPurchaseOrderDocumentUrl={setEditingPurchaseOrderDocumentUrl}
          setEditingPurchaseOrderImportLocked={setEditingPurchaseOrderImportLocked}
          openPurchaseOrderDetails={openPurchaseOrderDetails}
          openOrderDetails={openOrderDetails}
          beginEditPurchaseOrder={beginEditPurchaseOrder}
          savePurchaseOrderEdit={(id) => void savePurchaseOrderEdit(id)}
          deletePurchaseOrder={(id) => void deletePurchaseOrder(id)}
        />
      </section>
    </div>
  );
}
