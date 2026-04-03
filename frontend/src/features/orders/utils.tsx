import type { CatalogSearchResult, MissingItemResolverRow } from "@/lib/types";
import { isHttpsDocumentReference } from "@/lib/documentReferences";
import type {
  OrderImportPreview,
  OrderImportPreviewMatch,
  OrderImportPreviewRow,
  OrderImportPreviewStatus,
  LockedPurchaseOrderPreview,
} from "@/features/orders/types";

export function normalizeMissingRows(
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

export function downloadMissingRowsCsv(rows: MissingItemResolverRow[], filename: string) {
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

export function previewMatchToCatalogResult(match: OrderImportPreviewMatch): CatalogSearchResult {
  return {
    entity_type: "item",
    entity_id: match.item_id,
    value_text: match.canonical_item_number,
    display_label: match.display_label,
    summary: match.summary,
    match_source: match.match_source,
  };
}

export function orderPreviewRowKey(row: OrderImportPreviewRow): string {
  return row.preview_key ?? `${row.source_name ?? "orders_import.csv"}:${row.row}`;
}

export function purchaseOrderPreviewKey(value: {
  supplier_id: number;
  purchase_order_number: string;
}): string {
  return `${value.supplier_id}:${value.purchase_order_number}`;
}

export function mergeOrderImportPreviews(previews: OrderImportPreview[]): OrderImportPreview {
  const rows: OrderImportPreviewRow[] = [];
  const blockingErrors: string[] = [];
  const duplicateQuotationNumbers = new Set<string>();
  const lockedPurchaseOrders = new Map<string, LockedPurchaseOrderPreview>();
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
    (preview.locked_purchase_orders ?? []).forEach((locked) => {
      lockedPurchaseOrders.set(purchaseOrderPreviewKey(locked), locked);
    });
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
    locked_purchase_orders: Array.from(lockedPurchaseOrders.values()),
    can_auto_accept:
      previews.length > 0 &&
      previews.every((preview) => preview.can_auto_accept),
    rows,
  };
}

export function normalizeCatalogValue(value: string): string {
  return value.trim().toLowerCase().replace(/[\s_-]+/g, "");
}

export { previewStatusLabel, previewStatusTone } from "@/lib/previewStatus";

export function renderDocumentReference(url: string | null | undefined, label = "Open document") {
  if (!url) return "-";
  if (!isHttpsDocumentReference(url)) {
    return <span className="break-all text-slate-700">{url}</span>;
  }
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

export function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export function summaryMetric(label: string, value: string | number, tone: "slate" | "sky" | "emerald" | "amber" = "slate") {
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
