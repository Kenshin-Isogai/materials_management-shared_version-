import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { CatalogPicker } from "../components/CatalogPicker";
import { apiDownload, apiGet, apiGetWithPagination, apiSend, apiSendForm } from "../lib/api";
import { formatActionError, resolvePreviewSelection } from "../lib/previewState";
import type { CatalogSearchResult, Item } from "../lib/types";

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
  source_name?: string;
};

type ItemImportResult = {
  status: string;
  processed: number;
  created_count: number;
  duplicate_count: number;
  failed_count: number;
  import_job_id?: number;
  import_job_ids?: number[];
  rows: ItemImportRow[];
};

type ItemImportPreviewMatch = CatalogSearchResult & {
  confidence_score?: number | null;
  match_reason?: string | null;
};

type ItemImportPreviewRow = {
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

type ItemImportPreview = {
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

function itemPreviewMatchToCatalogResult(
  match: ItemImportPreviewMatch
): CatalogSearchResult {
  return {
    entity_type: "item",
    entity_id: match.entity_id,
    value_text: match.value_text,
    display_label: match.display_label,
    summary: match.summary,
    match_source: match.match_source,
  };
}

function itemImportPreviewRowKey(row: ItemImportPreviewRow): string {
  return row.preview_key ?? String(row.row);
}

function mergeItemImportPreviews(previews: ItemImportPreview[]): ItemImportPreview {
  if (previews.length === 1) {
    return {
      ...previews[0],
      rows: previews[0].rows.map((row) => ({
        ...row,
        source_name: previews[0].source_name,
        source_index: 0,
        preview_key: `0:${row.row}`
      }))
    };
  }

  return {
    source_name: `${previews.length} files`,
    summary: previews.reduce(
      (summary, preview) => ({
        total_rows: summary.total_rows + preview.summary.total_rows,
        exact: summary.exact + preview.summary.exact,
        high_confidence: summary.high_confidence + preview.summary.high_confidence,
        needs_review: summary.needs_review + preview.summary.needs_review,
        unresolved: summary.unresolved + preview.summary.unresolved
      }),
      {
        total_rows: 0,
        exact: 0,
        high_confidence: 0,
        needs_review: 0,
        unresolved: 0
      }
    ),
    blocking_errors: previews.flatMap((preview) =>
      preview.blocking_errors.map((message) => `${preview.source_name}: ${message}`)
    ),
    can_auto_accept: previews.every((preview) => preview.can_auto_accept),
    rows: previews.flatMap((preview, sourceIndex) =>
      preview.rows.map((row) => ({
        ...row,
        source_name: preview.source_name,
        source_index: sourceIndex,
        preview_key: `${sourceIndex}:${row.row}`
      }))
    )
  };
}

function mergeItemImportResults(
  results: Array<{ sourceName: string; result: ItemImportResult }>
): ItemImportResult {
  const processed = results.reduce((sum, entry) => sum + entry.result.processed, 0);
  const createdCount = results.reduce((sum, entry) => sum + entry.result.created_count, 0);
  const duplicateCount = results.reduce((sum, entry) => sum + entry.result.duplicate_count, 0);
  const failedCount = results.reduce((sum, entry) => sum + entry.result.failed_count, 0);
  const importJobIds = results
    .map((entry) => entry.result.import_job_id)
    .filter((jobId): jobId is number => typeof jobId === "number");

  return {
    status: failedCount === 0 ? "ok" : createdCount > 0 || duplicateCount > 0 ? "partial" : "error",
    processed,
    created_count: createdCount,
    duplicate_count: duplicateCount,
    failed_count: failedCount,
    import_job_id: importJobIds[importJobIds.length - 1],
    import_job_ids: importJobIds,
    rows: results.flatMap(({ sourceName, result }) =>
      result.rows.map((row) => ({
        ...row,
        source_name: sourceName
      }))
    )
  };
}

function previewStatusTone(status: ItemImportPreviewRow["status"]): string {
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

export function ItemsPage() {
  const [q, setQ] = useState("");

  const [entryMessage, setEntryMessage] = useState("");
  const [bulkRows, setBulkRows] = useState<ItemEntryRow[]>([blankRow(), blankRow(), blankRow()]);
  const [csvFiles, setCsvFiles] = useState<File[]>([]);
  const [csvMessage, setCsvMessage] = useState("");
  const [csvResult, setCsvResult] = useState<ItemImportResult | null>(null);
  const [csvPreview, setCsvPreview] = useState<ItemImportPreview | null>(null);
  const [csvPreviewSelections, setCsvPreviewSelections] = useState<
    Record<string, CatalogSearchResult | null>
  >({});
  const [csvPreviewUnits, setCsvPreviewUnits] = useState<Record<string, string>>({});
  const [selectedImportJobId, setSelectedImportJobId] = useState<number | null>(null);
  const [importJobBusyId, setImportJobBusyId] = useState<number | null>(null);
  const [importJobsMessage, setImportJobsMessage] = useState("");
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
  const [isItemListExpanded, setIsItemListExpanded] = useState(true);
  const [selectedFlowItemId, setSelectedFlowItemId] = useState<number | null>(null);
  const flowPanelRef = useRef<HTMLElement | null>(null);
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
    if (selectedFlowItemId == null) return;
    flowPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [selectedFlowItemId]);

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
    await apiSend("/aliases/upsert", {
      method: "POST",
      body: JSON.stringify({
        supplier_name: normalizedSupplier,
        ordered_item_number: normalizedOrdered,
        canonical_item_number: normalizedCanonical,
        units_per_order: parsedUnits,
      }),
    });
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

  function downloadImportCsv(path: string, fallbackFilename: string) {
    void apiDownload(path, fallbackFilename).catch((error) => {
      setCsvMessage(error instanceof Error ? error.message : String(error));
    });
  }

  function resetCsvPreview() {
    setCsvPreview(null);
    setCsvPreviewSelections({});
    setCsvPreviewUnits({});
  }

  function applyCsvPreview(preview: ItemImportPreview) {
    const nextSelections: Record<string, CatalogSearchResult | null> = {};
    const nextUnits: Record<string, string> = {};
    for (const row of preview.rows) {
      const rowKey = itemImportPreviewRowKey(row);
      nextSelections[rowKey] = row.suggested_match
        ? itemPreviewMatchToCatalogResult(row.suggested_match)
        : null;
      nextUnits[rowKey] = row.units_per_order || "1";
    }
    setCsvPreview(preview);
    setCsvPreviewSelections(nextSelections);
    setCsvPreviewUnits(nextUnits);
  }

  function selectedCsvPreviewMatch(
    row: ItemImportPreviewRow
  ): CatalogSearchResult | null {
    return resolvePreviewSelection(
      csvPreviewSelections,
      itemImportPreviewRowKey(row),
      row.suggested_match ? itemPreviewMatchToCatalogResult(row.suggested_match) : null
    );
  }

  function previewUnitsValue(row: ItemImportPreviewRow): string {
    return csvPreviewUnits[itemImportPreviewRowKey(row)] ?? row.units_per_order ?? "1";
  }

  function canConfirmPreviewRow(row: ItemImportPreviewRow): boolean {
    if (!row.blocking) return true;
    if (row.action === "resolve_alias_canonical_item") {
      return selectedCsvPreviewMatch(row) !== null;
    }
    if (
      row.entry_type === "alias" &&
      row.message === "units_per_order must be a positive integer"
    ) {
      const unitsValue = Number(previewUnitsValue(row));
      return Number.isInteger(unitsValue) && unitsValue > 0;
    }
    return false;
  }

  async function previewItemsCsv(event: FormEvent) {
    event.preventDefault();
    if (csvFiles.length === 0) return;
    setSubmitting(true);
    setCsvMessage("");
    setCsvResult(null);
    setImportJobsMessage("");
    resetCsvPreview();
    try {
      const previews: ItemImportPreview[] = [];
      for (const file of csvFiles) {
        const form = new FormData();
        form.append("file", file);
        previews.push(await apiSendForm<ItemImportPreview>("/items/import-preview", form));
      }
      const result = mergeItemImportPreviews(previews);
      applyCsvPreview(result);
      setCsvMessage(
        result.can_auto_accept
          ? `Preview ready: ${csvFiles.length} file(s), ${result.summary.total_rows} row(s) are ready to import.`
          : `Preview ready: files=${csvFiles.length}, review=${result.summary.needs_review}, unresolved=${result.summary.unresolved}.`
      );
    } catch (error) {
      setCsvMessage(formatActionError("Preview failed", error));
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmItemsPreview() {
    if (csvFiles.length === 0 || !csvPreview) return;

    for (const row of csvPreview.rows) {
      if (row.entry_type !== "alias") continue;
      const unitsValue = Number(previewUnitsValue(row));
      if (!Number.isInteger(unitsValue) || unitsValue <= 0) {
        setCsvMessage(`Row ${row.row}: units/order must be an integer greater than 0.`);
        return;
      }
    }

    const blockingRow = csvPreview.rows.find((row) => !canConfirmPreviewRow(row));
    if (blockingRow) {
      setCsvMessage(`Row ${blockingRow.row}: ${blockingRow.message}`);
      return;
    }

    const rowOverrides: Record<
      string,
      { canonical_item_number?: string; units_per_order?: number }
    > = {};

    for (const row of csvPreview.rows) {
      if (row.entry_type !== "alias") continue;
      const selection = selectedCsvPreviewMatch(row);
      const unitsValue = Number(previewUnitsValue(row));
      const suggestedMatch = row.suggested_match;
      const selectedItemNumber = selection?.value_text.trim();
      const canonicalChanged = Boolean(
        selectedItemNumber &&
        (
          row.action === "resolve_alias_canonical_item" ||
          (suggestedMatch
            ? selection?.entity_id !== suggestedMatch.entity_id
            : selectedItemNumber !== row.canonical_item_number.trim())
        )
      );
      const unitsChanged = String(unitsValue) !== String(row.units_per_order || "1");
      if (!canonicalChanged && !unitsChanged) continue;
      const rowKey = itemImportPreviewRowKey(row);
      rowOverrides[rowKey] = {};
      if (canonicalChanged && selectedItemNumber) {
        rowOverrides[rowKey].canonical_item_number = selectedItemNumber;
      }
      if (unitsChanged) {
        rowOverrides[rowKey].units_per_order = unitsValue;
      }
    }

    setSubmitting(true);
    setCsvMessage("");
    try {
      const importResults: Array<{ sourceName: string; result: ItemImportResult }> = [];
      for (const [sourceIndex, file] of csvFiles.entries()) {
        const fileRowOverrides: Record<
          number,
          { canonical_item_number?: string; units_per_order?: number }
        > = {};
        for (const row of csvPreview.rows) {
          if ((row.source_index ?? 0) !== sourceIndex) continue;
          const rowKey = itemImportPreviewRowKey(row);
          if (rowOverrides[rowKey] != null) {
            fileRowOverrides[row.row] = rowOverrides[rowKey];
          }
        }
        const form = new FormData();
        form.append("file", file);
        form.append("continue_on_error", "true");
        if (Object.keys(fileRowOverrides).length > 0) {
          form.append("row_overrides", JSON.stringify(fileRowOverrides));
        }
        importResults.push({
          sourceName: file.name,
          result: await apiSendForm<ItemImportResult>("/items/import", form)
        });
      }
      const result = mergeItemImportResults(importResults);
      setCsvResult(result);
      resetCsvPreview();
      setCsvMessage(
        `CSV import: files=${csvFiles.length}, status=${result.status}, processed=${result.processed}, created=${result.created_count}, duplicates=${result.duplicate_count}, failed=${result.failed_count}`
      );
      if (result.import_job_id != null) {
        setSelectedImportJobId(result.import_job_id);
      }
      await mutate();
      await mutateImportJobs();
      await mutateSelectedImportJob();
    } catch (error) {
      setCsvMessage(formatActionError("Import failed", error));
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
  const showCsvSourceColumn = Boolean(
    csvPreview?.rows.some((row) => Boolean(row.source_name)) ||
      csvIssues.some((row) => Boolean(row.source_name))
  );
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

      <datalist id="category-options">
        {uniqueCategoryOptions.map((value) => (
          <option key={value} value={value} />
        ))}
      </datalist>

      <section>

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
                        list="category-options"
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
        <h2 className="font-display text-lg font-semibold">General Items CSV Import</h2>
        <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
          <p className="font-semibold text-slate-900">Use this for general item registration or alias maintenance.</p>
          <p className="mt-1">
            This path previews the CSV before import and is not limited to files generated by the missing-items workflow.
          </p>
          <p>
            Missing-item CSVs downloaded from Orders use this same import path after you fill in the required item or alias details.
          </p>
          <p className="mt-2 font-semibold text-slate-900">CSV Format</p>
          <p className="mt-1">
            Required columns: <code>item_number</code>. Optional: <code>row_type</code> (
            <code>item</code>/<code>alias</code>, defaults to <code>item</code>).
          </p>
          <p>
            Generated missing-item CSVs may use <code>resolution_type</code> (
            <code>new_item</code>/<code>alias</code>) instead of <code>row_type</code>; both are accepted.
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
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              className="button-subtle"
              type="button"
              onClick={() => downloadImportCsv("/items/import-template", "items_import_template.csv")}
            >
              Download Template CSV
            </button>
            <button
              className="button-subtle"
              type="button"
              onClick={() => downloadImportCsv("/items/import-reference", "items_import_reference.csv")}
            >
              Download Reference CSV
            </button>
          </div>
        </div>

        <form className="mt-3 flex flex-wrap gap-3" onSubmit={previewItemsCsv}>
          <input
            className="input max-w-xl"
            type="file"
            accept=".csv,text/csv"
            multiple
            onChange={(e) => {
              setCsvFiles(Array.from(e.target.files ?? []));
              setCsvResult(null);
              resetCsvPreview();
            }}
            required
          />
          <button className="button" disabled={submitting} type="submit">
            Preview Import
          </button>
        </form>
        <p className="mt-2 text-xs text-slate-500">
          You can select multiple CSV files; successful imports are archived under{" "}
          <code>imports/items/registered/&lt;YYYY-MM&gt;/</code>.
        </p>
        {csvMessage && <p className="mt-3 text-sm text-signal">{csvMessage}</p>}
        {csvPreview && (
          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-emerald-50 px-3 py-1 font-semibold text-emerald-700">
                Exact {csvPreview.summary.exact}
              </span>
              <span className="rounded-full bg-sky-50 px-3 py-1 font-semibold text-sky-700">
                High Confidence {csvPreview.summary.high_confidence}
              </span>
              <span className="rounded-full bg-amber-50 px-3 py-1 font-semibold text-amber-700">
                Review {csvPreview.summary.needs_review}
              </span>
              <span className="rounded-full bg-red-50 px-3 py-1 font-semibold text-red-700">
                Unresolved {csvPreview.summary.unresolved}
              </span>
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-[1260px] text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    {showCsvSourceColumn && <th className="px-2 py-2">File</th>}
                    <th className="px-2 py-2">Row</th>
                    <th className="px-2 py-2">Type</th>
                    <th className="px-2 py-2">Input</th>
                    <th className="px-2 py-2">Resolved Canonical</th>
                    <th className="px-2 py-2">Status</th>
                    <th className="px-2 py-2">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {csvPreview.rows.map((row) => (
                    <tr key={itemImportPreviewRowKey(row)} className="border-b border-slate-100 align-top">
                      {showCsvSourceColumn && <td className="px-2 py-3">{row.source_name ?? "-"}</td>}
                      <td className="px-2 py-3 font-semibold">#{row.row}</td>
                      <td className="px-2 py-3">
                        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
                          {row.entry_type}
                        </span>
                      </td>
                      <td className="px-2 py-3">
                        <div className="space-y-1">
                          <p className="font-semibold text-slate-900">{row.item_number || "No item number"}</p>
                          {row.entry_type === "item" ? (
                            <>
                              <p className="text-xs text-slate-500">{row.manufacturer_name}</p>
                              {row.category && <p className="text-xs text-slate-500">{row.category}</p>}
                            </>
                          ) : (
                            <>
                              <p className="text-xs text-slate-500">supplier {row.supplier || "-"}</p>
                              <p className="text-xs text-slate-500">
                                canonical {row.canonical_item_number || "-"} | units {previewUnitsValue(row)}
                              </p>
                            </>
                          )}
                          {row.description && (
                            <p className="text-xs text-slate-500">{row.description}</p>
                          )}
                        </div>
                      </td>
                      <td className="px-2 py-3">
                        {selectedCsvPreviewMatch(row) ? (
                          <div className="space-y-1">
                            <p className="font-semibold text-slate-900">
                              {selectedCsvPreviewMatch(row)?.display_label}
                            </p>
                            {selectedCsvPreviewMatch(row)?.summary && (
                              <p className="text-xs text-slate-500">
                                {selectedCsvPreviewMatch(row)?.summary}
                              </p>
                            )}
                          </div>
                        ) : row.suggested_match ? (
                          <div className="space-y-1">
                            <p className="font-semibold text-slate-900">
                              {row.suggested_match.display_label}
                            </p>
                            {row.suggested_match.summary && (
                              <p className="text-xs text-slate-500">{row.suggested_match.summary}</p>
                            )}
                            {row.suggested_match.match_reason && (
                              <p className="text-xs text-slate-500">{row.suggested_match.match_reason}</p>
                            )}
                          </div>
                        ) : row.entry_type === "item" ? (
                          <p className="text-sm text-slate-500">Create new item</p>
                        ) : (
                          <p className="text-sm text-slate-500">
                            {row.canonical_item_number || "Select canonical item"}
                          </p>
                        )}
                      </td>
                      <td className="px-2 py-3">
                        <span
                          className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${previewStatusTone(row.status)}`}
                        >
                          {row.status}
                        </span>
                      </td>
                      <td className="px-2 py-3">
                        <div className="space-y-2">
                          <p className="text-xs text-slate-600">{row.message}</p>
                          {row.entry_type === "alias" && (
                            <div className="space-y-2">
                              <CatalogPicker
                                allowedTypes={["item"]}
                                onChange={(value) =>
                                  setCsvPreviewSelections((prev) => ({
                                    ...prev,
                                    [itemImportPreviewRowKey(row)]: value,
                                  }))
                                }
                                placeholder="Select canonical item"
                                recentKey="items-import-preview-canonical-item"
                                seedQuery={row.canonical_item_number}
                                value={selectedCsvPreviewMatch(row)}
                              />
                              <input
                                className="input max-w-[180px]"
                                min={1}
                                onChange={(e) =>
                                  setCsvPreviewUnits((prev) => ({
                                    ...prev,
                                    [itemImportPreviewRowKey(row)]: e.target.value,
                                  }))
                                }
                                placeholder="Units per order"
                                step={1}
                                type="number"
                                value={previewUnitsValue(row)}
                              />
                              {row.candidates.length > 1 && (
                                <p className="text-xs text-slate-500">
                                  Candidates:{" "}
                                  {row.candidates
                                    .slice(0, 3)
                                    .map((candidate) => candidate.display_label)
                                    .join(" | ")}
                                </p>
                              )}
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                className="button"
                disabled={submitting}
                onClick={() => void confirmItemsPreview()}
                type="button"
              >
                Confirm Import
              </button>
              <button
                className="button-subtle"
                disabled={submitting}
                onClick={resetCsvPreview}
                type="button"
              >
                Clear Preview
              </button>
            </div>
          </div>
        )}
        {csvIssues.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded-xl border border-amber-200 bg-amber-50 p-3">
            <p className="mb-2 text-sm font-semibold text-amber-900">Rows with issues</p>
            <table className="min-w-[540px] text-sm">
              <thead>
                <tr className="border-b border-amber-200 text-left text-amber-800">
                  {showCsvSourceColumn && <th className="px-2 py-2">File</th>}
                  <th className="px-2 py-2">CSV Row</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Item Number</th>
                  <th className="px-2 py-2">Message</th>
                </tr>
              </thead>
              <tbody>
                {csvIssues.map((row, idx) => (
                  <tr key={`${row.source_name ?? "csv"}-${row.row}-${idx}`} className="border-b border-amber-100">
                    {showCsvSourceColumn && <td className="px-2 py-2">{row.source_name ?? "-"}</td>}
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
        {importJobsError && <ApiErrorNotice error={importJobsError} area="item import job data" className="mt-2" />}
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
            {importJobDetailError && <ApiErrorNotice error={importJobDetailError} area="item import job detail" className="mt-2" />}
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
                      list="category-options"
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
          <button
            type="button"
            className="button-subtle"
            onClick={() => setIsItemListExpanded((prev) => !prev)}
            aria-expanded={isItemListExpanded}
          >
            {isItemListExpanded ? "Collapse" : "Expand"}
          </button>
          <input
            className="input w-80"
            placeholder="Search keywords (space = AND)"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {listMessage && <p className="mb-2 text-sm text-signal">{listMessage}</p>}
        <p className="mb-2 text-xs text-slate-500">
          Referenced items can update metadata, but item number/manufacturer changes are blocked.
        </p>
        {isItemListExpanded && isLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {isItemListExpanded && error && <ApiErrorNotice error={error} area="item list data" />}
        {isItemListExpanded && data?.data && (
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
                            onClick={() => {
                              setSelectedFlowItemId(item.item_id);
                              setIsItemListExpanded(false);
                            }}
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
        <section className="panel p-4" ref={flowPanelRef}>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-lg font-semibold">Item Increase/Decrease Timeline</h2>
            <button className="button-subtle" type="button" onClick={() => setSelectedFlowItemId(null)}>
              Close
            </button>
          </div>
          {selectedFlowLoading && <p className="text-sm text-slate-500">Loading timeline...</p>}
          {selectedFlowError && <ApiErrorNotice error={selectedFlowError} area="item flow timeline" />}
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
