import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import useSWR from "swr";
import { cn } from "@/lib/utils";
import { StatusCallout } from "@/components/StatusCallout";
import { apiDownload, apiGet, apiSend } from "@/lib/api";
import {
  isAuthError,
  isBackendUnavailableError,
  presentApiError,
} from "@/lib/errorUtils";
import { nextSynchronizedBoardDate } from "@/lib/workspaceState";
import { projectEditorRoute } from "@/features/projects/routes";
import type {
  ConfirmAllocationResult,
  PlanningAnalysisResult,
  PlanningAnalysisRow,
  PlanningSource,
  WorkspaceProjectSummary,
  WorkspaceSummary,
} from "@/lib/types";

/* ── Helpers ── */

function statusTone(status: string): string {
  switch (status) {
    case "ACTIVE":
      return "bg-emerald-100 text-emerald-800";
    case "CONFIRMED":
      return "bg-sky-100 text-sky-800";
    case "PLANNING":
      return "bg-amber-100 text-amber-800";
    case "COMPLETED":
      return "bg-slate-200 text-slate-700";
    case "CANCELLED":
      return "bg-rose-100 text-rose-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function sourceTone(sourceType: PlanningSource["source_type"]): string {
  switch (sourceType) {
    case "stock":
      return "bg-slate-100 text-slate-700";
    case "generic_order":
      return "bg-sky-100 text-sky-800";
    case "dedicated_order":
      return "bg-emerald-100 text-emerald-800";
    case "quoted_rfq":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function isConfirmablePlanningSource(source: PlanningSource): boolean {
  if ((source.quantity ?? 0) <= 0) return false;
  return source.source_type === "stock" || source.source_type === "generic_order";
}

function formatDate(value: string | null | undefined): string {
  return value && value.trim() ? value : "-";
}

function normalizePlanningDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.toLowerCase() === "none" || trimmed.toLowerCase() === "null") return null;
  return trimmed;
}

function formatPlanningDate(value: string | null | undefined): string {
  return formatDate(normalizePlanningDate(value));
}

function describePlanningDate(value: string | null | undefined): string {
  const normalized = normalizePlanningDate(value);
  return normalized ? formatDate(normalized) : "unknown date";
}

function comparePlanningSourceDate(a: PlanningSource, b: PlanningSource): number {
  const left = normalizePlanningDate(a.date) ?? "9999-12-31";
  const right = normalizePlanningDate(b.date) ?? "9999-12-31";
  if (left !== right) return left.localeCompare(right);
  return (a.ref_id ?? Number.MAX_SAFE_INTEGER) - (b.ref_id ?? Number.MAX_SAFE_INTEGER);
}

type RecoveryBurndownStep = {
  date: string | null;
  quantity: number;
  label: string;
  sourceType: PlanningSource["source_type"];
  remainingAfter: number;
};

function buildRecoveryBurndown(shortageAtStart: number, recoverySources: PlanningSource[]): RecoveryBurndownStep[] {
  let remaining = shortageAtStart;
  return [...recoverySources]
    .sort(comparePlanningSourceDate)
    .filter((s) => s.quantity > 0)
    .map((s) => {
      remaining = Math.max(0, remaining - s.quantity);
      return { date: normalizePlanningDate(s.date), quantity: s.quantity, label: s.label, sourceType: s.source_type, remainingAfter: remaining };
    });
}

function recoverySummaryText(shortageAtStart: number, recoverySources: PlanningSource[]): string {
  if (shortageAtStart <= 0) return "No start-date gap.";
  const steps = buildRecoveryBurndown(shortageAtStart, recoverySources);
  if (!steps.length) return "No later recovery scheduled.";
  const recovered = Math.min(shortageAtStart, steps.reduce((t, s) => t + s.quantity, 0));
  const resolvedStep = steps.find((s) => s.remainingAfter === 0);
  if (resolvedStep) return `Recovered ${recovered} by ${describePlanningDate(resolvedStep.date)}.`;
  return `Recovered ${recovered} by ${describePlanningDate(steps[steps.length - 1]?.date)}. Still short ${steps[steps.length - 1]?.remainingAfter ?? shortageAtStart}.`;
}

function pickDefaultProject(projects: WorkspaceProjectSummary[]): WorkspaceProjectSummary | null {
  return projects.find((p) => p.status !== "COMPLETED" && p.status !== "CANCELLED") ?? projects[0] ?? null;
}

function renderError(error: unknown, area: string) {
  if (isAuthError(error)) return <StatusCallout title="Sign-in required" message={`Sign in to load ${area}.`} tone="error" />;
  if (isBackendUnavailableError(error)) return <StatusCallout title="Environment unavailable" message={`${area} unavailable.`} tone="warning" />;
  return <p className="text-sm text-red-600">{presentApiError(error)}</p>;
}

/* ── Sub-components ── */

function SummaryMetric({ label, value, tone = "slate" }: { label: string; value: number | string; tone?: "slate" | "amber" | "emerald" | "sky" }) {
  const cls = tone === "amber" ? "border-amber-200 bg-amber-50 text-amber-900"
    : tone === "emerald" ? "border-emerald-200 bg-emerald-50 text-emerald-900"
    : tone === "sky" ? "border-sky-200 bg-sky-50 text-sky-900"
    : "border-slate-200 bg-slate-50 text-slate-900";
  return (
    <div className={cn("rounded-2xl border px-4 py-3", cls)}>
      <p className="text-xs font-semibold uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}

function PlanningSourceList({ title, sources, emptyLabel }: { title: string; sources: PlanningSource[]; emptyLabel: string }) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
      {sources.length ? (
        <div className="flex flex-wrap gap-2">
          {sources.map((source, i) => (
            <span key={`${source.source_type}-${source.ref_id ?? "stock"}-${i}`} className={cn("inline-flex items-center gap-2 rounded-full px-2 py-1 text-xs font-medium", sourceTone(source.source_type))} title={normalizePlanningDate(source.date) ?? undefined}>
              <span>{source.quantity}</span>
              <span>{source.label}</span>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-500">{emptyLabel}</p>
      )}
    </div>
  );
}

function PlanningBoardRow({ row, projectId }: { row: PlanningAnalysisRow; projectId: number }) {
  const recoverySummary = recoverySummaryText(row.shortage_at_start, row.recovery_sources_after_start);
  return (
    <tr className="border-b border-slate-100 align-top">
      <td className="px-2 py-3">
        <p className="font-semibold">{row.item_number ?? `#${row.item_id}`}</p>
        <p className="text-xs text-slate-500">{row.manufacturer_name ?? "-"}</p>
      </td>
      <td className="px-2 py-3">{row.required_quantity}</td>
      <td className="px-2 py-3">
        <p className="font-semibold">{row.covered_on_time_quantity}</p>
        <p className="text-xs text-slate-500">Dedicated {row.dedicated_supply_by_start} | Generic {row.generic_allocated_quantity} / pool {row.generic_available_at_start}</p>
      </td>
      <td className="px-2 py-3 font-semibold text-amber-700">{row.shortage_at_start}</td>
      <td className="px-2 py-3">
        <p className="font-semibold">{row.recovered_after_start_quantity}</p>
        <p className="text-xs text-slate-500">Generic {row.future_generic_recovery_quantity} | Dedicated {row.future_dedicated_recovery_quantity}</p>
        <p className="mt-1 text-xs text-slate-500">{recoverySummary}</p>
      </td>
      <td className="px-2 py-3 font-semibold text-slate-900">{row.remaining_shortage_quantity}</td>
      <td className="px-2 py-3"><PlanningSourceList title="By Start" sources={row.supply_sources_by_start} emptyLabel="No on-time coverage." /></td>
      <td className="px-2 py-3"><PlanningSourceList title="Later Recovery" sources={row.recovery_sources_after_start} emptyLabel="No later recovery." /></td>
      <td className="px-2 py-3">
        <div className="flex flex-col gap-2">
          <Link className="button-subtle" to={`/items/${row.item_id}`}>Item</Link>
          <Link className="button-subtle" to="/procurement">RFQ</Link>
        </div>
      </td>
    </tr>
  );
}

/* ── Main Page ── */

export function PlanningBoardPage() {
  const { projectId: urlProjectId } = useParams<{ projectId?: string }>();

  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(
    urlProjectId ? Number(urlProjectId) : null,
  );
  const [analysisDateDraft, setAnalysisDateDraft] = useState("");
  const [analysisDateApplied, setAnalysisDateApplied] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [working, setWorking] = useState(false);
  const [allocationPreview, setAllocationPreview] = useState<ConfirmAllocationResult | null>(null);

  const { data: workspaceSummary, error: workspaceError, mutate: mutateWorkspace } = useSWR("/workspace/summary", () => apiGet<WorkspaceSummary>("/workspace/summary"));

  const projects = workspaceSummary?.projects ?? [];
  const pipeline = workspaceSummary?.pipeline ?? [];

  useEffect(() => {
    const selectedStillExists = selectedProjectId != null && projects.some((p) => p.project_id === selectedProjectId);
    if (selectedStillExists) return;
    const defaultProject = pickDefaultProject(projects);
    if (!defaultProject) { setSelectedProjectId(null); setAnalysisDateDraft(""); setAnalysisDateApplied(""); return; }
    setSelectedProjectId(defaultProject.project_id);
    setAnalysisDateDraft(defaultProject.planned_start ?? "");
    setAnalysisDateApplied(defaultProject.planned_start ?? "");
  }, [projects, selectedProjectId]);

  const selectedProject = useMemo(() => projects.find((p) => p.project_id === selectedProjectId) ?? null, [projects, selectedProjectId]);

  useEffect(() => {
    if (!selectedProject) return;
    setAnalysisDateDraft(selectedProject.planned_start ?? "");
    setAnalysisDateApplied(selectedProject.planned_start ?? "");
    setActionMessage("");
  }, [selectedProject?.project_id]);

  const analysisKey = useMemo(() => {
    if (!selectedProject) return null;
    const params = new URLSearchParams();
    if (analysisDateApplied.trim()) params.set("target_date", analysisDateApplied.trim());
    const query = params.toString();
    return `/projects/${selectedProject.project_id}/planning-analysis${query ? `?${query}` : ""}`;
  }, [analysisDateApplied, selectedProject?.project_id]);

  const { data: analysisData, error: analysisError, isLoading: analysisLoading, mutate: mutateAnalysis } = useSWR(analysisKey, () => apiGet<PlanningAnalysisResult>(analysisKey ?? ""));

  const selectedAnalysisTargetDate = analysisData && analysisData.project.project_id === selectedProject?.project_id ? analysisData.target_date : null;
  const boardPipeline = analysisData?.pipeline ?? pipeline;
  const previewDirty = analysisDateDraft.trim() !== analysisDateApplied.trim();
  const persistedDate = selectedProject?.planned_start ?? "";
  const canPersistDate = analysisDateDraft.trim() !== "" && analysisDateDraft.trim() !== persistedDate;
  const hasConfirmableAllocation = useMemo(() => (analysisData?.rows ?? []).some((row) => (row.supply_sources_by_start ?? []).some(isConfirmablePlanningSource)), [analysisData?.rows]);

  useEffect(() => {
    if (!selectedProject) return;
    const next = nextSynchronizedBoardDate({ analysisDateDraft, analysisDateApplied, projectPlannedStart: selectedProject.planned_start, analysisTargetDate: selectedAnalysisTargetDate });
    if (next == null) return;
    setAnalysisDateDraft(next);
    setAnalysisDateApplied(next);
  }, [analysisDateApplied, analysisDateDraft, selectedAnalysisTargetDate, selectedProject?.planned_start, selectedProject?.project_id]);

  useEffect(() => {
    if (!previewDirty) return;
    setAllocationPreview(null);
  }, [previewDirty]);

  async function refreshWorkspace() {
    await Promise.all([mutateWorkspace(), analysisKey ? mutateAnalysis() : Promise.resolve(undefined)]);
  }

  function selectProject(projectId: number) {
    const project = projects.find((p) => p.project_id === projectId);
    setSelectedProjectId(projectId);
    setAnalysisDateDraft(project?.planned_start ?? "");
    setAnalysisDateApplied(project?.planned_start ?? "");
    setAllocationPreview(null);
  }

  function previewImpact() { setActionMessage(""); setAllocationPreview(null); setAnalysisDateApplied(analysisDateDraft.trim()); }

  async function savePlannedStartFromBoard() {
    if (!selectedProjectId) return;
    setWorking(true); setActionMessage("");
    try {
      await apiSend(`/projects/${selectedProjectId}`, { method: "PUT", body: JSON.stringify({ planned_start: analysisDateDraft.trim() || null }) });
      setAnalysisDateApplied(analysisDateDraft.trim());
      setActionMessage("Planned start saved.");
      await refreshWorkspace();
    } catch (e) { setActionMessage(`Save failed: ${String(e ?? "")}`); } finally { setWorking(false); }
  }

  async function previewConfirmAllocation() {
    if (!selectedProjectId) return;
    setWorking(true); setActionMessage("");
    try {
      const payload = await apiSend<ConfirmAllocationResult>(`/projects/${selectedProjectId}/confirm-allocation`, {
        method: "POST", body: JSON.stringify({ target_date: selectedAnalysisTargetDate ?? (analysisDateApplied.trim() || null), dry_run: true }),
      });
      setAllocationPreview(payload);
      setActionMessage("Allocation preview generated.");
    } catch (e) { setAllocationPreview(null); setActionMessage(`Preview failed: ${String(e ?? "")}`); } finally { setWorking(false); }
  }

  async function executeConfirmAllocation() {
    if (!selectedProjectId || !allocationPreview) return;
    if (!window.confirm("Confirm this allocation? Generic coverage → dedicated orders, stock → reservations.")) return;
    setWorking(true); setActionMessage("");
    try {
      const payload = await apiSend<ConfirmAllocationResult>(`/projects/${selectedProjectId}/confirm-allocation`, {
        method: "POST", body: JSON.stringify({ target_date: selectedAnalysisTargetDate ?? (analysisDateApplied.trim() || null), dry_run: false, expected_snapshot_signature: allocationPreview.snapshot_signature }),
      });
      setAllocationPreview(payload);
      setActionMessage(`Confirmed: ${payload.orders_assigned.length} assigned, ${payload.orders_split.length} split, ${payload.reservations_created.length} reservations.`);
      await refreshWorkspace();
    } catch (e) { setActionMessage(`Confirm failed: ${String(e ?? "")}`); await refreshWorkspace(); } finally { setWorking(false); }
  }

  async function createRfqBatch() {
    if (!selectedProjectId) return;
    const isDraft = selectedProject?.status === "PLANNING";
    if (!window.confirm(isDraft ? "Create procurement batch from gaps? This will confirm the draft project." : "Create procurement batch from gaps?")) return;
    setWorking(true); setActionMessage("");
    try {
      const payload = await apiSend<{ batch_id: number }>("/shortage-inbox/to-procurement", {
        method: "POST", body: JSON.stringify({
          create_batch_title: `${selectedProject?.name ?? "Project"} procurement`,
          confirm_project_id: isDraft ? selectedProjectId : null,
          confirm_target_date: isDraft ? selectedAnalysisTargetDate ?? (analysisDateApplied.trim() || null) : null,
          lines: (analysisData?.rows ?? []).filter((r) => r.shortage_at_start > 0).map((r) => ({
            item_id: r.item_id, requested_quantity: r.shortage_at_start, source_type: "PROJECT", source_project_id: selectedProjectId,
            expected_arrival: selectedAnalysisTargetDate ?? (analysisDateApplied.trim() || null), note: "From workspace planning gap",
          })),
        }),
      });
      setActionMessage(`Created procurement batch #${payload.batch_id}.`);
      await refreshWorkspace();
    } catch (e) { setActionMessage(`Creation failed: ${String(e ?? "")}`); } finally { setWorking(false); }
  }

  async function downloadPlanningExport() {
    if (!selectedProjectId) return;
    const params = new URLSearchParams({ project_id: String(selectedProjectId) });
    if (selectedAnalysisTargetDate) params.set("target_date", selectedAnalysisTargetDate);
    try { await apiDownload(`/workspace/planning-export?${params}`, `planning_project_${selectedProjectId}.csv`); setActionMessage("Export downloaded."); }
    catch (e) { setActionMessage(`Export failed: ${String(e ?? "")}`); }
  }

  async function downloadPipelineExport() {
    const params = new URLSearchParams();
    if (selectedProjectId) { params.set("project_id", String(selectedProjectId)); if (selectedAnalysisTargetDate) params.set("target_date", selectedAnalysisTargetDate); }
    const query = params.toString();
    try { await apiDownload(`/workspace/planning-export-multi${query ? `?${query}` : ""}`, `pipeline_export.csv`); setActionMessage("Pipeline export downloaded."); }
    catch (e) { setActionMessage(`Export failed: ${String(e ?? "")}`); }
  }

  /* ── Render ── */
  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold">Planning Board</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Sequential netting analysis for a selected project. Dedicated supply consumed before generic.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            <Link className="font-semibold underline" to="/projects">Projects</Link>{" · "}
            <Link className="font-semibold underline" to="/projects/overview">Overview</Link>{" · "}
            <Link className="font-semibold underline" to="/procurement">Procurement</Link>
          </p>
        </div>
      </section>

      {workspaceError && renderError(workspaceError, "workspace data")}

      {/* ── Board Header ── */}
      <section className="panel p-4">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr),auto]">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-display text-2xl font-semibold">{analysisData?.project.name ?? selectedProject?.name ?? "Select a project"}</h2>
              {selectedProject && <span className={cn("rounded-full px-2 py-1 text-xs font-semibold", statusTone(selectedProject.status))}>{selectedProject.status}</span>}
              {analysisData?.summary.is_planning_preview && <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">What-If Preview</span>}
            </div>
            <div className="grid gap-3 md:grid-cols-[200px,auto,auto,auto]">
              <select className="input" value={selectedProjectId ?? ""} onChange={(e) => selectProject(Number(e.target.value))}>
                {projects.map((p) => <option key={p.project_id} value={p.project_id}>#{p.project_id} {p.name} ({p.status})</option>)}
              </select>
              <input className="input" type="date" value={analysisDateDraft} onChange={(e) => setAnalysisDateDraft(e.target.value)} />
              <button className="button-subtle" type="button" disabled={!selectedProjectId} onClick={previewImpact}>Preview Impact</button>
              <button className="button" type="button" disabled={!canPersistDate || working} onClick={savePlannedStartFromBoard}>Save Planned Start</button>
            </div>
            {previewDirty && <p className="text-xs text-amber-700">Date changed. Use <span className="font-semibold">Preview Impact</span> to refresh.</p>}
            {!!actionMessage && <p className="text-sm text-slate-700">{actionMessage}</p>}
            {analysisError && renderError(analysisError, "planning analysis")}
          </div>

          {analysisData?.summary && (
            <div className="grid min-w-[340px] gap-3 sm:grid-cols-2">
              <SummaryMetric label="Required" value={analysisData.summary.required_total} />
              <SummaryMetric label="Covered On Time" value={analysisData.summary.covered_on_time_total} tone="emerald" />
              <SummaryMetric label="On-Time Gap" value={analysisData.summary.shortage_at_start_total} tone="amber" />
              <SummaryMetric label="Remaining" value={analysisData.summary.remaining_shortage_total} />
              <SummaryMetric label="Generic Committed" value={analysisData.summary.generic_committed_total} tone="sky" />
              <SummaryMetric label="Generic Before" value={analysisData.summary.cumulative_generic_consumed_before_total} tone="sky" />
            </div>
          )}
        </div>
      </section>

      {/* ── Actions & Allocation Preview ── */}
      <section className="panel p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-display text-lg font-semibold">Actions</h3>
          <div className="flex flex-wrap gap-2">
            {selectedProjectId && <Link className="button-subtle" to={projectEditorRoute(selectedProjectId)}>Open Project</Link>}
            {selectedProjectId && <button className="button-subtle" type="button" disabled={working || !analysisData || !hasConfirmableAllocation} onClick={() => void previewConfirmAllocation()}>Preview Confirm</button>}
            {selectedProjectId && <button className="button-subtle" type="button" disabled={working || previewDirty || !allocationPreview || allocationPreview.dry_run !== true} onClick={() => void executeConfirmAllocation()}>Confirm Allocation</button>}
            {selectedProjectId && <button className="button-subtle" type="button" disabled={working || previewDirty || !analysisData} onClick={() => void downloadPlanningExport()}>Export CSV</button>}
            {selectedProjectId && <button className="button-subtle" type="button" disabled={working || previewDirty || !analysisData} onClick={() => void downloadPipelineExport()}>Export Pipeline</button>}
            {selectedProjectId && <button className="button" type="button" disabled={working || previewDirty || !analysisData || analysisData.summary.shortage_at_start_total <= 0} onClick={createRfqBatch}>Create Procurement Batch</button>}
          </div>
        </div>
        {previewDirty && (
          <p className="mb-3 text-xs text-amber-700">
            Refresh the board with <span className="font-semibold">Preview Impact</span> before confirming, exporting, or creating procurement from the edited date.
          </p>
        )}

        {allocationPreview && (
          <div className="mb-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-semibold">Allocation {allocationPreview.dry_run ? "Preview" : "Result"}</p>
                <p className="text-xs text-slate-500">
                  Target {formatDate(allocationPreview.target_date)} | Orders assigned {allocationPreview.orders_assigned.length} |
                  Split {allocationPreview.orders_split.length} | Reservations {allocationPreview.reservations_created.length}
                </p>
              </div>
              <button className="button-subtle" type="button" onClick={() => setAllocationPreview(null)}>Clear</button>
            </div>
            <div className="mt-3 grid gap-3 xl:grid-cols-2">
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Orders</p>
                {allocationPreview.orders_assigned.map((e) => <p key={`a-${e.order_id}-${e.item_id}`}>Assign #{e.order_id} item #{e.item_id} qty {e.quantity}.</p>)}
                {allocationPreview.orders_split.map((e) => <p key={`s-${e.original_order_id}-${e.item_id}`}>Split #{e.original_order_id}: assign {e.assigned_quantity}, leave {e.remaining_quantity}{e.new_order_id ? `, new #${e.new_order_id}` : ""}.</p>)}
                {!allocationPreview.orders_assigned.length && !allocationPreview.orders_split.length && <p className="text-slate-500">No orders dedicated.</p>}
              </div>
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Reservations</p>
                {allocationPreview.reservations_created.map((e) => <p key={`r-${e.item_id}-${e.reservation_id ?? "p"}`}>Reserve item #{e.item_id} qty {e.quantity}{e.reservation_id ? ` as #${e.reservation_id}` : ""}.</p>)}
                {!allocationPreview.reservations_created.length && <p className="text-slate-500">No stock reservations.</p>}
              </div>
            </div>
            {!!allocationPreview.skipped.length && (
              <div className="mt-3">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Skipped</p>
                {allocationPreview.skipped.map((e, i) => <p key={`sk-${e.item_id}-${i}`} className="text-slate-600">Item #{e.item_id}{e.order_id ? ` / order #${e.order_id}` : ""}: {e.reason}</p>)}
              </div>
            )}
          </div>
        )}

        {/* Pipeline cards */}
        <div className="flex gap-3 overflow-x-auto pb-2">
          {boardPipeline.map((row) => (
            <button
              key={`${row.project_id}-${row.is_planning_preview ? "p" : "c"}`}
              type="button"
              className={cn(
                "min-w-[250px] rounded-2xl border px-4 py-4 text-left transition",
                row.project_id === selectedProjectId ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-white hover:border-slate-300",
              )}
              onClick={() => selectProject(row.project_id)}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="font-semibold">{row.name}</p>
                <span className={cn("rounded-full px-2 py-1 text-[11px] font-semibold", row.project_id === selectedProjectId ? "bg-white/10 text-white" : statusTone(row.status))}>{row.status}</span>
              </div>
              <p className={cn("mt-2 text-xs", row.project_id === selectedProjectId ? "text-slate-200" : "text-slate-500")}>{row.planned_start}{row.is_planning_preview ? " | preview" : ""}</p>
              <div className={cn("mt-3 grid grid-cols-2 gap-2 text-xs", row.project_id === selectedProjectId ? "text-slate-100" : "text-slate-600")}>
                <div className="rounded-xl bg-black/5 px-2 py-2"><p className="font-semibold">On-Time Gap</p><p>{row.shortage_at_start_total}</p></div>
                <div className="rounded-xl bg-black/5 px-2 py-2"><p className="font-semibold">Generic Before</p><p>{row.cumulative_generic_consumed_before_total}</p></div>
              </div>
            </button>
          ))}
          {!boardPipeline.length && <div className="rounded-2xl border border-dashed border-slate-300 px-5 py-6 text-sm text-slate-500">No pipeline data yet.</div>}
        </div>
      </section>

      {/* ── Netting Grid ── */}
      <section className="panel p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-display text-lg font-semibold">Netting Grid</h3>
            <p className="text-sm text-muted-foreground">Supply-source chips show on-time coverage and later recovery sources.</p>
          </div>
        </div>
        {analysisLoading && <p className="text-sm text-slate-500">Loading planning board...</p>}
        {!analysisLoading && analysisData && (
          <div className="overflow-x-auto">
            <table className="min-w-[1520px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">Item</th>
                  <th className="px-2 py-2">Required</th>
                  <th className="px-2 py-2">Covered By Start</th>
                  <th className="px-2 py-2">On-Time Gap</th>
                  <th className="px-2 py-2">Recovered Later</th>
                  <th className="px-2 py-2">Remaining</th>
                  <th className="px-2 py-2">Coverage Breakdown</th>
                  <th className="px-2 py-2">Recovery Breakdown</th>
                  <th className="px-2 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {analysisData.rows.map((row) => <PlanningBoardRow key={row.item_id} row={row} projectId={analysisData.project.project_id} />)}
                {!analysisData.rows.length && (
                  <tr><td className="px-2 py-5 text-slate-500" colSpan={9}>No requirement rows for this project.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
