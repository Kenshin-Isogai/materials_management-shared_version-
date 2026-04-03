import type { CatalogSearchResult } from "@/lib/types";
import type {
  ItemEntryRow,
  ItemImportPreview,
  ItemImportPreviewMatch,
  ItemImportPreviewRow,
  ItemImportResult,
  MetadataBulkRow,
} from "@/features/items/types";

export function itemPreviewMatchToCatalogResult(
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

export function itemImportPreviewRowKey(row: ItemImportPreviewRow): string {
  return row.preview_key ?? String(row.row);
}

export function mergeItemImportPreviews(previews: ItemImportPreview[]): ItemImportPreview {
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

export function mergeItemImportResults(
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

export function previewStatusTone(status: ItemImportPreviewRow["status"]): string {
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

export const blankRow = (): ItemEntryRow => ({
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

export const blankMetadataRow = (): MetadataBulkRow => ({
  item_id: "",
  category: "",
  url: "",
  description: "",
});
