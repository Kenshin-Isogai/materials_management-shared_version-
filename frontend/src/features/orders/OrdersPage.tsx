import { FormEvent, useRef, useState } from "react";
import useSWR from "swr";
import { apiDownload, apiGet, apiGetAllPages, apiGetWithPagination, apiSendForm } from "@/lib/api";
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
import { OrderLinesSection, type OrderLinesSectionHandle } from "@/features/orders/components/OrderLinesSection";
import { QuotationSection } from "@/features/orders/components/QuotationSection";
import { PurchaseOrdersSection } from "@/features/orders/components/PurchaseOrdersSection";

export function OrdersPage() {
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
  const orderLinesSectionRef = useRef<OrderLinesSectionHandle | null>(null);

  const { data: ordersData, error, isLoading, mutate: mutateOrders } = useSWR("/purchase-order-lines", () =>
    apiGetAllPages<Order>("/purchase-order-lines?per_page=200"),
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
  const { data: generatedArtifacts = [] } = useSWR("/artifacts?artifact_type=missing_items_register", apiGet<GeneratedArtifact[]>);
  const { data: itemsData } = useSWR("/items-orders-context", () => apiGetWithPagination<Item[]>("/items?per_page=500"));
  const { data: projectsData } = useSWR("/projects-orders-context", () =>
    apiGetAllPages<ProjectRow>("/projects?per_page=200"),
  );

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
      nextSelections[key] = row.suggested_match ? previewMatchToCatalogResult(row.suggested_match) : null;
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
      row.suggested_match ? previewMatchToCatalogResult(row.suggested_match) : null,
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
          }),
        ),
    );
    return (importPreview.locked_purchase_orders ?? []).filter((locked) => keys.has(purchaseOrderPreviewKey(locked)));
  }

  function canOfferAliasSave(row: OrderImportPreviewRow, selected: CatalogSearchResult | null): boolean {
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
        previews.push(await apiSendForm<OrderImportPreview>("/purchase-order-lines/import-preview", form));
      }
      const result = mergeOrderImportPreviews(previews);
      applyImportPreview(result);
      setMessage(
        result.can_auto_accept
          ? `Preview ready: files=${files.length}, rows=${result.summary.total_rows} are auto-acceptable.`
          : `Preview ready: files=${files.length}, rows=${result.summary.total_rows}, review=${result.summary.needs_review}, unresolved=${result.summary.unresolved}.`,
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
      (locked) => !previewUnlocks[purchaseOrderPreviewKey(locked)],
    );
    if (unresolvedLocks.length > 0) {
      setMessage(
        `Unlock locked purchase orders before import: ${unresolvedLocks
          .map((locked) => locked.purchase_order_number)
          .join(", ")}`,
      );
      return;
    }

    const unresolvedRows = importPreview.rows.filter((row) => !selectedPreviewMatch(row));
    if (unresolvedRows.length > 0) {
      setMessage(`Resolve preview rows before import: ${unresolvedRows.map((row) => row.row).join(", ")}`);
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
            `Missing items detected (${result.missing_count}) in ${file.name}. Download the generated CSV, update it, then import it from Items.`,
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
          : `Imported ${totalImportedCount} rows across ${files.length} file(s).`,
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

      <OrderLinesSection
        ref={orderLinesSectionRef}
        ordersData={ordersData}
        error={error}
        isLoading={isLoading}
        itemsData={itemsData}
        projectsData={projectsData}
        refreshOrderViews={refreshOrderViews}
        setMessage={setMessage}
      />

      <section className="grid gap-4 xl:grid-cols-2 xl:items-start">
        <QuotationSection
          ordersData={ordersData}
          quotationsData={quotationsData}
          quotationsLoading={quotationsLoading}
          quotationsError={quotationsError}
          refreshOrderViews={refreshOrderViews}
          setMessage={setMessage}
        />

        <PurchaseOrdersSection
          ordersData={ordersData}
          purchaseOrdersData={purchaseOrdersData}
          purchaseOrdersLoading={purchaseOrdersLoading}
          purchaseOrdersError={purchaseOrdersError}
          quotationsData={quotationsData}
          refreshOrderViews={refreshOrderViews}
          setMessage={setMessage}
          onOpenOrderDetails={(orderId) => orderLinesSectionRef.current?.openOrderDetails(orderId)}
        />
      </section>
    </div>
  );
}
