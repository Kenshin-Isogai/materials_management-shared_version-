import { useMemo, useState } from "react";
import useSWR from "swr";
import { apiGetWithPagination, apiSend } from "../lib/api";

type ProjectOption = {
  project_id: number;
  name: string;
  planned_start: string | null;
  status: string;
};

type PurchaseCandidate = {
  candidate_id: number;
  source_type: "BOM" | "PROJECT";
  project_id: number | null;
  project_name: string | null;
  item_id: number | null;
  item_number: string | null;
  manufacturer_name: string | null;
  supplier_name: string | null;
  ordered_item_number: string | null;
  canonical_item_number: string | null;
  required_quantity: number;
  available_stock: number;
  shortage_quantity: number;
  target_date: string | null;
  status: "OPEN" | "ORDERING" | "ORDERED" | "CANCELLED";
  note: string | null;
  updated_at: string;
};

export function PurchaseCandidatesPage() {
  const [statusFilter, setStatusFilter] = useState("OPEN");
  const [sourceFilter, setSourceFilter] = useState("");
  const [projectId, setProjectId] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [note, setNote] = useState("");
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("per_page", "500");
    if (statusFilter) params.set("status", statusFilter);
    if (sourceFilter) params.set("source_type", sourceFilter);
    return `/purchase-candidates?${params.toString()}`;
  }, [sourceFilter, statusFilter]);

  const { data: listResp, isLoading, error, mutate } = useSWR(listPath, () =>
    apiGetWithPagination<PurchaseCandidate[]>(listPath)
  );
  const { data: projectsResp } = useSWR("/projects-options-purchase-candidates", () =>
    apiGetWithPagination<ProjectOption[]>("/projects?per_page=500")
  );
  const rows = listResp?.data ?? [];
  const projects = projectsResp?.data ?? [];

  async function createFromProjectGap() {
    if (!projectId) return;
    setWorking(true);
    setMessage("");
    try {
      const payload = await apiSend<{ created_count: number }>(
        `/purchase-candidates/from-project/${Number(projectId)}`,
        {
          method: "POST",
          body: JSON.stringify({
            target_date: targetDate.trim() || null,
            note: note.trim() || null
          })
        }
      );
      setMessage(`Created ${payload.created_count} purchase candidate(s) from project gap.`);
      await mutate();
    } catch (e) {
      setMessage(`Create failed: ${String(e ?? "")}`);
    } finally {
      setWorking(false);
    }
  }

  async function updateStatus(candidateId: number, status: PurchaseCandidate["status"]) {
    setWorking(true);
    setMessage("");
    try {
      await apiSend(`/purchase-candidates/${candidateId}`, {
        method: "PUT",
        body: JSON.stringify({ status })
      });
      await mutate();
    } catch (e) {
      setMessage(`Update failed: ${String(e ?? "")}`);
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Purchase Candidates</h1>
        <p className="mt-1 text-sm text-slate-600">
          Keep pre-PO shortage candidates while waiting for quotation and expected-arrival decisions.
        </p>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Create From Project Gap</h2>
        <div className="grid gap-3 md:grid-cols-4">
          <select className="input" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">Select project</option>
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                #{project.project_id} {project.name} ({project.status}){project.planned_start ? ` / ${project.planned_start}` : ""}
              </option>
            ))}
          </select>
          <input
            className="input"
            type="date"
            value={targetDate}
            onChange={(e) => setTargetDate(e.target.value)}
            placeholder="Target date"
          />
          <input
            className="input"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional note"
          />
          <button className="button" disabled={working || !projectId} onClick={createFromProjectGap}>
            Create Candidates
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Tip: Use the BOM page “Save Shortages” button for BOM-driven candidate creation.
        </p>
        {!!message && <p className="mt-2 text-sm text-slate-700">{message}</p>}
      </section>

      <section className="panel p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <select className="input w-auto" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All status</option>
            <option value="OPEN">OPEN</option>
            <option value="ORDERING">ORDERING</option>
            <option value="ORDERED">ORDERED</option>
            <option value="CANCELLED">CANCELLED</option>
          </select>
          <select className="input w-auto" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
            <option value="">All source</option>
            <option value="PROJECT">PROJECT</option>
            <option value="BOM">BOM</option>
          </select>
        </div>
        {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {error && <p className="text-sm text-red-600">{String(error)}</p>}
        {!isLoading && !error && (
          <div className="overflow-x-auto">
            <table className="min-w-[1200px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">ID</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Source</th>
                  <th className="px-2 py-2">Project</th>
                  <th className="px-2 py-2">Item</th>
                  <th className="px-2 py-2">Supplier / Ordered Item</th>
                  <th className="px-2 py-2">Required</th>
                  <th className="px-2 py-2">Available</th>
                  <th className="px-2 py-2">Shortage</th>
                  <th className="px-2 py-2">Target Date</th>
                  <th className="px-2 py-2">Note</th>
                  <th className="px-2 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.candidate_id} className="border-b border-slate-100">
                    <td className="px-2 py-2">#{row.candidate_id}</td>
                    <td className="px-2 py-2">{row.status}</td>
                    <td className="px-2 py-2">{row.source_type}</td>
                    <td className="px-2 py-2">
                      {row.project_id ? `#${row.project_id} ${row.project_name ?? ""}` : "-"}
                    </td>
                    <td className="px-2 py-2">
                      {row.item_number ? `${row.item_number}${row.manufacturer_name ? ` (${row.manufacturer_name})` : ""}` : "-"}
                    </td>
                    <td className="px-2 py-2">
                      {[row.supplier_name, row.ordered_item_number].filter(Boolean).join(" / ") || "-"}
                    </td>
                    <td className="px-2 py-2">{row.required_quantity}</td>
                    <td className="px-2 py-2">{row.available_stock}</td>
                    <td className="px-2 py-2 font-semibold text-amber-700">{row.shortage_quantity}</td>
                    <td className="px-2 py-2">{row.target_date ?? "-"}</td>
                    <td className="px-2 py-2">{row.note ?? "-"}</td>
                    <td className="px-2 py-2">
                      <div className="flex flex-wrap gap-1">
                        <button className="button-subtle" disabled={working} onClick={() => updateStatus(row.candidate_id, "OPEN")}>
                          Open
                        </button>
                        <button className="button-subtle" disabled={working} onClick={() => updateStatus(row.candidate_id, "ORDERING")}>
                          Ordering
                        </button>
                        <button className="button-subtle" disabled={working} onClick={() => updateStatus(row.candidate_id, "ORDERED")}>
                          Ordered
                        </button>
                        <button className="button-subtle" disabled={working} onClick={() => updateStatus(row.candidate_id, "CANCELLED")}>
                          Cancel
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr>
                    <td className="px-2 py-4 text-slate-500" colSpan={12}>
                      No purchase candidates.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
