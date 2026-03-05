import { useState } from "react";
import { apiSend } from "../lib/api";

type BomRow = {
  supplier: string;
  item_number: string;
  required_quantity: number;
};

type BomResult = {
  rows: Array<Record<string, unknown>>;
  target_date?: string | null;
};

const blankRow = (): BomRow => ({
  supplier: "",
  item_number: "",
  required_quantity: 0
});

export function BomPage() {
  const [rows, setRows] = useState<BomRow[]>([
    { supplier: "Thorlabs", item_number: "LENS-001", required_quantity: 3 }
  ]);
  const [result, setResult] = useState<BomResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [targetDate, setTargetDate] = useState("");
  const [message, setMessage] = useState("");

  function updateRow(index: number, patch: Partial<BomRow>) {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeRow(index: number) {
    setRows((prev) => prev.filter((_, i) => i !== index));
  }

  function normalizedRows(): BomRow[] {
    return rows
      .filter((row) => row.supplier.trim() && row.item_number.trim())
      .map((row) => ({
        supplier: row.supplier.trim(),
        item_number: row.item_number.trim(),
        required_quantity: Number(row.required_quantity || 0)
      }));
  }

  async function analyze() {
    const payloadRows = normalizedRows();
    if (!payloadRows.length) return;
    setMessage("");
    setLoading(true);
    try {
      const data = await apiSend<BomResult>("/bom/analyze", {
        method: "POST",
        body: JSON.stringify({
          rows: payloadRows,
          target_date: targetDate.trim() || null
        })
      });
      setResult(data);
    } finally {
      setLoading(false);
    }
  }

  async function reserve() {
    const payloadRows = normalizedRows();
    if (!payloadRows.length) return;
    setMessage("");
    setLoading(true);
    try {
      const data = await apiSend<{ analysis: Array<Record<string, unknown>> }>(
        "/bom/reserve",
        {
          method: "POST",
          body: JSON.stringify({
            rows: payloadRows,
            purpose: "BOM reserve"
          })
        }
      );
      setResult({ rows: data.analysis });
    } finally {
      setLoading(false);
    }
  }

  async function saveShortages() {
    const payloadRows = normalizedRows();
    if (!payloadRows.length) return;
    setMessage("");
    setLoading(true);
    try {
      const data = await apiSend<{
        target_date: string | null;
        analysis: Array<Record<string, unknown>>;
        created_count: number;
      }>("/purchase-candidates/from-bom", {
        method: "POST",
        body: JSON.stringify({
          rows: payloadRows,
          target_date: targetDate.trim() || null
        })
      });
      setResult({ rows: data.analysis, target_date: data.target_date });
      setMessage(`Saved ${data.created_count} purchase candidate(s).`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">BOM</h1>
        <p className="mt-1 text-sm text-slate-600">
          Run gap analysis and reserve available stock from BOM input rows.
        </p>
      </section>

      <section className="panel p-4">
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-600">Spreadsheet-like BOM entry</p>
          <button className="button-subtle" onClick={() => setRows((prev) => [...prev, blankRow()])}>
            Add Row
          </button>
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-[700px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="px-2 py-2">Supplier</th>
                <th className="px-2 py-2">Item Number</th>
                <th className="px-2 py-2">Required Qty</th>
                <th className="px-2 py-2">-</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => (
                <tr key={idx} className="border-b border-slate-100">
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      value={row.supplier}
                      onChange={(e) => updateRow(idx, { supplier: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      value={row.item_number}
                      onChange={(e) => updateRow(idx, { item_number: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <input
                      className="input"
                      type="number"
                      min={0}
                      value={row.required_quantity}
                      onChange={(e) => updateRow(idx, { required_quantity: Number(e.target.value) })}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <button className="button-subtle" onClick={() => removeRow(idx)}>
                      Del
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex gap-2">
          <input
            className="input"
            type="date"
            value={targetDate}
            onChange={(e) => setTargetDate(e.target.value)}
            title="BOM analysis target date"
          />
          <button className="button" disabled={loading} onClick={analyze}>
            Analyze
          </button>
          <button className="button-subtle" disabled={loading} onClick={reserve}>
            Reserve Available
          </button>
          <button className="button-subtle" disabled={loading} onClick={saveShortages}>
            Save Shortages
          </button>
        </div>
        {!!message && <p className="mt-2 text-sm text-slate-700">{message}</p>}
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Result</h2>
        {!result && <p className="text-sm text-slate-500">No analysis yet.</p>}
        {result && (
          <div className="space-y-2 overflow-x-auto">
            <p className="text-xs text-slate-500">
              Analysis date: <strong>{result.target_date ?? "current availability"}</strong>
            </p>
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">Supplier</th>
                  <th className="px-2 py-2">Ordered Item</th>
                  <th className="px-2 py-2">Canonical Item</th>
                  <th className="px-2 py-2">Required</th>
                  <th className="px-2 py-2">Available</th>
                  <th className="px-2 py-2">Shortage</th>
                  <th className="px-2 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, idx) => (
                  <tr key={idx} className="border-b border-slate-100">
                    <td className="px-2 py-2">{String(row.supplier ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.ordered_item_number ?? row.item_number ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.canonical_item_number ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.required_quantity ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.available_stock ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.shortage ?? "-")}</td>
                    <td className="px-2 py-2">{String(row.status ?? "-")}</td>
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
