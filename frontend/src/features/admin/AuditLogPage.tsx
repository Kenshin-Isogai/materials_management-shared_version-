import { useState } from "react";
import useSWR from "swr";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { apiGetWithPagination, apiSend } from "@/lib/api";
import type { Transaction } from "@/lib/types";

export function HistoryPage() {
  const [busy, setBusy] = useState(false);
  const { data, error, isLoading, mutate } = useSWR("/transactions", () =>
    apiGetWithPagination<Transaction[]>("/transactions?per_page=200")
  );

  async function undo(logId: number) {
    setBusy(true);
    try {
      await apiSend(`/transactions/${logId}/undo`, {
        method: "POST",
        body: JSON.stringify({})
      });
      await mutate();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">History</h1>
        <p className="mt-1 text-sm text-slate-600">
          Transaction log with append-only undo via compensating operations.
        </p>
      </section>

      <section className="panel p-4">
        {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {error && <ApiErrorNotice error={error} area="history data" />}
        {data?.data && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">Log ID</th>
                  <th className="px-2 py-2">Time</th>
                  <th className="px-2 py-2">Type</th>
                  <th className="px-2 py-2">Item</th>
                  <th className="px-2 py-2">Qty</th>
                  <th className="px-2 py-2">From</th>
                  <th className="px-2 py-2">To</th>
                  <th className="px-2 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {data.data.map((row) => (
                  <tr key={row.log_id} className="border-b border-slate-100">
                    <td className="px-2 py-2">#{row.log_id}</td>
                    <td className="px-2 py-2">{row.timestamp}</td>
                    <td className="px-2 py-2">{row.operation_type}</td>
                    <td className="px-2 py-2">{row.item_number}</td>
                    <td className="px-2 py-2">{row.quantity}</td>
                    <td className="px-2 py-2">{row.from_location ?? "-"}</td>
                    <td className="px-2 py-2">{row.to_location ?? "-"}</td>
                    <td className="px-2 py-2">
                      {row.is_undone ? (
                        <span className="text-slate-400">Undone</span>
                      ) : (
                        <button
                          className="button-subtle"
                          onClick={() => undo(row.log_id)}
                          disabled={busy}
                        >
                          Undo
                        </button>
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

