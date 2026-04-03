import { FormEvent, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { useLocation } from "react-router-dom";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { ImportPreviewSummary } from "@/components/ImportPreviewSummary";
import { apiDownload, apiGetAllPages, apiGetWithPagination, apiSend, apiSendForm } from "@/lib/api";
import { CatalogPicker } from "@/components/CatalogPicker";
import { formatActionError, resolvePreviewSelection } from "@/lib/previewState";
import { previewStatusTone } from "@/lib/previewStatus";
import type { CatalogSearchResult, Item, Order, ProjectRow, Reservation } from "@/lib/types";

type ReservationRow = {
  item_id: string;
  quantity: string;
  purpose: string;
  deadline: string;
  note: string;
  project_id: string;
};

type ReservationImportPreviewRow = {
  row: number;
  quantity: string;
  item_id: string;
  assembly: string;
  assembly_quantity: string;
  purpose: string | null;
  deadline: string | null;
  note: string | null;
  project_id: string | null;
  status: "exact" | "high_confidence" | "needs_review" | "unresolved";
  message: string;
  blocking: boolean;
  requires_user_selection: boolean;
  allowed_entity_types: Array<"item">;
  suggested_match: CatalogSearchResult | null;
  generated_reservations: Array<{
    item_id: number;
    item_number: string;
    manufacturer_name: string;
    quantity: number;
  }>;
};

type ReservationImportPreview = {
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
  rows: ReservationImportPreviewRow[];
};

const blankRow = (): ReservationRow => ({
  item_id: "",
  quantity: "",
  purpose: "",
  deadline: "",
  note: "",
  project_id: "",
});

function itemToCatalogResult(item: Item): CatalogSearchResult {
  return {
    entity_type: "item",
    entity_id: item.item_id,
    value_text: item.item_number,
    display_label: `${item.item_number} (${item.manufacturer_name}) #${item.item_id}`,
    summary: [item.category, `#${item.item_id}`].filter(Boolean).join(" | "),
    match_source: "item_number",
  };
}

export function ReservationsPage() {
  const location = useLocation();
  const [bulkRows, setBulkRows] = useState<ReservationRow[]>([
    blankRow(),
    blankRow(),
    blankRow(),
    blankRow()
  ]);
  const [loading, setLoading] = useState(false);
  const [reservationCsvFile, setReservationCsvFile] = useState<File | null>(null);
  const [reservationMessage, setReservationMessage] = useState("");
  const [reservationPreview, setReservationPreview] = useState<ReservationImportPreview | null>(null);
  const [reservationPreviewSelections, setReservationPreviewSelections] = useState<
    Record<number, CatalogSearchResult | null>
  >({});
  const { data, error, isLoading, mutate: mutateReservations } = useSWR("/reservations", () =>
    apiGetWithPagination<Reservation[]>("/reservations?per_page=200")
  );
  const { data: itemsResp } = useSWR("/items-options-reservations", () =>
    apiGetWithPagination<Item[]>("/items?per_page=1000")
  );
  const { data: projectsResp } = useSWR("/projects-options-reservations", () =>
    apiGetAllPages<ProjectRow>("/projects?per_page=200")
  );
  const { data: openOrders } = useSWR("/purchase-order-lines-open-options-reservations", () =>
    apiGetAllPages<Order>("/purchase-order-lines?include_arrived=false&per_page=200")
  );
  const { data: allReservations, mutate: mutateReservationSummary } = useSWR(
    "/reservations-summary-options",
    () => apiGetAllPages<Reservation>("/reservations?per_page=200")
  );
  const items = useMemo(() => itemsResp?.data ?? [], [itemsResp]);
  const projects = useMemo(() => projectsResp ?? [], [projectsResp]);
  const openOrderRows = useMemo(() => openOrders ?? [], [openOrders]);
  const allReservationRows = useMemo(() => allReservations ?? [], [allReservations]);
  const itemCatalogById = useMemo(
    () => new Map(items.map((item) => [item.item_id, itemToCatalogResult(item)])),
    [items]
  );

  const provisionalSummary = useMemo(() => {
    const reservations = allReservationRows.filter((row) => row.status === "ACTIVE");
    const projectRows = new Map<
      number,
      {
        project_id: number;
        project_name: string;
        active_reserved_quantity: number;
        active_reservation_count: number;
        open_incoming_dedicated_quantity: number;
      }
    >();
    let activeProvisionalQuantity = 0;
    let activeProvisionalCount = 0;
    let openIncomingDedicatedQuantity = 0;
    let openIncomingUncommittedQuantity = 0;

    for (const row of reservations) {
      if (!row.project_id) continue;
      activeProvisionalQuantity += row.quantity;
      activeProvisionalCount += 1;
      const existing = projectRows.get(row.project_id) ?? {
        project_id: row.project_id,
        project_name: row.project_name ?? `(project #${row.project_id})`,
        active_reserved_quantity: 0,
        active_reservation_count: 0,
        open_incoming_dedicated_quantity: 0,
      };
      existing.active_reserved_quantity += row.quantity;
      existing.active_reservation_count += 1;
      projectRows.set(row.project_id, existing);
    }

    for (const order of openOrderRows) {
      if (order.status !== "Ordered") continue;
      if (order.project_id) {
        openIncomingDedicatedQuantity += order.order_amount;
        const existing = projectRows.get(order.project_id) ?? {
          project_id: order.project_id,
          project_name: order.project_name ?? `(project #${order.project_id})`,
          active_reserved_quantity: 0,
          active_reservation_count: 0,
          open_incoming_dedicated_quantity: 0,
        };
        existing.open_incoming_dedicated_quantity += order.order_amount;
        projectRows.set(order.project_id, existing);
      } else {
        openIncomingUncommittedQuantity += order.order_amount;
      }
    }

    const rows = Array.from(projectRows.values()).sort((a, b) =>
      a.project_name.localeCompare(b.project_name)
    );
    return {
      active_provisional_quantity: activeProvisionalQuantity,
      active_provisional_count: activeProvisionalCount,
      open_incoming_dedicated_quantity: openIncomingDedicatedQuantity,
      open_incoming_uncommitted_quantity: openIncomingUncommittedQuantity,
      rows,
    };
  }, [allReservationRows, openOrderRows]);

  useEffect(() => {
    if (!location.search) return;
    const params = new URLSearchParams(location.search);
    const hasPrefill =
      params.has("item_id") ||
      params.has("quantity") ||
      params.has("purpose") ||
      params.has("deadline") ||
      params.has("note") ||
      params.has("project_id");
    if (!hasPrefill) return;

    const itemIdRaw = params.get("item_id");
    const quantityRaw = params.get("quantity");
    const projectIdRaw = params.get("project_id");
    const sourceOrderIdRaw = params.get("source_purchase_order_line_id");

    const next: ReservationRow = {
      ...blankRow(),
      item_id:
        itemIdRaw && Number.isFinite(Number(itemIdRaw)) && Number(itemIdRaw) > 0 ? itemIdRaw : "",
      quantity:
        quantityRaw && Number.isFinite(Number(quantityRaw)) && Number(quantityRaw) > 0 ? quantityRaw : "",
      purpose: params.get("purpose")?.trim() ?? "",
      deadline: params.get("deadline")?.trim() ?? "",
      note: params.get("note")?.trim() ?? "",
      project_id:
        projectIdRaw && Number.isFinite(Number(projectIdRaw)) && Number(projectIdRaw) > 0
          ? projectIdRaw
          : "",
    };

    setBulkRows((prev) => {
      if (!prev.length) return [next];
      const copy = [...prev];
      copy[0] = { ...copy[0], ...next };
      return copy;
    });

    if (sourceOrderIdRaw && Number.isFinite(Number(sourceOrderIdRaw))) {
      setReservationMessage(
        `Prefilled from purchase order line #${sourceOrderIdRaw}. Confirm item/qty/project before submitting.`
      );
    } else {
      setReservationMessage("Prefilled reservation entry. Confirm values before submitting.");
    }
  }, [location.search]);

  function updateBulkRow(index: number, patch: Partial<ReservationRow>) {
    setBulkRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeBulkRow(index: number) {
    setBulkRows((prev) => prev.filter((_, i) => i !== index));
  }

  function resetReservationPreview() {
    setReservationPreview(null);
    setReservationPreviewSelections({});
  }

  function applyReservationPreview(preview: ReservationImportPreview) {
    const nextSelections: Record<number, CatalogSearchResult | null> = {};
    for (const row of preview.rows) {
      nextSelections[row.row] = row.suggested_match;
    }
    setReservationPreview(preview);
    setReservationPreviewSelections(nextSelections);
  }

  function downloadProvisionalSummaryCsv() {
    const timestamp = new Date().toISOString();
    const header = [
      "project_id",
      "project_name",
      "active_provisional_reserved_qty",
      "active_provisional_reservation_count",
      "open_incoming_dedicated_qty",
      "open_incoming_uncommitted_qty",
      "generated_at",
    ];
    const csvRows = [header.join(",")];
    for (const row of provisionalSummary.rows) {
      csvRows.push(
        [
          row.project_id,
          `"${(row.project_name ?? "").replace(/"/g, '""')}"`,
          row.active_reserved_quantity,
          row.active_reservation_count,
          row.open_incoming_dedicated_quantity,
          "",
          timestamp,
        ].join(",")
      );
    }
    csvRows.push(
      [
        "",
        '"(UNCOMMITTED_INCOMING_POOL)"',
        "",
        "",
        "",
        provisionalSummary.open_incoming_uncommitted_quantity,
        timestamp,
      ].join(",")
    );
    const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "provisional_allocation_summary.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  function selectedReservationPreviewMatch(
    row: ReservationImportPreviewRow
  ): CatalogSearchResult | null {
    return resolvePreviewSelection(
      reservationPreviewSelections,
      row.row,
      row.suggested_match ?? null
    );
  }

  async function revalidateReservationViews() {
    await Promise.all([mutateReservations(), mutateReservationSummary()]);
  }

  async function createBulk() {
    const reservations = bulkRows
      .filter((row) => row.item_id && row.quantity)
      .map((row) => ({
        item_id: Number(row.item_id),
        quantity: Number(row.quantity),
        purpose: row.purpose.trim() || null,
        deadline: row.deadline.trim() || null,
        note: row.note.trim() || null,
        project_id: row.project_id ? Number(row.project_id) : null,
      }));
    if (!reservations.length) return;
    setLoading(true);
    try {
      await apiSend("/reservations/batch", {
        method: "POST",
        body: JSON.stringify({ reservations })
      });
      setBulkRows([blankRow(), blankRow(), blankRow(), blankRow()]);
      await revalidateReservationViews();
    } finally {
      setLoading(false);
    }
  }

  async function previewReservationCsv(event: FormEvent) {
    event.preventDefault();
    if (!reservationCsvFile) return;
    const formData = new FormData();
    formData.append("file", reservationCsvFile);
    setLoading(true);
    setReservationMessage("");
    resetReservationPreview();
    try {
      const result = await apiSendForm<ReservationImportPreview>(
        "/reservations/import-preview",
        formData
      );
      applyReservationPreview(result);
      setReservationMessage(
        result.can_auto_accept
          ? `Preview ready: ${result.summary.total_rows} row(s) are ready to import.`
          : `Preview ready: review=${result.summary.needs_review}, unresolved=${result.summary.unresolved}.`
      );
    } catch (error) {
      setReservationMessage(formatActionError("Preview failed", error));
    } finally {
      setLoading(false);
    }
  }

  async function confirmReservationPreview() {
    if (!reservationCsvFile || !reservationPreview) return;
    const missingSelection = reservationPreview.rows.find(
      (row) => row.requires_user_selection && !selectedReservationPreviewMatch(row)
    );
    if (missingSelection) {
      setReservationMessage(`Row ${missingSelection.row}: choose an item or assembly first.`);
      return;
    }
    const nonFixableBlocking = reservationPreview.rows.find(
      (row) => row.blocking && !row.requires_user_selection
    );
    if (nonFixableBlocking) {
      setReservationMessage(`Row ${nonFixableBlocking.row}: ${nonFixableBlocking.message}`);
      return;
    }

    const rowOverrides: Record<number, { item_id?: number; assembly_id?: number }> = {};
    for (const row of reservationPreview.rows) {
      const selection = selectedReservationPreviewMatch(row);
      if (!selection) continue;
      const changedSelection =
        row.requires_user_selection ||
        selection.entity_id !== row.suggested_match?.entity_id ||
        selection.entity_type !== row.suggested_match?.entity_type;
      if (!changedSelection) continue;
      if (selection.entity_type === "item") {
        rowOverrides[row.row] = { item_id: selection.entity_id };
      } else if (selection.entity_type === "assembly") {
        rowOverrides[row.row] = { assembly_id: selection.entity_id };
      }
    }

    const formData = new FormData();
    formData.append("file", reservationCsvFile);
    if (Object.keys(rowOverrides).length > 0) {
      formData.append("row_overrides", JSON.stringify(rowOverrides));
    }
    setLoading(true);
    setReservationMessage("");
    try {
      const result = await apiSendForm<Reservation[]>("/reservations/import-csv", formData);
      setReservationMessage(`Imported ${result.length} reservation row(s).`);
      setReservationCsvFile(null);
      resetReservationPreview();
      await revalidateReservationViews();
    } catch (error) {
      setReservationMessage(formatActionError("Import failed", error));
    } finally {
      setLoading(false);
    }
  }

  async function release(id: number, maxQuantity: number) {
    const quantityText = window.prompt(
      `Release quantity (1-${maxQuantity}, leave blank for full release):`,
      ""
    );
    if (quantityText === null) return;
    const quantity = quantityText.trim() === "" ? null : Number(quantityText);
    if (quantity !== null && (!Number.isInteger(quantity) || quantity <= 0)) {
      window.alert("Quantity must be a positive integer.");
      return;
    }
    if (quantity !== null && quantity > maxQuantity) {
      window.alert(`Quantity cannot exceed remaining reservation quantity (${maxQuantity}).`);
      return;
    }
    setLoading(true);
    try {
      await apiSend(`/reservations/${id}/release`, {
        method: "POST",
        body: JSON.stringify(quantity === null ? {} : { quantity })
      });
      await revalidateReservationViews();
    } finally {
      setLoading(false);
    }
  }

  async function consume(id: number, maxQuantity: number) {
    const quantityText = window.prompt(
      `Consume quantity (1-${maxQuantity}, leave blank for full consume):`,
      ""
    );
    if (quantityText === null) return;
    const quantity = quantityText.trim() === "" ? null : Number(quantityText);
    if (quantity !== null && (!Number.isInteger(quantity) || quantity <= 0)) {
      window.alert("Quantity must be a positive integer.");
      return;
    }
    if (quantity !== null && quantity > maxQuantity) {
      window.alert(`Quantity cannot exceed remaining reservation quantity (${maxQuantity}).`);
      return;
    }
    setLoading(true);
    try {
      await apiSend(`/reservations/${id}/consume`, {
        method: "POST",
        body: JSON.stringify(quantity === null ? {} : { quantity })
      });
      await revalidateReservationViews();
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Reservations</h1>
        <p className="mt-1 text-sm text-slate-600">
          Reserve stock for near-term execution and handle release or consume transitions.
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Use <span className="font-semibold">Projects</span> for demand planning first, then reserve
          concrete quantities here once work is ready.
        </p>
      </section>



      <section className="panel grid gap-3 p-4">
        <h2 className="font-display text-lg font-semibold">CSV Import (Reservations)</h2>
        <p className="text-xs text-slate-500">
          Columns: item_id, quantity, purpose, deadline, note, project_id(optional)
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            className="button-subtle"
            type="button"
            onClick={() =>
              void apiDownload(
                "/reservations/import-template",
                "reservations_import_template.csv"
              ).catch((error) => {
                window.alert(error instanceof Error ? error.message : String(error));
              })
            }
          >
            Download Template CSV
          </button>
          <button
            className="button-subtle"
            type="button"
            onClick={() =>
              void apiDownload(
                "/reservations/import-reference",
                "reservations_import_reference.csv"
              ).catch((error) => {
                window.alert(error instanceof Error ? error.message : String(error));
              })
            }
          >
            Download Reference CSV
          </button>
        </div>
        <form className="grid gap-2" onSubmit={previewReservationCsv}>
          <input
            className="input"
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              setReservationCsvFile(e.target.files?.[0] ?? null);
              resetReservationPreview();
            }}
            required
          />
          <button className="button" disabled={loading || !reservationCsvFile} type="submit">
            Preview Import
          </button>
        </form>
        {reservationMessage && <p className="text-sm text-signal">{reservationMessage}</p>}
        {reservationPreview && (
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <ImportPreviewSummary summary={reservationPreview.summary} />
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-[1100px] text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="px-2 py-2">Row</th>
                    <th className="px-2 py-2">Raw Input</th>
                    <th className="px-2 py-2">Expanded Result</th>
                    <th className="px-2 py-2">Status</th>
                    <th className="px-2 py-2">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {reservationPreview.rows.map((row) => (
                    <tr key={row.row} className="border-b border-slate-100 align-top">
                      <td className="px-2 py-3 font-semibold">#{row.row}</td>
                      <td className="px-2 py-3">
                        <div className="space-y-1">
                          <p className="font-semibold text-slate-900">
                            {row.item_id ? `item_id ${row.item_id}` : row.assembly || "No target"}
                          </p>
                          <p className="text-xs text-slate-500">
                            qty {row.quantity}
                          </p>
                          {row.purpose && <p className="text-xs text-slate-500">{row.purpose}</p>}
                          {row.deadline && <p className="text-xs text-slate-500">deadline {row.deadline}</p>}
                          {row.project_id && <p className="text-xs text-slate-500">project #{row.project_id}</p>}
                        </div>
                      </td>
                      <td className="px-2 py-3">
                        {row.generated_reservations.length > 0 ? (
                          <div className="space-y-1">
                            {row.generated_reservations.map((generated) => (
                              <p key={`${row.row}-${generated.item_id}`} className="text-xs text-slate-600">
                                {generated.item_number} ({generated.manufacturer_name}) x {generated.quantity}
                              </p>
                            ))}
                          </div>
                        ) : row.suggested_match ? (
                          <div className="space-y-1">
                            <p className="font-semibold text-slate-900">
                              {row.suggested_match.display_label}
                            </p>
                            {row.suggested_match.summary && (
                              <p className="text-xs text-slate-500">{row.suggested_match.summary}</p>
                            )}
                          </div>
                        ) : (
                          <p className="text-sm text-slate-500">No resolved target</p>
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
                          {row.allowed_entity_types.length > 0 && (
                            <CatalogPicker
                              allowedTypes={row.allowed_entity_types}
                              onChange={(value) =>
                                setReservationPreviewSelections((prev) => ({
                                  ...prev,
                                  [row.row]: value,
                                }))
                              }
                              placeholder="Select item"
                              recentKey="reservations-import-preview-target"
                              value={selectedReservationPreviewMatch(row)}
                            />
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button className="button" disabled={loading} onClick={() => void confirmReservationPreview()} type="button">
                Confirm Import
              </button>
              <button className="button-subtle" disabled={loading} onClick={resetReservationPreview} type="button">
                Clear Preview
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="panel space-y-3 p-4">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-lg font-semibold">Reservation Entry</h2>
          <button
            className="button-subtle"
            onClick={() => setBulkRows((prev) => [...prev, blankRow()])}
          >
            Add Row
          </button>
        </div>
        <p className="text-xs text-slate-500">
          Single-item and multi-item reservations are both handled here.
        </p>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="px-2 py-2">Item</th>
                <th className="px-2 py-2">Qty</th>
                <th className="px-2 py-2">Purpose</th>
                <th className="px-2 py-2">Deadline</th>
                <th className="px-2 py-2">Note</th>
                <th className="px-2 py-2">Project (optional)</th>
                <th className="px-2 py-2">-</th>
              </tr>
            </thead>
            <tbody>
              {bulkRows.map((row, idx) => (
                <tr key={idx} className="border-b border-slate-100">
                  <td className="px-2 py-2">
                    <CatalogPicker
                      allowedTypes={["item"]}
                      onChange={(value) =>
                        updateBulkRow(idx, { item_id: value ? String(value.entity_id) : "" })
                      }
                      placeholder="Search items"
                      recentKey="reservations-entry-item"
                      value={row.item_id ? itemCatalogById.get(Number(row.item_id)) ?? null : null}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      type="number"
                      min={1}
                      value={row.quantity}
                      onChange={(e) => updateBulkRow(idx, { quantity: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      value={row.purpose}
                      onChange={(e) => updateBulkRow(idx, { purpose: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      type="date"
                      value={row.deadline}
                      onChange={(e) => updateBulkRow(idx, { deadline: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      value={row.note}
                      onChange={(e) => updateBulkRow(idx, { note: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <select
                      className="input"
                      value={row.project_id}
                      onChange={(e) => updateBulkRow(idx, { project_id: e.target.value })}
                    >
                      <option value="">Generic (no project)</option>
                      {projects.map((project) => (
                        <option key={project.project_id} value={project.project_id}>
                          {project.name} (#{project.project_id}, {project.status})
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-2">
                    <button className="button-subtle" onClick={() => removeBulkRow(idx)}>
                      Del
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button className="button" disabled={loading} onClick={createBulk}>
          Submit Batch
        </button>
      </section>

      <section className="panel space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-lg font-semibold">Provisional Allocation Summary</h2>
          <button type="button" className="button-subtle" onClick={downloadProvisionalSummaryCsv}>
            Export Summary CSV
          </button>
        </div>
        <p className="text-xs text-slate-500">
          Tracks project-linked ACTIVE reservations and open incoming supply split into dedicated vs uncommitted pools.
        </p>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded border border-slate-200 bg-slate-50 p-3 text-sm">
            <p className="text-xs text-slate-500">Active provisional reserved qty</p>
            <p className="font-semibold">{provisionalSummary.active_provisional_quantity}</p>
          </div>
          <div className="rounded border border-slate-200 bg-slate-50 p-3 text-sm">
            <p className="text-xs text-slate-500">Active provisional reservations</p>
            <p className="font-semibold">{provisionalSummary.active_provisional_count}</p>
          </div>
          <div className="rounded border border-slate-200 bg-slate-50 p-3 text-sm">
            <p className="text-xs text-slate-500">Open incoming dedicated qty</p>
            <p className="font-semibold">{provisionalSummary.open_incoming_dedicated_quantity}</p>
          </div>
          <div className="rounded border border-slate-200 bg-slate-50 p-3 text-sm">
            <p className="text-xs text-slate-500">Open incoming uncommitted qty</p>
            <p className="font-semibold">{provisionalSummary.open_incoming_uncommitted_quantity}</p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="px-2 py-2">Project</th>
                <th className="px-2 py-2">Active Reserved Qty</th>
                <th className="px-2 py-2">Active Reservations</th>
                <th className="px-2 py-2">Open Incoming Dedicated Qty</th>
              </tr>
            </thead>
            <tbody>
              {provisionalSummary.rows.length ? (
                provisionalSummary.rows.map((row) => (
                  <tr key={row.project_id} className="border-b border-slate-100">
                    <td className="px-2 py-2">
                      {row.project_name} (#{row.project_id})
                    </td>
                    <td className="px-2 py-2">{row.active_reserved_quantity}</td>
                    <td className="px-2 py-2">{row.active_reservation_count}</td>
                    <td className="px-2 py-2">{row.open_incoming_dedicated_quantity}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="px-2 py-2 text-slate-500" colSpan={4}>
                    No project-linked provisional reservations or dedicated incoming orders yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Reservation List</h2>
        {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {error && <ApiErrorNotice error={error} area="reservation data" />}
        {data?.data && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">ID</th>
                  <th className="px-2 py-2">Item</th>
                  <th className="px-2 py-2">Qty</th>
                  <th className="px-2 py-2">Purpose</th>
                  <th className="px-2 py-2">Deadline</th>
                  <th className="px-2 py-2">Project</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.data.map((row) => (
                  <tr key={row.reservation_id} className="border-b border-slate-100">
                    <td className="px-2 py-2">#{row.reservation_id}</td>
                    <td className="px-2 py-2">{row.item_number}</td>
                    <td className="px-2 py-2">{row.quantity}</td>
                    <td className="px-2 py-2">{row.purpose ?? "-"}</td>
                    <td className="px-2 py-2">{row.deadline ?? "-"}</td>
                    <td className="px-2 py-2">
                      {row.project_id ? `${row.project_name ?? "(unnamed)"} (#${row.project_id})` : "-"}
                    </td>
                    <td className="px-2 py-2">{row.status}</td>
                    <td className="px-2 py-2">
                      {row.status === "ACTIVE" ? (
                        <div className="flex gap-2">
                          <button
                            className="button-subtle"
                            onClick={() => release(row.reservation_id, row.quantity)}
                            disabled={loading}
                          >
                            Release...
                          </button>
                          <button
                            className="button-subtle"
                            onClick={() => consume(row.reservation_id, row.quantity)}
                            disabled={loading}
                          >
                            Consume...
                          </button>
                        </div>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
