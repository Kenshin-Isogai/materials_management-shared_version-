import { FormEvent, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import useSWR from "swr";
import { apiGetWithPagination, apiSend, apiSendForm } from "../lib/api";
import type { MissingItemResolverRow, Order, Quotation } from "../lib/types";

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
  rows?: MissingItemResolverRow[];
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

function csvEscape(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, "\"\"")}"`;
  }
  return value;
}

function downloadTemplateCsv(
  filename: string,
  headers: string[],
  sampleRow: Record<string, string>
) {
  const headerLine = headers.map(csvEscape).join(",");
  const dataLine = headers.map((key) => csvEscape(sampleRow[key] ?? "")).join(",");
  const csv = `${headerLine}\n${dataLine}\n`;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

export function OrdersPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [supplier, setSupplier] = useState("");
  const [defaultDate, setDefaultDate] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [unregisteredRoot, setUnregisteredRoot] = useState("");
  const [registeredRoot, setRegisteredRoot] = useState("");
  const [message, setMessage] = useState<string>("");
  const [missingRows, setMissingRows] = useState<MissingItemResolverRow[]>([]);
  const [batchMissingReports, setBatchMissingReports] = useState<UnregisteredFileReport[]>([]);
  const [batchErrorReports, setBatchErrorReports] = useState<BatchErrorReport[]>([]);
  const [batchWarnings, setBatchWarnings] = useState<string[]>([]);
  const [batchNormalizations, setBatchNormalizations] = useState<BatchNormalization[]>([]);
  const [showAdvancedBatch, setShowAdvancedBatch] = useState(false);
  const [loading, setLoading] = useState(false);
  const [editingQuotationId, setEditingQuotationId] = useState<number | null>(null);
  const [editingQuotationPdfLink, setEditingQuotationPdfLink] = useState("");
  const [editingQuotationIssueDate, setEditingQuotationIssueDate] = useState("");
  const [sortKey, setSortKey] = useState<"order_id" | "supplier_name" | "canonical_item_number" | "order_amount" | "expected_arrival" | "status">("order_id");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [quotationSortKey, setQuotationSortKey] = useState<"quotation_id" | "supplier_name" | "quotation_number" | "issue_date" | "pdf_link">("quotation_id");
  const [quotationSortDirection, setQuotationSortDirection] = useState<"asc" | "desc">("desc");
  const [quotationNumberSearch, setQuotationNumberSearch] = useState("");
  const [quotationFilter, setQuotationFilter] = useState("");
  const [isOrderListExpanded, setIsOrderListExpanded] = useState(false);

  const { data, error, isLoading, mutate: mutateOrders } = useSWR("/orders", () =>
    apiGetWithPagination<Order[]>("/orders?per_page=200")
  );
  const {
    data: quotationsData,
    error: quotationsError,
    isLoading: quotationsLoading,
    mutate: mutateQuotations,
  } = useSWR("/quotations", () => apiGetWithPagination<Quotation[]>("/quotations?per_page=200"));

  const sortedOrders = useMemo(() => {
    const rows = [...(data?.data ?? [])];
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
  }, [data?.data, sortDirection, sortKey]);

  const filteredSortedQuotations = useMemo(() => {
    const numberQuery = quotationNumberSearch.trim().toLowerCase();
    const filterQuery = quotationFilter.trim().toLowerCase();
    const rows = (quotationsData?.data ?? []).filter((row) => {
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
  }, [quotationsData?.data, quotationFilter, quotationNumberSearch, quotationSortDirection, quotationSortKey]);

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

  async function submitImport(event: FormEvent) {
    event.preventDefault();
    if (!file || !supplier.trim()) return;
    setLoading(true);
    setMessage("");
    setMissingRows([]);
    sessionStorage.removeItem(PENDING_BATCH_RETRY_KEY);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("supplier_name", supplier);
      if (defaultDate.trim()) form.append("default_order_date", defaultDate.trim());
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
        setMissingRows([]);
        sessionStorage.removeItem(PENDING_MISSING_ITEMS_KEY);
        sessionStorage.removeItem(PENDING_ORDER_IMPORT_KEY);
        sessionStorage.removeItem(PENDING_BATCH_RETRY_KEY);
        setMessage(`Imported ${result.imported_count ?? 0} rows.`);
      }
      await Promise.all([mutateOrders(), mutateQuotations()]);
    } catch (error) {
      const messageText = String(error ?? "");
      if (messageText.includes("quotations/registered/pdf_files")) {
        setMessage(
          "Import failed: Manual import requires pdf_link to be blank, filename-only, or quotations/registered/pdf_files/<supplier>/<file>.pdf. " +
          "For unregistered folder CSV files, use 'Unregistered Folder Batch'."
        );
      } else {
        setMessage(`Import failed: ${messageText}`);
      }
    } finally {
      setLoading(false);
    }
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

  async function runRegisterUnregisteredMissing() {
    setLoading(true);
    setMessage("");
    setBatchMissingReports([]);
    setBatchErrorReports([]);
    setBatchWarnings([]);
    setBatchNormalizations([]);
    try {
      const result = await apiSend<RegisterBatchResult>("/orders/register-unregistered-missing", {
        method: "POST",
        body: JSON.stringify({
          unregistered_root: unregisteredRoot || null,
          registered_root: registeredRoot || null,
          continue_on_error: true
        })
      });
      setBatchWarnings(uniqueWarnings(result.warnings ?? []));
      setBatchNormalizations(uniqueNormalizations(result.normalizations ?? []));
      setBatchErrorReports(toBatchErrorReports("register", result.files));
      setMessage(
        `Missing registration batch: status=${result.status}, processed=${result.processed}, succeeded=${result.succeeded}, failed=${result.failed}`
      );
      await Promise.all([mutateOrders(), mutateQuotations()]);
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
      const registerResult = await apiSend<RegisterBatchResult>("/orders/register-unregistered-missing", {
        method: "POST",
        body: JSON.stringify({
          unregistered_root: null,
          registered_root: null,
          continue_on_error: true
        })
      });
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
      setBatchErrorReports([
        ...toBatchErrorReports("register", registerResult.files),
        ...toBatchErrorReports("import", importResult.files),
      ]);

      const mergedWarnings = uniqueWarnings([
        ...(registerResult.warnings ?? []),
        ...(importResult.warnings ?? [])
      ]);
      const mergedNormalizations = uniqueNormalizations([
        ...(registerResult.normalizations ?? []),
        ...(importResult.normalizations ?? [])
      ]);
      setBatchWarnings(mergedWarnings);
      setBatchNormalizations(mergedNormalizations);
      setMessage(
        `Unregistered batch complete: register(status=${registerResult.status}, processed=${registerResult.processed}, succeeded=${registerResult.succeeded}, failed=${registerResult.failed}) + import(status=${importResult.status}, processed=${importResult.processed}, succeeded=${importResult.succeeded}, missing_items=${importResult.missing_items}, failed=${importResult.failed})`
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
            <code>{"quotations/registered/pdf_files/<supplier>/<file>.pdf"}</code> or blank.
          </p>
          <p>
            If you provide only a filename like <code>Q-2026-001.pdf</code>, it is auto-normalized
            to the canonical registered path for the selected supplier.
          </p>
          <button
            className="button-subtle mt-2"
            type="button"
            onClick={() =>
              downloadTemplateCsv(
                "order_import_template.csv",
                [
                  "item_number",
                  "quantity",
                  "quotation_number",
                  "issue_date",
                  "order_date",
                  "expected_arrival",
                  "pdf_link"
                ],
                {
                  item_number: "LENS-001",
                  quantity: "5",
                  quotation_number: "Q-2026-001",
                  issue_date: "2026-02-23",
                  order_date: "2026-02-23",
                  expected_arrival: "2026-03-01",
                  pdf_link: "quotations/registered/pdf_files/Thorlabs/Q-2026-001.pdf"
                }
              )
            }
          >
            Download Template CSV
          </button>
        </div>
        <form className="grid gap-3 md:grid-cols-4" onSubmit={submitImport}>
          <input
            className="input"
            placeholder="Supplier name"
            value={supplier}
            onChange={(e) => setSupplier(e.target.value)}
            required
          />
          <input
            className="input"
            type="date"
            value={defaultDate}
            onChange={(e) => setDefaultDate(e.target.value)}
          />
          <input
            className="input"
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            required
          />
          <button className="button" disabled={loading} type="submit">
            Import
          </button>
        </form>
        {message && <p className="mt-3 text-sm text-signal">{message}</p>}
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
          <code>{"quotations/unregistered/csv_files/<supplier>/*.csv"}</code>
          {" "}
          and
          {" "}
          <code>{"quotations/unregistered/pdf_files/<supplier>/*"}</code>
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
              <button className="button-subtle" onClick={runRegisterUnregisteredMissing} disabled={loading}>
                Register Missing CSVs
              </button>
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
            {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
            {error && <p className="text-sm text-red-600">{String(error)}</p>}
            {data?.data && (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-slate-500">
                      <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("order_id")}>Order {sortIndicator("order_id")}</button></th>
                      <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("supplier_name")}>Supplier {sortIndicator("supplier_name")}</button></th>
                      <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("canonical_item_number")}>Item {sortIndicator("canonical_item_number")}</button></th>
                      <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("order_amount")}>Qty {sortIndicator("order_amount")}</button></th>
                      <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("expected_arrival")}>Expected {sortIndicator("expected_arrival")}</button></th>
                      <th className="px-2 py-2"><button type="button" onClick={() => toggleSort("status")}>Status {sortIndicator("status")}</button></th>
                      <th className="px-2 py-2">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedOrders.map((row) => (
                      <tr key={row.order_id} className="border-b border-slate-100">
                        <td className="px-2 py-2">#{row.order_id}</td>
                        <td className="px-2 py-2">{row.supplier_name}</td>
                        <td className="px-2 py-2 font-semibold">{row.canonical_item_number}</td>
                        <td className="px-2 py-2">{row.order_amount}</td>
                        <td className="px-2 py-2">{row.expected_arrival ?? "-"}</td>
                        <td className="px-2 py-2">{row.status}</td>
                        <td className="px-2 py-2">
                          <div className="flex gap-2">
                            {row.status === "Ordered" ? (
                              <button
                                className="button-subtle"
                                onClick={() => markArrived(row.order_id)}
                                disabled={loading}
                              >
                                Mark Arrived
                              </button>
                            ) : (
                              <span className="text-slate-400">-</span>
                            )}
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
            )}
          </>
        )}
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Imported Quotations</h2>
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
        {quotationsData?.data && (
          <>
            <p className="mb-2 text-xs text-slate-500">Showing {filteredSortedQuotations.length} / {quotationsData.data.length} quotations</p>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="px-2 py-2"><button type="button" onClick={() => toggleQuotationSort("quotation_id")}>ID {quotationSortIndicator("quotation_id")}</button></th>
                    <th className="px-2 py-2"><button type="button" onClick={() => toggleQuotationSort("supplier_name")}>Supplier {quotationSortIndicator("supplier_name")}</button></th>
                    <th className="px-2 py-2"><button type="button" onClick={() => toggleQuotationSort("quotation_number")}>Quotation # {quotationSortIndicator("quotation_number")}</button></th>
                    <th className="px-2 py-2"><button type="button" onClick={() => toggleQuotationSort("issue_date")}>Issue Date {quotationSortIndicator("issue_date")}</button></th>
                    <th className="px-2 py-2"><button type="button" onClick={() => toggleQuotationSort("pdf_link")}>PDF Link {quotationSortIndicator("pdf_link")}</button></th>
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
                          placeholder="quotations/registered/pdf_files/<supplier>/<file>.pdf"
                        />
                      ) : (
                        row.pdf_link ?? "-"
                      )}
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex gap-2">
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
      </section>
    </div>
  );
}
