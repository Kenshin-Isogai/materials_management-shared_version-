import { FormEvent, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import useSWR from "swr";
import { apiGet, apiGetWithPagination, apiSend, apiSendForm } from "../lib/api";
import type { Item, MissingItemResolverRow } from "../lib/types";

type ItemRowType = "item" | "alias";

type ItemEntryRow = {
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

type ItemImportRow = {
  row: number;
  status: "created" | "duplicate" | "error";
  entry_type?: ItemRowType;
  item_id?: number;
  item_number?: string;
  supplier?: string;
  canonical_item_number?: string;
  units_per_order?: number;
  error?: string;
};

type ItemImportResult = {
  status: string;
  processed: number;
  created_count: number;
  duplicate_count: number;
  failed_count: number;
  import_job_id?: number;
  rows: ItemImportRow[];
};

type ItemImportJobSummary = {
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

type ItemImportJobEffect = {
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

type ItemImportJobDetail = {
  job: ItemImportJobSummary;
  effects: ItemImportJobEffect[];
};

type ItemEditDraft = {
  item_number: string;
  manufacturer_name: string;
  category: string;
  url: string;
  description: string;
};

type MetadataBulkRow = {
  item_id: string;
  category: string;
  url: string;
  description: string;
};

type MetadataBulkResultRow = {
  row: number;
  status: "updated" | "error";
  item_id: number;
  item_number?: string;
  error?: string;
  code?: string;
};

type MetadataBulkResult = {
  status: string;
  processed: number;
  updated_count: number;
  failed_count: number;
  rows: MetadataBulkResultRow[];
};

type MissingResolverRow = {
  row?: number;
  supplier: string;
  item_number: string;
  resolution_type: "new_item" | "alias";
  category: string;
  url: string;
  description: string;
  canonical_item_number: string;
  units_per_order: string;
};

type RegisterMissingResult = {
  created_items: number;
  created_aliases: number;
};

type ItemFlowEvent = {
  event_at: string;
  delta: number;
  quantity: number;
  direction: "increase" | "decrease";
  source_type: string;
  source_ref: string;
  reason: string;
  note: string | null;
};

type ItemFlowTimeline = {
  item_id: number;
  item_number: string;
  manufacturer_name: string;
  current_stock: number;
  events: ItemFlowEvent[];
};

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

type OrderImportResult = {
  status: string;
  imported_count?: number;
  missing_count?: number;
  missing_csv_path?: string;
  rows?: MissingItemResolverRow[];
};

type BatchRetryResult = {
  status: string;
  file?: string;
  supplier?: string;
  imported_count?: number;
  moved_to?: string;
  missing_count?: number;
  missing_csv_path?: string;
  missing_rows?: MissingItemResolverRow[];
  error?: string;
};

const blankRow = (): ItemEntryRow => ({
  row_type: "item",
  item_number: "",
  manufacturer_name: "UNKNOWN",
  supplier: "",
  canonical_item_number: "",
  units_per_order: "1",
  category: "",
  url: "",
  description: ""
});

const blankMetadataRow = (): MetadataBulkRow => ({
  item_id: "",
  category: "",
  url: "",
  description: "",
});

function toMissingResolverRows(rows: MissingItemResolverRow[] | undefined): MissingResolverRow[] {
  return (rows ?? [])
    .filter((row) => String(row.item_number ?? "").trim())
    .map((row) => {
      const resolutionType: MissingResolverRow["resolution_type"] =
        row.resolution_type === "alias" ? "alias" : "new_item";
      return {
        row: row.row,
        supplier: String(row.supplier ?? "").trim(),
        item_number: String(row.item_number ?? "").trim(),
        resolution_type: resolutionType,
        category: String(row.category ?? ""),
        url: String(row.url ?? ""),
        description: String(row.description ?? ""),
        canonical_item_number: String(row.canonical_item_number ?? ""),
        units_per_order: String(row.units_per_order ?? "1")
      };
    })
    .filter((row) => row.supplier && row.item_number);
}

function csvEscape(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, "\"\"")}"`;
  }
  return value;
}

function downloadTemplateCsv(
  filename: string,
  headers: string[],
  sampleRows: Record<string, string>[]
) {
  const headerLine = headers.map(csvEscape).join(",");
  const dataLines = sampleRows.map((sampleRow) =>
    headers.map((key) => csvEscape(sampleRow[key] ?? "")).join(",")
  );
  const csv = `${headerLine}\n${dataLines.join("\n")}\n`;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function ItemsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [itemNumber, setItemNumber] = useState("");
  const [entryType, setEntryType] = useState<ItemRowType>("item");
  const [manufacturerName, setManufacturerName] = useState("UNKNOWN");
  const [aliasSupplier, setAliasSupplier] = useState("");
  const [canonicalItemNumber, setCanonicalItemNumber] = useState("");
  const [unitsPerOrder, setUnitsPerOrder] = useState("1");
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [entryMessage, setEntryMessage] = useState("");
  const [bulkRows, setBulkRows] = useState<ItemEntryRow[]>([blankRow(), blankRow(), blankRow()]);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvMessage, setCsvMessage] = useState("");
  const [csvResult, setCsvResult] = useState<ItemImportResult | null>(null);
  const [selectedImportJobId, setSelectedImportJobId] = useState<number | null>(null);
  const [importJobBusyId, setImportJobBusyId] = useState<number | null>(null);
  const [importJobsMessage, setImportJobsMessage] = useState("");
  const [missingRows, setMissingRows] = useState<MissingResolverRow[]>([]);
  const [missingMessage, setMissingMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [listBusy, setListBusy] = useState(false);
  const [listMessage, setListMessage] = useState("");
  const [editingItemId, setEditingItemId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<ItemEditDraft | null>(null);
  const [metadataRows, setMetadataRows] = useState<MetadataBulkRow[]>([
    blankMetadataRow(),
    blankMetadataRow(),
    blankMetadataRow(),
  ]);
  const [metadataMessage, setMetadataMessage] = useState("");
  const [metadataResult, setMetadataResult] = useState<MetadataBulkResult | null>(null);
  const [metadataBusy, setMetadataBusy] = useState(false);
  const [sortKey, setSortKey] = useState<"item_id" | "item_number" | "manufacturer_name" | "category" | "url">("item_id");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [selectedFlowItemId, setSelectedFlowItemId] = useState<number | null>(null);
  const key = useMemo(() => `/items?q=${encodeURIComponent(q)}`, [q]);

  const { data, error, isLoading, mutate } = useSWR(key, () =>
    apiGetWithPagination<Item[]>(key)
  );
  const {
    data: importJobsData,
    error: importJobsError,
    isLoading: importJobsLoading,
    mutate: mutateImportJobs,
  } = useSWR("/items-import-jobs", () =>
    apiGetWithPagination<ItemImportJobSummary[]>("/items/import-jobs?per_page=20")
  );
  const selectedImportJobKey = useMemo(
    () => (selectedImportJobId == null ? null : `/items/import-jobs/${selectedImportJobId}`),
    [selectedImportJobId]
  );
  const {
    data: selectedImportJobData,
    error: importJobDetailError,
    isLoading: importJobDetailLoading,
    mutate: mutateSelectedImportJob,
  } = useSWR(selectedImportJobKey, () =>
    apiGet<ItemImportJobDetail>(`/items/import-jobs/${selectedImportJobId ?? ""}`)
  );
  const { data: itemOptionsData } = useSWR("/items-options-missing-resolver", () =>
    apiGetWithPagination<Item[]>("/items?per_page=1000")
  );
  const { data: categories } = useSWR("/category-options-missing-resolver", () =>
    apiGet<string[]>("/categories")
  );
  const selectedFlowKey = useMemo(
    () => (selectedFlowItemId == null ? null : `/items/${selectedFlowItemId}/flow`),
    [selectedFlowItemId]
  );
  const {
    data: selectedFlowData,
    error: selectedFlowError,
    isLoading: selectedFlowLoading,
  } = useSWR(selectedFlowKey, () => apiGet<ItemFlowTimeline>(selectedFlowKey ?? ""));
  const itemOptions = itemOptionsData?.data ?? [];
  const categoryOptions = categories ?? [];
  const importJobs = importJobsData?.data ?? [];
  const sortedItems = useMemo(() => {
    const rows = [...(data?.data ?? [])];
    rows.sort((a, b) => {
      const left = a[sortKey] ?? "";
      const right = b[sortKey] ?? "";
      if (typeof left === "number" && typeof right === "number") {
        return sortDirection === "asc" ? left - right : right - left;
      }
      const compared = String(left).localeCompare(String(right));
      return sortDirection === "asc" ? compared : -compared;
    });
    return rows;
  }, [data?.data, sortDirection, sortKey]);

  function toggleSort(nextKey: typeof sortKey) {
    if (nextKey === sortKey) {
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

  useEffect(() => {
    if (!importJobs.length) {
      setSelectedImportJobId(null);
      return;
    }
    if (
      selectedImportJobId == null ||
      !importJobs.some((job) => job.import_job_id === selectedImportJobId)
    ) {
      setSelectedImportJobId(importJobs[0].import_job_id);
    }
  }, [importJobs, selectedImportJobId]);

  useEffect(() => {
    const stateRows = (location.state as { pendingMissingRows?: MissingItemResolverRow[] } | null)
      ?.pendingMissingRows;
    let nextRows = toMissingResolverRows(stateRows);
    if (!nextRows.length) {
      const raw = sessionStorage.getItem(PENDING_MISSING_ITEMS_KEY);
      if (raw) {
        try {
          const parsed = JSON.parse(raw) as MissingItemResolverRow[];
          nextRows = toMissingResolverRows(parsed);
        } catch {
          sessionStorage.removeItem(PENDING_MISSING_ITEMS_KEY);
        }
      }
    }
    if (nextRows.length) {
      setMissingRows(nextRows);
    }
  }, [location.key, location.state]);

  async function registerAliasRow(
    orderedItemNumber: string,
    supplier: string,
    canonicalNumber: string,
    unitsValue: string
  ) {
    const normalizedOrdered = orderedItemNumber.trim();
    if (!normalizedOrdered) {
      throw new Error("item_number is required");
    }
    const normalizedSupplier = supplier.trim();
    if (!normalizedSupplier) {
      throw new Error("supplier is required for alias rows");
    }
    const normalizedCanonical = canonicalNumber.trim();
    if (!normalizedCanonical) {
      throw new Error("canonical_item_number is required for alias rows");
    }
    const parsedUnits = Number(unitsValue || "1");
    if (!Number.isInteger(parsedUnits) || parsedUnits <= 0) {
      throw new Error("units_per_order must be a positive integer");
    }
    await apiSend<RegisterMissingResult>("/register-missing/rows", {
      method: "POST",
      body: JSON.stringify({
        rows: [
          {
            supplier: normalizedSupplier,
            item_number: normalizedOrdered,
            resolution_type: "alias",
            canonical_item_number: normalizedCanonical,
            units_per_order: parsedUnits,
            category: null,
            url: null,
            description: null,
          },
        ],
      }),
    });
  }

  async function createOne(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setEntryMessage("");
    try {
      if (entryType === "alias") {
        await registerAliasRow(itemNumber, aliasSupplier, canonicalItemNumber, unitsPerOrder);
        setAliasSupplier("");
        setCanonicalItemNumber("");
        setUnitsPerOrder("1");
      } else {
        await apiSend<Item>("/items", {
          method: "POST",
          body: JSON.stringify({
            item_number: itemNumber,
            manufacturer_name: manufacturerName,
            category: category || null,
            description: description || null
          })
        });
      }
      setItemNumber("");
      setDescription("");
      await mutate();
    } catch (error) {
      setEntryMessage(String(error instanceof Error ? error.message : error));
    } finally {
      setSubmitting(false);
    }
  }

  function updateBulkRow(index: number, patch: Partial<ItemEntryRow>) {
    setBulkRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeBulkRow(index: number) {
    setBulkRows((prev) => prev.filter((_, i) => i !== index));
  }

  async function createBulk() {
    const rows = bulkRows.filter((row) => row.item_number.trim());
    if (!rows.length) return;
    setSubmitting(true);
    setEntryMessage("");
    try {
      for (const row of rows) {
        if (row.row_type === "alias") {
          await registerAliasRow(
            row.item_number,
            row.supplier,
            row.canonical_item_number,
            row.units_per_order
          );
        } else {
          await apiSend<Item>("/items", {
            method: "POST",
            body: JSON.stringify({
              item_number: row.item_number.trim(),
              manufacturer_name: row.manufacturer_name.trim() || "UNKNOWN",
              category: row.category.trim() || null,
              url: row.url.trim() || null,
              description: row.description.trim() || null
            })
          });
        }
      }
      setBulkRows([blankRow(), blankRow(), blankRow()]);
      await mutate();
    } catch (error) {
      setEntryMessage(String(error instanceof Error ? error.message : error));
    } finally {
      setSubmitting(false);
    }
  }

  async function importItemsCsv(event: FormEvent) {
    event.preventDefault();
    if (!csvFile) return;
    setSubmitting(true);
    setCsvMessage("");
    setImportJobsMessage("");
    try {
      const form = new FormData();
      form.append("file", csvFile);
      form.append("continue_on_error", "true");
      const result = await apiSendForm<ItemImportResult>("/items/import", form);
      setCsvResult(result);
      setCsvMessage(
        `CSV import: status=${result.status}, processed=${result.processed}, created=${result.created_count}, duplicates=${result.duplicate_count}, failed=${result.failed_count}`
      );
      if (result.import_job_id != null) {
        setSelectedImportJobId(result.import_job_id);
      }
      await mutate();
      await mutateImportJobs();
      await mutateSelectedImportJob();
    } catch (error) {
      setCsvMessage(String(error instanceof Error ? error.message : error));
    } finally {
      setSubmitting(false);
    }
  }

  async function undoImportJob(job: ItemImportJobSummary) {
    if (job.lifecycle_state !== "active") return;
    if (
      !window.confirm(
        `Undo items import job #${job.import_job_id}? This removes/restores rows created by that import when safe.`
      )
    ) {
      return;
    }
    setImportJobBusyId(job.import_job_id);
    setImportJobsMessage("");
    try {
      const result = await apiSend<{
        import_job_id: number;
        status: string;
        removed_aliases: number;
        restored_aliases: number;
        removed_items: number;
      }>(`/items/import-jobs/${job.import_job_id}/undo`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setImportJobsMessage(
        `Undo job #${result.import_job_id}: removed_items=${result.removed_items}, removed_aliases=${result.removed_aliases}, restored_aliases=${result.restored_aliases}`
      );
      await mutate();
      await mutateImportJobs();
      await mutateSelectedImportJob();
    } catch (error) {
      setImportJobsMessage(String(error instanceof Error ? error.message : error));
    } finally {
      setImportJobBusyId(null);
    }
  }

  async function redoImportJob(job: ItemImportJobSummary) {
    if (job.lifecycle_state !== "undone") return;
    if (!window.confirm(`Redo items import job #${job.import_job_id}?`)) return;
    setImportJobBusyId(job.import_job_id);
    setImportJobsMessage("");
    try {
      const result = await apiSend<{
        source_job_id: number;
        redo_job_id: number;
        import_result: ItemImportResult;
      }>(`/items/import-jobs/${job.import_job_id}/redo`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setSelectedImportJobId(result.redo_job_id);
      setCsvResult(result.import_result);
      setCsvMessage(
        `Redo import: status=${result.import_result.status}, processed=${result.import_result.processed}, created=${result.import_result.created_count}, duplicates=${result.import_result.duplicate_count}, failed=${result.import_result.failed_count}`
      );
      setImportJobsMessage(
        `Redo completed: source_job_id=${result.source_job_id}, redo_job_id=${result.redo_job_id}`
      );
      await mutate();
      await mutateImportJobs();
      await mutateSelectedImportJob();
    } catch (error) {
      setImportJobsMessage(String(error instanceof Error ? error.message : error));
    } finally {
      setImportJobBusyId(null);
    }
  }

  function setMissingRowsAndPersist(
    updater: MissingResolverRow[] | ((prev: MissingResolverRow[]) => MissingResolverRow[])
  ) {
    setMissingRows((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      if (next.length) {
        sessionStorage.setItem(PENDING_MISSING_ITEMS_KEY, JSON.stringify(next));
      } else {
        sessionStorage.removeItem(PENDING_MISSING_ITEMS_KEY);
      }
      return next;
    });
  }

  function updateMissingRow(index: number, patch: Partial<MissingResolverRow>) {
    setMissingRowsAndPersist((prev) =>
      prev.map((row, i) => (i === index ? { ...row, ...patch } : row))
    );
  }

  function removeMissingRow(index: number) {
    setMissingRowsAndPersist((prev) => prev.filter((_, i) => i !== index));
  }

  async function retryPendingBatchImportAfterResolve(): Promise<
    | { status: "ok"; importedCount: number }
    | { status: "missing_items"; rows: MissingResolverRow[]; missingCount: number }
    | { status: "error"; message: string }
    | { status: "not_found" }
  > {
    const raw = sessionStorage.getItem(PENDING_BATCH_RETRY_KEY);
    if (!raw) return { status: "not_found" };
    let pending: PendingBatchRetry;
    try {
      pending = JSON.parse(raw) as PendingBatchRetry;
    } catch {
      sessionStorage.removeItem(PENDING_BATCH_RETRY_KEY);
      return { status: "not_found" };
    }
    const result = await apiSend<BatchRetryResult>("/orders/retry-unregistered-file", {
      method: "POST",
      body: JSON.stringify({
        csv_path: pending.csv_path,
        unregistered_root: pending.unregistered_root || null,
        registered_root: pending.registered_root || null,
        default_order_date: pending.default_order_date || null,
      }),
    });
    if (result.status === "missing_items") {
      const unresolved = toMissingResolverRows(result.missing_rows);
      if (unresolved.length) {
        sessionStorage.setItem(PENDING_MISSING_ITEMS_KEY, JSON.stringify(unresolved));
      }
      return {
        status: "missing_items",
        rows: unresolved,
        missingCount: Number(result.missing_count ?? unresolved.length),
      };
    }
    if (result.status === "ok") {
      sessionStorage.removeItem(PENDING_BATCH_RETRY_KEY);
      sessionStorage.removeItem(PENDING_ORDER_IMPORT_KEY);
      sessionStorage.removeItem(PENDING_MISSING_ITEMS_KEY);
      return { status: "ok", importedCount: Number(result.imported_count ?? 0) };
    }
    return {
      status: "error",
      message: result.error || "Batch retry failed.",
    };
  }

  async function retryPendingOrderImportAfterResolve(): Promise<
    | { status: "ok"; importedCount: number }
    | { status: "missing_items"; rows: MissingResolverRow[]; missingCount: number }
    | { status: "not_found" }
  > {
    const raw = sessionStorage.getItem(PENDING_ORDER_IMPORT_KEY);
    if (!raw) return { status: "not_found" };
    let pending: PendingOrderImport;
    try {
      pending = JSON.parse(raw) as PendingOrderImport;
    } catch {
      sessionStorage.removeItem(PENDING_ORDER_IMPORT_KEY);
      return { status: "not_found" };
    }

    const form = new FormData();
    const retryFile = new File([pending.file_text], pending.file_name || "order_import.csv", {
      type: "text/csv",
    });
    form.append("file", retryFile);
    form.append("supplier_name", pending.supplier_name);
    if (pending.default_order_date) {
      form.append("default_order_date", pending.default_order_date);
    }
    const result = await apiSendForm<OrderImportResult>("/orders/import", form);
    if (result.status === "missing_items") {
      const unresolved = toMissingResolverRows(result.rows);
      if (unresolved.length) {
        sessionStorage.setItem(PENDING_MISSING_ITEMS_KEY, JSON.stringify(unresolved));
      }
      return {
        status: "missing_items",
        rows: unresolved,
        missingCount: Number(result.missing_count ?? unresolved.length),
      };
    }
    sessionStorage.removeItem(PENDING_ORDER_IMPORT_KEY);
    sessionStorage.removeItem(PENDING_MISSING_ITEMS_KEY);
    return { status: "ok", importedCount: Number(result.imported_count ?? 0) };
  }

  async function registerMissingRows() {
    if (!missingRows.length) return;
    const aliasMissingCanonical = missingRows.find(
      (row) => row.resolution_type === "alias" && !row.canonical_item_number.trim()
    );
    if (aliasMissingCanonical) {
      setMissingMessage(
        `CSV row ${aliasMissingCanonical.row ?? "-"}: alias requires canonical item selection`
      );
      return;
    }
    const aliasInvalidUnits = missingRows.find(
      (row) =>
        row.resolution_type === "alias" &&
        (!Number.isInteger(Number(row.units_per_order)) || Number(row.units_per_order) <= 0)
    );
    if (aliasInvalidUnits) {
      setMissingMessage(
        `CSV row ${aliasInvalidUnits.row ?? "-"}: units_per_order must be a positive integer`
      );
      return;
    }

    setSubmitting(true);
    setMissingMessage("");
    try {
      const payloadRows = missingRows.map((row) => ({
        item_number: row.item_number.trim(),
        supplier: row.supplier.trim(),
        resolution_type: row.resolution_type,
        category: row.category.trim() || null,
        url: row.url.trim() || null,
        description: row.description.trim() || null,
        canonical_item_number:
          row.resolution_type === "alias" ? row.canonical_item_number.trim() : null,
        units_per_order:
          row.resolution_type === "alias"
            ? Number(row.units_per_order || "1")
            : null,
      }));
      const result = await apiSend<RegisterMissingResult>("/register-missing/rows", {
        method: "POST",
        body: JSON.stringify({ rows: payloadRows }),
      });
      const registrationSummary = `Registered missing items: created_items=${result.created_items}, created_aliases=${result.created_aliases}`;
      const batchRetry = await retryPendingBatchImportAfterResolve();
      if (batchRetry.status === "ok") {
        setMissingRowsAndPersist([]);
        await mutate();
        navigate("/orders", {
          state: {
            autoMessage: `${registrationSummary}. Batch auto re-import succeeded (${batchRetry.importedCount} rows).`,
          },
        });
        return;
      }
      if (batchRetry.status === "missing_items") {
        setMissingRowsAndPersist(batchRetry.rows);
        setMissingMessage(
          `${registrationSummary}. Batch auto re-import still has missing items (${batchRetry.missingCount}). Continue editing below.`
        );
        await mutate();
        return;
      }
      if (batchRetry.status === "error") {
        setMissingMessage(`${registrationSummary}. Batch auto re-import failed: ${batchRetry.message}`);
        await mutate();
        return;
      }
      const retry = await retryPendingOrderImportAfterResolve();
      if (retry.status === "ok") {
        setMissingRowsAndPersist([]);
        await mutate();
        navigate("/orders", {
          state: {
            autoMessage: `${registrationSummary}. Auto re-import succeeded (${retry.importedCount} rows).`,
          },
        });
        return;
      }
      if (retry.status === "missing_items") {
        setMissingRowsAndPersist(retry.rows);
        setMissingMessage(
          `${registrationSummary}. Auto re-import still has missing items (${retry.missingCount}). Continue editing below.`
        );
        await mutate();
        return;
      }
      setMissingRowsAndPersist([]);
      setMissingMessage(`${registrationSummary}. Re-import manually from Orders.`);
      await mutate();
    } finally {
      setSubmitting(false);
    }
  }

  function startEdit(item: Item) {
    setListMessage("");
    setEditingItemId(item.item_id);
    setEditDraft({
      item_number: item.item_number,
      manufacturer_name: item.manufacturer_name,
      category: item.category ?? "",
      url: item.url ?? "",
      description: item.description ?? "",
    });
  }

  function cancelEdit() {
    setEditingItemId(null);
    setEditDraft(null);
  }

  async function saveEdit() {
    if (editingItemId == null || editDraft == null) return;
    setListBusy(true);
    setListMessage("");
    try {
      await apiSend<Item>(`/items/${editingItemId}`, {
        method: "PUT",
        body: JSON.stringify({
          item_number: editDraft.item_number.trim(),
          manufacturer_name: editDraft.manufacturer_name.trim(),
          category: editDraft.category.trim() || null,
          url: editDraft.url.trim() || null,
          description: editDraft.description.trim() || null,
        }),
      });
      setEditingItemId(null);
      setEditDraft(null);
      await mutate();
      setListMessage(`Updated item #${editingItemId}.`);
    } catch (error) {
      setListMessage(String(error instanceof Error ? error.message : error));
    } finally {
      setListBusy(false);
    }
  }

  async function removeItem(item: Item) {
    if (!window.confirm(`Delete item #${item.item_id} (${item.item_number})?`)) return;
    setListBusy(true);
    setListMessage("");
    try {
      await apiSend<{ deleted: boolean }>(`/items/${item.item_id}`, {
        method: "DELETE",
      });
      if (editingItemId === item.item_id) {
        setEditingItemId(null);
        setEditDraft(null);
      }
      await mutate();
      setListMessage(`Deleted item #${item.item_id}.`);
    } catch (error) {
      setListMessage(String(error instanceof Error ? error.message : error));
    } finally {
      setListBusy(false);
    }
  }

  function updateMetadataRow(index: number, patch: Partial<MetadataBulkRow>) {
    setMetadataRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeMetadataRow(index: number) {
    setMetadataRows((prev) => prev.filter((_, i) => i !== index));
  }

  async function submitMetadataBulk() {
    setMetadataBusy(true);
    setMetadataMessage("");
    setMetadataResult(null);
    try {
      const payloadRows: Array<Record<string, string | number>> = [];
      for (let idx = 0; idx < metadataRows.length; idx += 1) {
        const row = metadataRows[idx];
        const rowNo = idx + 1;
        const hasAnyMetadata =
          Boolean(row.category.trim()) || Boolean(row.url.trim()) || Boolean(row.description.trim());
        if (!row.item_id.trim() && !hasAnyMetadata) {
          continue;
        }
        if (!row.item_id.trim()) {
          setMetadataMessage(`Bulk metadata row ${rowNo}: item_id is required`);
          return;
        }
        const itemId = Number(row.item_id);
        if (!Number.isInteger(itemId) || itemId <= 0) {
          setMetadataMessage(`Bulk metadata row ${rowNo}: item_id must be a positive integer`);
          return;
        }
        if (!hasAnyMetadata) {
          setMetadataMessage(`Bulk metadata row ${rowNo}: set category, url, or description`);
          return;
        }
        const entry: Record<string, string | number> = { item_id: itemId };
        if (row.category.trim()) entry.category = row.category.trim();
        if (row.url.trim()) entry.url = row.url.trim();
        if (row.description.trim()) entry.description = row.description.trim();
        payloadRows.push(entry);
      }
      if (!payloadRows.length) {
        setMetadataMessage("No bulk metadata rows to submit.");
        return;
      }
      const result = await apiSend<MetadataBulkResult>("/items/metadata/bulk", {
        method: "POST",
        body: JSON.stringify({
          rows: payloadRows,
          continue_on_error: true,
        }),
      });
      setMetadataResult(result);
      setMetadataMessage(
        `Bulk metadata: status=${result.status}, processed=${result.processed}, updated=${result.updated_count}, failed=${result.failed_count}`
      );
      await mutate();
    } catch (error) {
      setMetadataMessage(String(error instanceof Error ? error.message : error));
    } finally {
      setMetadataBusy(false);
    }
  }

  const csvIssues = (csvResult?.rows ?? []).filter((row) => row.status !== "created");
  const metadataIssues = (metadataResult?.rows ?? []).filter((row) => row.status === "error");
  const selectedImportJob = selectedImportJobData?.job;
  const selectedImportJobIssues = (selectedImportJobData?.effects ?? []).filter(
    (row) => row.status !== "created"
  );
  const itemLabel = (item: Item) => `${item.item_number} (${item.manufacturer_name}) #${item.item_id}`;
  const uniqueCategoryOptions = Array.from(new Set(categoryOptions));

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Items</h1>
        <p className="mt-1 text-sm text-slate-600">
          Spreadsheet-like single and bulk item registration.
        </p>
      </section>

      {missingRows.length > 0 && (
        <section className="panel p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-lg font-semibold">Resolve Missing Items From Orders</h2>
            <button className="button-subtle" onClick={() => navigate("/orders")} type="button">
              Back To Orders
            </button>
          </div>
          <p className="mt-1 text-sm text-slate-600">
            Fill this form and submit to register missing rows. The app will retry order import automatically.
          </p>
          <datalist id="resolver-category-options">
            {uniqueCategoryOptions.map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-[1400px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">CSV Row</th>
                  <th className="px-2 py-2">Supplier</th>
                  <th className="px-2 py-2">Ordered Item</th>
                  <th className="px-2 py-2">Resolution</th>
                  <th className="px-2 py-2">Category</th>
                  <th className="px-2 py-2">URL</th>
                  <th className="px-2 py-2">Description</th>
                  <th className="px-2 py-2">Canonical Item (alias only)</th>
                  <th className="px-2 py-2">Units/Order</th>
                  <th className="px-2 py-2">-</th>
                </tr>
              </thead>
              <tbody>
                {missingRows.map((row, idx) => (
                  <tr key={`${row.supplier}-${row.item_number}-${idx}`} className="border-b border-slate-100">
                    <td className="px-2 py-2">{row.row ?? "-"}</td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.supplier}
                        onChange={(e) => updateMissingRow(idx, { supplier: e.target.value })}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.item_number}
                        onChange={(e) => updateMissingRow(idx, { item_number: e.target.value })}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <select
                        className="input"
                        value={row.resolution_type}
                        onChange={(e) =>
                          updateMissingRow(idx, {
                            resolution_type: e.target.value as "new_item" | "alias",
                          })
                        }
                      >
                        <option value="new_item">new_item</option>
                        <option value="alias">alias</option>
                      </select>
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.category}
                        onChange={(e) => updateMissingRow(idx, { category: e.target.value })}
                        list="resolver-category-options"
                        disabled={row.resolution_type === "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.url}
                        onChange={(e) => updateMissingRow(idx, { url: e.target.value })}
                        disabled={row.resolution_type === "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.description}
                        onChange={(e) => updateMissingRow(idx, { description: e.target.value })}
                        disabled={row.resolution_type === "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <select
                        className="input"
                        value={row.canonical_item_number}
                        onChange={(e) =>
                          updateMissingRow(idx, { canonical_item_number: e.target.value })
                        }
                        disabled={row.resolution_type !== "alias"}
                      >
                        <option value="">Select canonical item</option>
                        {itemOptions.map((item) => (
                          <option key={item.item_id} value={item.item_number}>
                            {itemLabel(item)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        type="number"
                        min={1}
                        step={1}
                        value={row.units_per_order}
                        onChange={(e) => updateMissingRow(idx, { units_per_order: e.target.value })}
                        disabled={row.resolution_type !== "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <button className="button-subtle" onClick={() => removeMissingRow(idx)} type="button">
                        Del
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="button" disabled={submitting} onClick={registerMissingRows} type="button">
              Register And Retry Import
            </button>
            <button className="button-subtle" onClick={() => navigate("/orders")} type="button">
              Return To Orders
            </button>
          </div>
          {missingMessage && <p className="mt-2 text-sm text-signal">{missingMessage}</p>}
        </section>
      )}

      <section className="grid gap-5 lg:grid-cols-2">
        <form className="panel space-y-3 p-4" onSubmit={createOne}>
          <h2 className="font-display text-lg font-semibold">Create Item / Alias</h2>
          <select
            className="input"
            value={entryType}
            onChange={(e) => setEntryType(e.target.value as ItemRowType)}
          >
            <option value="item">item</option>
            <option value="alias">alias</option>
          </select>
          <input
            className="input"
            placeholder={entryType === "alias" ? "Ordered item number (alias)" : "Item number"}
            value={itemNumber}
            onChange={(e) => setItemNumber(e.target.value)}
            required
          />
          <input
            className="input"
            placeholder="Manufacturer"
            value={manufacturerName}
            onChange={(e) => setManufacturerName(e.target.value)}
            disabled={entryType === "alias"}
            required={entryType === "item"}
          />
          <input
            className="input"
            placeholder="Supplier (alias only)"
            value={aliasSupplier}
            onChange={(e) => setAliasSupplier(e.target.value)}
            disabled={entryType !== "alias"}
            required={entryType === "alias"}
          />
          <select
            className="input"
            value={canonicalItemNumber}
            onChange={(e) => setCanonicalItemNumber(e.target.value)}
            disabled={entryType !== "alias"}
          >
            <option value="">Canonical item (alias only)</option>
            {itemOptions.map((item) => (
              <option key={item.item_id} value={item.item_number}>
                {itemLabel(item)}
              </option>
            ))}
          </select>
          <input
            className="input"
            type="number"
            min={1}
            step={1}
            placeholder="Units/Order (alias only)"
            value={unitsPerOrder}
            onChange={(e) => setUnitsPerOrder(e.target.value)}
            disabled={entryType !== "alias"}
          />
          <input
            className="input"
            placeholder="Category (optional)"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            disabled={entryType === "alias"}
          />
          <input
            className="input"
            placeholder="Description (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={entryType === "alias"}
          />
          <button className="button w-full" disabled={submitting} type="submit">
            {entryType === "alias" ? "Add Alias" : "Add Item"}
          </button>
        </form>

        <div className="panel space-y-3 p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-lg font-semibold">Bulk Item Entry</h2>
            <button
              className="button-subtle"
              type="button"
              onClick={() => setBulkRows((prev) => [...prev, blankRow()])}
            >
              Add Row
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-[1280px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="min-w-[110px] px-2 py-2">Type</th>
                  <th className="px-2 py-2">Item Number</th>
                  <th className="px-2 py-2">Manufacturer</th>
                  <th className="px-2 py-2">Alias Supplier</th>
                  <th className="px-2 py-2">Canonical Item (alias)</th>
                  <th className="px-2 py-2">Units/Order (alias)</th>
                  <th className="px-2 py-2">Category</th>
                  <th className="px-2 py-2">URL</th>
                  <th className="px-2 py-2">Description</th>
                  <th className="px-2 py-2">-</th>
                </tr>
              </thead>
              <tbody>
                {bulkRows.map((row, idx) => (
                  <tr key={idx} className="border-b border-slate-100">
                    <td className="min-w-[110px] px-2 py-2">
                      <select
                        className="input min-w-[110px]"
                        value={row.row_type}
                        onChange={(e) =>
                          updateBulkRow(idx, { row_type: e.target.value as ItemRowType })
                        }
                      >
                        <option value="item">item</option>
                        <option value="alias">alias</option>
                      </select>
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.item_number}
                        onChange={(e) => updateBulkRow(idx, { item_number: e.target.value })}
                        placeholder={row.row_type === "alias" ? "ER2-P4" : "LENS-001"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.manufacturer_name}
                        onChange={(e) => updateBulkRow(idx, { manufacturer_name: e.target.value })}
                        placeholder="Thorlabs"
                        disabled={row.row_type === "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.supplier}
                        onChange={(e) => updateBulkRow(idx, { supplier: e.target.value })}
                        placeholder="Supplier for alias"
                        disabled={row.row_type !== "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <select
                        className="input"
                        value={row.canonical_item_number}
                        onChange={(e) => updateBulkRow(idx, { canonical_item_number: e.target.value })}
                        disabled={row.row_type !== "alias"}
                      >
                        <option value="">Select canonical item</option>
                        {itemOptions.map((item) => (
                          <option key={item.item_id} value={item.item_number}>
                            {itemLabel(item)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        type="number"
                        min={1}
                        step={1}
                        value={row.units_per_order}
                        onChange={(e) => updateBulkRow(idx, { units_per_order: e.target.value })}
                        placeholder="1"
                        disabled={row.row_type !== "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.category}
                        onChange={(e) => updateBulkRow(idx, { category: e.target.value })}
                        placeholder="Lens"
                        disabled={row.row_type === "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.url}
                        onChange={(e) => updateBulkRow(idx, { url: e.target.value })}
                        placeholder="https://..."
                        disabled={row.row_type === "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        className="input"
                        value={row.description}
                        onChange={(e) => updateBulkRow(idx, { description: e.target.value })}
                        placeholder="notes"
                        disabled={row.row_type === "alias"}
                      />
                    </td>
                    <td className="px-2 py-2">
                      <button className="button-subtle" type="button" onClick={() => removeBulkRow(idx)}>
                        Del
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-500">
            Alias supplier means the supplier namespace where the ordered SKU alias is defined.
          </p>
          <button className="button w-full" disabled={submitting} onClick={createBulk}>
            Submit Bulk Rows
          </button>
        </div>
      </section>
      {entryMessage && <p className="text-sm text-signal">{entryMessage}</p>}

      <section className="panel p-4">
        <h2 className="font-display text-lg font-semibold">Import Items CSV</h2>
        <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
          <p className="font-semibold text-slate-900">CSV Format</p>
          <p className="mt-1">
            Required columns: <code>item_number</code>. Optional: <code>row_type</code> (
            <code>item</code>/<code>alias</code>, defaults to <code>item</code>).
          </p>
          <p>
            Item rows use <code>manufacturer_name</code> (or <code>manufacturer</code>),{" "}
            <code>category</code>, <code>url</code>, <code>description</code>.
          </p>
          <p>
            Alias rows require <code>supplier</code>, <code>canonical_item_number</code>, and{" "}
            <code>units_per_order</code> (&gt; 0).
          </p>
          <p>Missing manufacturer defaults to <code>UNKNOWN</code>.</p>
          <button
            className="button-subtle mt-2"
            type="button"
            onClick={() =>
              downloadTemplateCsv(
                "items_import_template.csv",
                [
                  "row_type",
                  "item_number",
                  "manufacturer_name",
                  "category",
                  "url",
                  "description",
                  "supplier",
                  "canonical_item_number",
                  "units_per_order",
                ],
                [
                  {
                    row_type: "item",
                    item_number: "LENS-001",
                    manufacturer_name: "Thorlabs",
                    category: "Lens",
                    url: "https://example.com/lens-001",
                    description: "Sample lens row",
                    supplier: "",
                    canonical_item_number: "",
                    units_per_order: "",
                  },
                  {
                    row_type: "alias",
                    item_number: "ER2-P4",
                    manufacturer_name: "",
                    category: "",
                    url: "",
                    description: "",
                    supplier: "Thorlabs",
                    canonical_item_number: "ER2",
                    units_per_order: "4",
                  },
                ]
              )
            }
          >
            Download Template CSV
          </button>
        </div>

        <form className="mt-3 flex flex-wrap gap-3" onSubmit={importItemsCsv}>
          <input
            className="input max-w-xl"
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
            required
          />
          <button className="button" disabled={submitting} type="submit">
            Import Items CSV
          </button>
        </form>
        {csvMessage && <p className="mt-3 text-sm text-signal">{csvMessage}</p>}
        {csvIssues.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded-xl border border-amber-200 bg-amber-50 p-3">
            <p className="mb-2 text-sm font-semibold text-amber-900">Rows with issues</p>
            <table className="min-w-[540px] text-sm">
              <thead>
                <tr className="border-b border-amber-200 text-left text-amber-800">
                  <th className="px-2 py-2">CSV Row</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Item Number</th>
                  <th className="px-2 py-2">Message</th>
                </tr>
              </thead>
              <tbody>
                {csvIssues.map((row, idx) => (
                  <tr key={`${row.row}-${idx}`} className="border-b border-amber-100">
                    <td className="px-2 py-2">{row.row}</td>
                    <td className="px-2 py-2">{row.status}</td>
                    <td className="px-2 py-2 font-semibold">{row.item_number ?? "-"}</td>
                    <td className="px-2 py-2">{row.error ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-lg font-semibold">Items Import History</h2>
          <button className="button-subtle" type="button" onClick={() => mutateImportJobs()}>
            Refresh
          </button>
        </div>
        <p className="text-sm text-slate-600">
          Undo/redo is available per items import job. Undo is blocked if imported rows were changed
          later.
        </p>
        {importJobsMessage && <p className="mt-2 text-sm text-signal">{importJobsMessage}</p>}
        {importJobsLoading && <p className="mt-2 text-sm text-slate-500">Loading import jobs...</p>}
        {importJobsError && <p className="mt-2 text-sm text-red-600">{String(importJobsError)}</p>}
        {importJobs.length > 0 ? (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-[980px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">Job</th>
                  <th className="px-2 py-2">Created</th>
                  <th className="px-2 py-2">Source</th>
                  <th className="px-2 py-2">Lifecycle</th>
                  <th className="px-2 py-2">Result</th>
                  <th className="px-2 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {importJobs.map((job) => (
                  <tr key={job.import_job_id} className="border-b border-slate-100">
                    <td className="px-2 py-2 font-semibold">#{job.import_job_id}</td>
                    <td className="px-2 py-2">{job.created_at}</td>
                    <td className="px-2 py-2">{job.source_name}</td>
                    <td className="px-2 py-2">
                      {job.lifecycle_state}
                      {job.undone_at ? ` (at ${job.undone_at})` : ""}
                    </td>
                    <td className="px-2 py-2">
                      {job.status} | processed={job.processed}, created={job.created_count},
                      duplicates={job.duplicate_count}, failed={job.failed_count}
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="button-subtle"
                          type="button"
                          onClick={() => setSelectedImportJobId(job.import_job_id)}
                          disabled={importJobBusyId !== null}
                        >
                          View
                        </button>
                        {job.lifecycle_state === "active" ? (
                          <button
                            className="button-subtle"
                            type="button"
                            onClick={() => undoImportJob(job)}
                            disabled={importJobBusyId !== null}
                          >
                            Undo
                          </button>
                        ) : (
                          <button
                            className="button-subtle"
                            type="button"
                            onClick={() => redoImportJob(job)}
                            disabled={importJobBusyId !== null}
                          >
                            Redo
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-2 text-sm text-slate-500">No items import jobs yet.</p>
        )}
        {selectedImportJobId != null && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-sm font-semibold text-slate-900">Selected Job #{selectedImportJobId}</p>
            {importJobDetailLoading && <p className="mt-2 text-sm text-slate-500">Loading job detail...</p>}
            {importJobDetailError && (
              <p className="mt-2 text-sm text-red-600">{String(importJobDetailError)}</p>
            )}
            {selectedImportJob && (
              <>
                <p className="mt-2 text-sm text-slate-700">
                  status={selectedImportJob.status}, lifecycle={selectedImportJob.lifecycle_state},
                  processed={selectedImportJob.processed}, created={selectedImportJob.created_count},
                  duplicates={selectedImportJob.duplicate_count}, failed={selectedImportJob.failed_count}
                </p>
                {selectedImportJobIssues.length > 0 ? (
                  <div className="mt-2 overflow-x-auto rounded-lg border border-amber-200 bg-amber-50 p-2">
                    <p className="mb-2 text-sm font-semibold text-amber-900">Rows with issues</p>
                    <table className="min-w-[860px] text-sm">
                      <thead>
                        <tr className="border-b border-amber-200 text-left text-amber-800">
                          <th className="px-2 py-1">Row</th>
                          <th className="px-2 py-1">Status</th>
                          <th className="px-2 py-1">Entry</th>
                          <th className="px-2 py-1">Item</th>
                          <th className="px-2 py-1">Supplier</th>
                          <th className="px-2 py-1">Canonical</th>
                          <th className="px-2 py-1">Units</th>
                          <th className="px-2 py-1">Code</th>
                          <th className="px-2 py-1">Message</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedImportJobIssues.map((row) => (
                          <tr key={row.effect_id} className="border-b border-amber-100">
                            <td className="px-2 py-1">{row.row_number}</td>
                            <td className="px-2 py-1">{row.status}</td>
                            <td className="px-2 py-1">{row.entry_type ?? "-"}</td>
                            <td className="px-2 py-1 font-semibold">{row.item_number ?? "-"}</td>
                            <td className="px-2 py-1">{row.supplier_name ?? "-"}</td>
                            <td className="px-2 py-1">{row.canonical_item_number ?? "-"}</td>
                            <td className="px-2 py-1">{row.units_per_order ?? "-"}</td>
                            <td className="px-2 py-1">{row.code ?? "-"}</td>
                            <td className="px-2 py-1">{row.message ?? "-"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="mt-2 text-sm text-slate-600">No duplicate/error rows in this job.</p>
                )}
              </>
            )}
          </div>
        )}
      </section>

      <section className="panel p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-lg font-semibold">Bulk Metadata Update</h2>
          <button
            className="button-subtle"
            type="button"
            onClick={() => setMetadataRows((prev) => [...prev, blankMetadataRow()])}
          >
            Add Row
          </button>
        </div>
        <p className="text-sm text-slate-600">
          Update only <code>category</code>, <code>url</code>, and <code>description</code> in
          bulk. Item identity fields are not part of this flow.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-[920px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="px-2 py-2">Item ID</th>
                <th className="px-2 py-2">Category</th>
                <th className="px-2 py-2">URL</th>
                <th className="px-2 py-2">Description</th>
                <th className="px-2 py-2">-</th>
              </tr>
            </thead>
            <tbody>
              {metadataRows.map((row, idx) => (
                <tr key={idx} className="border-b border-slate-100">
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      type="number"
                      min={1}
                      step={1}
                      value={row.item_id}
                      onChange={(e) => updateMetadataRow(idx, { item_id: e.target.value })}
                      placeholder="123"
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      value={row.category}
                      onChange={(e) => updateMetadataRow(idx, { category: e.target.value })}
                      list="resolver-category-options"
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      value={row.url}
                      onChange={(e) => updateMetadataRow(idx, { url: e.target.value })}
                      placeholder="https://..."
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      value={row.description}
                      onChange={(e) => updateMetadataRow(idx, { description: e.target.value })}
                      placeholder="notes"
                    />
                  </td>
                  <td className="px-2 py-2">
                    <button className="button-subtle" type="button" onClick={() => removeMetadataRow(idx)}>
                      Del
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="button" type="button" disabled={metadataBusy} onClick={submitMetadataBulk}>
            Apply Bulk Metadata
          </button>
          <button
            className="button-subtle"
            type="button"
            disabled={metadataBusy}
            onClick={() => {
              setMetadataRows([blankMetadataRow(), blankMetadataRow(), blankMetadataRow()]);
              setMetadataResult(null);
              setMetadataMessage("");
            }}
          >
            Reset
          </button>
        </div>
        {metadataMessage && <p className="mt-2 text-sm text-signal">{metadataMessage}</p>}
        {metadataIssues.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded-xl border border-amber-200 bg-amber-50 p-3">
            <p className="mb-2 text-sm font-semibold text-amber-900">Bulk metadata issues</p>
            <table className="min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-amber-200 text-left text-amber-800">
                  <th className="px-2 py-2">Row</th>
                  <th className="px-2 py-2">Item ID</th>
                  <th className="px-2 py-2">Code</th>
                  <th className="px-2 py-2">Message</th>
                </tr>
              </thead>
              <tbody>
                {metadataIssues.map((row, idx) => (
                  <tr key={`${row.row}-${idx}`} className="border-b border-amber-100">
                    <td className="px-2 py-2">{row.row}</td>
                    <td className="px-2 py-2">{row.item_id}</td>
                    <td className="px-2 py-2">{row.code ?? "-"}</td>
                    <td className="px-2 py-2">{row.error ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h2 className="font-display text-lg font-semibold">Item List</h2>
          <input
            className="input w-80"
            placeholder="Search by keyword"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {listMessage && <p className="mb-2 text-sm text-signal">{listMessage}</p>}
        <p className="mb-2 text-xs text-slate-500">
          Referenced items can update metadata, but item number/manufacturer changes are blocked.
        </p>
        {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {error && <p className="text-sm text-red-600">{String(error)}</p>}
        {data?.data && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("item_id")}>ID {sortIndicator("item_id")}</button></th>
                  <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("item_number")}>Item Number {sortIndicator("item_number")}</button></th>
                  <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("manufacturer_name")}>Manufacturer {sortIndicator("manufacturer_name")}</button></th>
                  <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("category")}>Category {sortIndicator("category")}</button></th>
                  <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("url")}>URL {sortIndicator("url")}</button></th>
                  <th className="px-2 py-2">Description</th>
                  <th className="px-2 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((item) => (
                  <tr key={item.item_id} className="border-b border-slate-100">
                    <td className="px-2 py-2">{item.item_id}</td>
                    <td className="px-2 py-2 font-semibold">
                      {editingItemId === item.item_id ? (
                        <input
                          className="input"
                          value={editDraft?.item_number ?? ""}
                          onChange={(e) =>
                            setEditDraft((prev) => (prev ? { ...prev, item_number: e.target.value } : prev))
                          }
                        />
                      ) : (
                        item.item_number
                      )}
                    </td>
                    <td className="px-2 py-2">
                      {editingItemId === item.item_id ? (
                        <input
                          className="input"
                          value={editDraft?.manufacturer_name ?? ""}
                          onChange={(e) =>
                            setEditDraft((prev) =>
                              prev ? { ...prev, manufacturer_name: e.target.value } : prev
                            )
                          }
                        />
                      ) : (
                        item.manufacturer_name
                      )}
                    </td>
                    <td className="px-2 py-2">
                      {editingItemId === item.item_id ? (
                        <input
                          className="input"
                          value={editDraft?.category ?? ""}
                          onChange={(e) =>
                            setEditDraft((prev) => (prev ? { ...prev, category: e.target.value } : prev))
                          }
                        />
                      ) : (
                        item.category ?? "-"
                      )}
                    </td>
                    <td className="px-2 py-2">
                      {editingItemId === item.item_id ? (
                        <input
                          className="input"
                          value={editDraft?.url ?? ""}
                          onChange={(e) =>
                            setEditDraft((prev) => (prev ? { ...prev, url: e.target.value } : prev))
                          }
                        />
                      ) : (
                        item.url ? (
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 underline"
                          >
                            {item.url}
                          </a>
                        ) : (
                          "-"
                        )
                      )}
                    </td>
                    <td className="px-2 py-2">
                      {editingItemId === item.item_id ? (
                        <input
                          className="input"
                          value={editDraft?.description ?? ""}
                          onChange={(e) =>
                            setEditDraft((prev) => (prev ? { ...prev, description: e.target.value } : prev))
                          }
                        />
                      ) : (
                        item.description ?? "-"
                      )}
                    </td>
                    <td className="px-2 py-2">
                      {editingItemId === item.item_id ? (
                        <div className="flex flex-wrap gap-2">
                          <button
                            className="button-subtle"
                            type="button"
                            disabled={listBusy}
                            onClick={saveEdit}
                          >
                            Save
                          </button>
                          <button
                            className="button-subtle"
                            type="button"
                            disabled={listBusy}
                            onClick={cancelEdit}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          <button
                            className="button-subtle"
                            type="button"
                            disabled={listBusy}
                            onClick={() => startEdit(item)}
                          >
                            Edit
                          </button>
                          <button
                            className="button-subtle"
                            type="button"
                            disabled={listBusy}
                            onClick={() => setSelectedFlowItemId(item.item_id)}
                          >
                            Flow
                          </button>
                          <button
                            className="button-subtle"
                            type="button"
                            disabled={listBusy}
                            onClick={() => removeItem(item)}
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selectedFlowItemId != null && (
        <section className="panel p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-lg font-semibold">Item Increase/Decrease Timeline</h2>
            <button className="button-subtle" type="button" onClick={() => setSelectedFlowItemId(null)}>
              Close
            </button>
          </div>
          {selectedFlowLoading && <p className="text-sm text-slate-500">Loading timeline...</p>}
          {selectedFlowError && <p className="text-sm text-red-600">{String(selectedFlowError)}</p>}
          {selectedFlowData && (
            <>
              <p className="mb-2 text-sm text-slate-700">
                <strong>{selectedFlowData.item_number}</strong> ({selectedFlowData.manufacturer_name}) / Current STOCK: <strong>{selectedFlowData.current_stock}</strong>
              </p>
              <p className="mb-3 text-xs text-slate-500">
                This timeline combines transaction history (actual past changes) with open-order arrivals and active reservation deadlines (planned demand changes).
              </p>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-slate-500">
                      <th className="px-2 py-2">When</th>
                      <th className="px-2 py-2">Change</th>
                      <th className="px-2 py-2">Direction</th>
                      <th className="px-2 py-2">Why</th>
                      <th className="px-2 py-2">Reference</th>
                      <th className="px-2 py-2">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedFlowData.events.map((event, idx) => (
                      <tr key={`${event.source_ref}-${event.event_at}-${idx}`} className="border-b border-slate-100">
                        <td className="px-2 py-2">{event.event_at}</td>
                        <td className={`px-2 py-2 font-semibold ${event.delta >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                          {event.delta >= 0 ? `+${event.delta}` : String(event.delta)}
                        </td>
                        <td className="px-2 py-2">{event.direction}</td>
                        <td className="px-2 py-2">{event.reason}</td>
                        <td className="px-2 py-2">{event.source_ref}</td>
                        <td className="px-2 py-2">{event.note ?? "-"}</td>
                      </tr>
                    ))}
                    {selectedFlowData.events.length === 0 && (
                      <tr>
                        <td className="px-2 py-3 text-slate-500" colSpan={6}>No increase/decrease events found for this item.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      )}

    </div>
  );
}
