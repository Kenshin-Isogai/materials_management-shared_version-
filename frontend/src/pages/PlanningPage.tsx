import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { apiGet, apiGetWithPagination, apiSend } from "../lib/api";

type ProjectOption = {
  project_id: number;
  name: string;
  status: string;
  planned_start: string | null;
  requirement_count: number;
};

type PipelineRow = {
  project_id: number;
  name: string;
  status: string;
  planned_start: string;
  is_planning_preview: boolean;
  item_count: number;
  required_total: number;
  covered_on_time_total: number;
  shortage_at_start_total: number;
  remaining_shortage_total: number;
};

type PlanningRow = {
  item_id: number;
  item_number: string | null;
  manufacturer_name: string | null;
  required_quantity: number;
  dedicated_supply_by_start: number;
  generic_available_at_start: number;
  generic_allocated_quantity: number;
  covered_on_time_quantity: number;
  shortage_at_start: number;
  recovered_after_start_quantity: number;
  remaining_shortage_quantity: number;
};

type PlanningResult = {
  project: {
    project_id: number;
    name: string;
    status: string;
    planned_start: string | null;
  };
  target_date: string;
  summary: PipelineRow;
  rows: PlanningRow[];
  pipeline: PipelineRow[];
};

type RfqBatchResponse = {
  rfq_id: number;
  title: string;
};

export function PlanningPage() {
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [analysisDate, setAnalysisDate] = useState("");
  const [rfqTitle, setRfqTitle] = useState("");
  const [rfqNote, setRfqNote] = useState("");
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");

  const { data: projectsResp } = useSWR("/projects-planning-options", () =>
    apiGetWithPagination<ProjectOption[]>("/projects?per_page=500")
  );
  const { data: pipelineResp, mutate: mutatePipeline } = useSWR("/planning-pipeline", () =>
    apiGet<PipelineRow[]>("/planning/pipeline")
  );

  const projects = projectsResp?.data ?? [];
  const selectedProject = useMemo(
    () => projects.find((project) => String(project.project_id) === selectedProjectId) ?? null,
    [projects, selectedProjectId]
  );

  useEffect(() => {
    if (!selectedProjectId && projects.length) {
      const preferred =
        projects.find((project) => project.status !== "COMPLETED" && project.status !== "CANCELLED") ??
        projects[0];
      setSelectedProjectId(String(preferred.project_id));
    }
  }, [projects, selectedProjectId]);

  useEffect(() => {
    if (!selectedProject) return;
    setAnalysisDate(selectedProject.planned_start ?? "");
    setRfqTitle("");
    setRfqNote("");
  }, [selectedProject?.project_id]);

  const analysisKey = useMemo(() => {
    if (!selectedProjectId) return null;
    const params = new URLSearchParams();
    if (analysisDate.trim()) params.set("target_date", analysisDate.trim());
    const query = params.toString();
    return `/projects/${selectedProjectId}/planning-analysis${query ? `?${query}` : ""}`;
  }, [analysisDate, selectedProjectId]);

  const {
    data: analysisData,
    error: analysisError,
    isLoading: analysisLoading,
    mutate: mutateAnalysis,
  } = useSWR(analysisKey, () => apiGet<PlanningResult>(analysisKey ?? ""));

  const pipeline = analysisData?.pipeline ?? pipelineResp ?? [];

  async function createRfqBatch() {
    if (!selectedProjectId) return;
    setWorking(true);
    setMessage("");
    try {
      const payload = await apiSend<RfqBatchResponse>(`/projects/${selectedProjectId}/rfq-batches`, {
        method: "POST",
        body: JSON.stringify({
          title: rfqTitle.trim() || null,
          note: rfqNote.trim() || null,
          target_date: analysisDate.trim() || null,
        })
      });
      setMessage(`Created RFQ batch #${payload.rfq_id}.`);
      await Promise.all([mutateAnalysis(), mutatePipeline()]);
    } catch (error) {
      setMessage(`RFQ creation failed: ${String(error ?? "")}`);
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Planning Pipeline</h1>
        <p className="mt-1 text-sm text-slate-600">
          Sequence projects by start date, net later work against earlier committed demand, and turn uncovered rows into RFQ batches.
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Projects in <span className="font-semibold">CONFIRMED</span> or <span className="font-semibold">ACTIVE</span> consume planning capacity for later projects. Creating an RFQ from a draft project auto-confirms it.
        </p>
      </section>

      <section className="grid gap-6 xl:grid-cols-[320px,minmax(0,1fr)]">
        <aside className="space-y-4">
          <section className="panel p-4">
            <h2 className="mb-3 font-display text-lg font-semibold">Analyze Project</h2>
            <div className="space-y-3">
              <select
                className="input"
                value={selectedProjectId}
                onChange={(e) => setSelectedProjectId(e.target.value)}
              >
                <option value="">Select project</option>
                {projects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    #{project.project_id} {project.name} ({project.status})
                  </option>
                ))}
              </select>
              <input
                className="input"
                type="date"
                value={analysisDate}
                onChange={(e) => setAnalysisDate(e.target.value)}
                placeholder="Project start date"
              />
              {selectedProject && (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                  <p className="font-semibold">{selectedProject.name}</p>
                  <p>Status: {selectedProject.status}</p>
                  <p>Requirements: {selectedProject.requirement_count}</p>
                  <p>Stored planned start: {selectedProject.planned_start ?? "-"}</p>
                </div>
              )}
              {!!message && <p className="text-sm text-slate-700">{message}</p>}
              {analysisError && <p className="text-sm text-red-600">{String(analysisError)}</p>}
            </div>
          </section>

          <section className="panel p-4">
            <h2 className="mb-3 font-display text-lg font-semibold">Committed Timeline</h2>
            <div className="space-y-3">
              {!pipeline.length && <p className="text-sm text-slate-500">No committed projects in the pipeline yet.</p>}
              {pipeline.map((row) => {
                const active = String(row.project_id) === selectedProjectId;
                return (
                  <button
                    key={row.project_id}
                    type="button"
                    className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                      active
                        ? "border-slate-800 bg-slate-800 text-white"
                        : "border-slate-200 bg-white hover:border-slate-300"
                    }`}
                    onClick={() => setSelectedProjectId(String(row.project_id))}
                  >
                    <p className="text-sm font-semibold">
                      #{row.project_id} {row.name}
                    </p>
                    <p className={`mt-1 text-xs ${active ? "text-slate-200" : "text-slate-500"}`}>
                      {row.planned_start} / {row.status}
                      {row.is_planning_preview ? " / preview" : ""}
                    </p>
                    <div className={`mt-3 grid grid-cols-2 gap-2 text-xs ${active ? "text-slate-100" : "text-slate-600"}`}>
                      <div className="rounded-xl bg-black/5 px-2 py-2">
                        <p className="font-semibold">On-time gap</p>
                        <p>{row.shortage_at_start_total}</p>
                      </div>
                      <div className="rounded-xl bg-black/5 px-2 py-2">
                        <p className="font-semibold">Remaining</p>
                        <p>{row.remaining_shortage_total}</p>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        </aside>

        <div className="space-y-4">
          {!selectedProjectId && (
            <section className="panel p-6">
              <p className="text-sm text-slate-500">Select a project to run sequential planning analysis.</p>
            </section>
          )}

          {selectedProjectId && (
            <>
              <section className="panel p-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <h2 className="font-display text-xl font-semibold">
                      {analysisData?.project.name ?? selectedProject?.name ?? "Project analysis"}
                    </h2>
                    <p className="mt-1 text-sm text-slate-600">
                      Analysis date: <span className="font-semibold">{analysisData?.target_date ?? (analysisDate || "-")}</span>
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Dedicated supply is used first. Generic coverage is what remains after earlier committed projects and their backlogs are netted out.
                    </p>
                  </div>
                  {analysisData?.summary && (
                    <div className="grid min-w-[320px] gap-3 sm:grid-cols-3">
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Required</p>
                        <p className="mt-1 text-2xl font-bold">{analysisData.summary.required_total}</p>
                      </div>
                      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">On-Time Gap</p>
                        <p className="mt-1 text-2xl font-bold text-amber-800">{analysisData.summary.shortage_at_start_total}</p>
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Remaining</p>
                        <p className="mt-1 text-2xl font-bold">{analysisData.summary.remaining_shortage_total}</p>
                      </div>
                    </div>
                  )}
                </div>
              </section>

              <section className="panel p-4">
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr),minmax(0,1fr),auto]">
                  <input
                    className="input"
                    value={rfqTitle}
                    onChange={(e) => setRfqTitle(e.target.value)}
                    placeholder="Optional RFQ batch title"
                  />
                  <input
                    className="input"
                    value={rfqNote}
                    onChange={(e) => setRfqNote(e.target.value)}
                    placeholder="Optional RFQ note"
                  />
                  <button
                    className="button"
                    type="button"
                    disabled={working || !analysisData || analysisData.summary.shortage_at_start_total <= 0}
                    onClick={createRfqBatch}
                  >
                    Create RFQ From Gaps
                  </button>
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  The batch is created from rows with on-time shortage only. Later recovery remains visible in the table, but it does not remove the start-date risk.
                </p>
              </section>

              <section className="panel p-4">
                {analysisLoading && <p className="text-sm text-slate-500">Loading planning analysis...</p>}
                {!analysisLoading && analysisData && (
                  <div className="overflow-x-auto">
                    <table className="min-w-[1080px] text-sm">
                      <thead>
                        <tr className="border-b border-slate-200 text-left text-slate-500">
                          <th className="px-2 py-2">Item</th>
                          <th className="px-2 py-2">Required</th>
                          <th className="px-2 py-2">Dedicated By Start</th>
                          <th className="px-2 py-2">Generic Covered</th>
                          <th className="px-2 py-2">On-Time Gap</th>
                          <th className="px-2 py-2">Recovered Later</th>
                          <th className="px-2 py-2">Remaining</th>
                        </tr>
                      </thead>
                      <tbody>
                        {analysisData.rows.map((row) => (
                          <tr key={row.item_id} className="border-b border-slate-100">
                            <td className="px-2 py-2">
                              <p className="font-semibold">{row.item_number ?? `#${row.item_id}`}</p>
                              <p className="text-xs text-slate-500">{row.manufacturer_name ?? "-"}</p>
                            </td>
                            <td className="px-2 py-2">{row.required_quantity}</td>
                            <td className="px-2 py-2">{row.dedicated_supply_by_start}</td>
                            <td className="px-2 py-2">
                              <span title={`Generic pool visible at start: ${row.generic_available_at_start}`}>
                                {row.generic_allocated_quantity}
                              </span>
                            </td>
                            <td className="px-2 py-2 font-semibold text-amber-700">{row.shortage_at_start}</td>
                            <td className="px-2 py-2">{row.recovered_after_start_quantity}</td>
                            <td className="px-2 py-2 font-semibold text-slate-900">{row.remaining_shortage_quantity}</td>
                          </tr>
                        ))}
                        {!analysisData.rows.length && (
                          <tr>
                            <td className="px-2 py-4 text-slate-500" colSpan={7}>
                              No requirement rows.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
