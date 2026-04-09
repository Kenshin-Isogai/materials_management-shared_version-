import { useMemo, useRef, useState } from "react";
import { apiSend } from "@/lib/api";
import type { Order, Quotation } from "@/lib/types";
import { QuotationTable } from "@/features/orders/components/QuotationTable";

type QuotationSectionProps = {
  ordersData: Order[] | undefined;
  quotationsData: Quotation[] | undefined;
  quotationsLoading: boolean;
  quotationsError: unknown;
  refreshOrderViews: () => Promise<unknown>;
  setMessage: (value: string) => void;
  onOpenOrderDetails: (orderId: number) => void;
};

export function QuotationSection({
  ordersData,
  quotationsData,
  quotationsLoading,
  quotationsError,
  refreshOrderViews,
  setMessage,
  onOpenOrderDetails,
}: QuotationSectionProps) {
  const [loading, setLoading] = useState(false);
  const [editingQuotationId, setEditingQuotationId] = useState<number | null>(null);
  const [editingQuotationDocumentUrl, setEditingQuotationDocumentUrl] = useState("");
  const [editingQuotationIssueDate, setEditingQuotationIssueDate] = useState("");
  const [quotationNumberSearch, setQuotationNumberSearch] = useState("");
  const [quotationFilter, setQuotationFilter] = useState("");
  const [selectedQuotationId, setSelectedQuotationId] = useState<number | null>(null);
  const quotationDetailsRef = useRef<HTMLDivElement | null>(null);

  const sortedOrders = useMemo(() => {
    const rows = [...(ordersData ?? [])];
    rows.sort((a, b) => b.order_id - a.order_id);
    return rows;
  }, [ordersData]);

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

    rows.sort((a, b) => b.quotation_id - a.quotation_id);
    return rows;
  }, [quotationsData, quotationFilter, quotationNumberSearch]);

  const orderCountByQuotationId = useMemo(() => {
    const counts = new Map<number, number>();
    for (const row of sortedOrders) {
      counts.set(row.quotation_id, (counts.get(row.quotation_id) ?? 0) + 1);
    }
    return counts;
  }, [sortedOrders]);

  const selectedQuotation = useMemo(
    () => (quotationsData ?? []).find((row) => row.quotation_id === selectedQuotationId) ?? null,
    [quotationsData, selectedQuotationId],
  );

  const quotationOrders = useMemo(() => {
    if (!selectedQuotationId) return [];
    return sortedOrders.filter((row) => row.quotation_id === selectedQuotationId);
  }, [selectedQuotationId, sortedOrders]);

  function scrollToSection(refObject: { current: HTMLElement | null }) {
    requestAnimationFrame(() => {
      refObject.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function openQuotationDetails(quotationId: number) {
    setMessage("");
    setSelectedQuotationId(quotationId);
    scrollToSection(quotationDetailsRef);
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

  return (
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
      openOrderDetails={onOpenOrderDetails}
      beginEditQuotation={beginEditQuotation}
      saveQuotationEdit={(id) => void saveQuotationEdit(id)}
      deleteQuotation={(id) => void deleteQuotation(id)}
    />
  );
}
