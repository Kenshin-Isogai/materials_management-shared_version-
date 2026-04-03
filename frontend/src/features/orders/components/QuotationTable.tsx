import React from "react";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import type { Order, Quotation } from "@/lib/types";
import { summaryMetric, renderDocumentReference } from "@/features/orders/utils";

export type QuotationTableProps = {
  quotationsData: Quotation[] | undefined;
  filteredSortedQuotations: Quotation[];
  quotationOrders: Order[];
  selectedQuotation: Quotation | null;
  quotationsLoading: boolean;
  quotationsError: unknown;
  loading: boolean;
  selectedQuotationId: number | null;
  editingQuotationId: number | null;
  editingQuotationDocumentUrl: string;
  editingQuotationIssueDate: string;
  quotationNumberSearch: string;
  quotationFilter: string;
  orderCountByQuotationId: Map<number, number>;
  quotationDetailsRef: React.Ref<HTMLDivElement>;
  setQuotationNumberSearch: (value: string) => void;
  setQuotationFilter: (value: string) => void;
  setSelectedQuotationId: (id: number | null) => void;
  setEditingQuotationId: (id: number | null) => void;
  setEditingQuotationDocumentUrl: (value: string) => void;
  setEditingQuotationIssueDate: (value: string) => void;
  openQuotationDetails: (quotationId: number) => void;
  beginEditQuotation: (row: Quotation) => void;
  saveQuotationEdit: (quotationId: number) => void;
  deleteQuotation: (quotationId: number) => void;
};

export function QuotationTable({
  quotationsData,
  filteredSortedQuotations,
  quotationOrders,
  selectedQuotation,
  quotationsLoading,
  quotationsError,
  loading,
  selectedQuotationId,
  editingQuotationId,
  editingQuotationDocumentUrl,
  editingQuotationIssueDate,
  quotationNumberSearch,
  quotationFilter,
  orderCountByQuotationId,
  quotationDetailsRef,
  setQuotationNumberSearch,
  setQuotationFilter,
  setSelectedQuotationId,
  setEditingQuotationId,
  setEditingQuotationDocumentUrl,
  setEditingQuotationIssueDate,
  openQuotationDetails,
  beginEditQuotation,
  saveQuotationEdit,
  deleteQuotation,
}: QuotationTableProps) {
  return (
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
        {quotationsError ? <ApiErrorNotice error={quotationsError} area="quotation data" /> : null}
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
                  <p className="mt-1">{renderDocumentReference(selectedQuotation.quotation_document_url)}</p>
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
                  <input className="input" value={editingQuotationDocumentUrl} onChange={(event) => setEditingQuotationDocumentUrl(event.target.value)} placeholder="Document reference or https://..." />
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
